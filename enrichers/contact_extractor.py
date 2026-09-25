"""
Step 3d — Contact extraction from the prospect's own website.

Every address found here is free and already verified by the fact that the
company published it. The cascade tries this before spending a single credit,
so the quality of this module decides how much of a 50-credit month survives.
"""
import logging
import re
import time
import unicodedata
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

import config
from api.quota_db import normalize_name
from enrichers.phone_extractor import ExtractedPhone, extract_phones

logger = logging.getLogger(__name__)

# Slugs of pages worth following, in FR, EN and transliterated AR.
EXTRACTION_SLUGS: tuple[str, ...] = (
    "contact", "contactez", "contactez-nous", "contact-us", "nous-contacter",
    "a-propos", "apropos", "about", "about-us", "qui-sommes-nous",
    "equipe", "team", "notre-equipe", "our-team",
    "mentions-legales", "legal", "impressum",
    "carriere", "carrieres", "careers", "jobs", "recrutement",
    "ittasal", "ittasal-bina", "man-nahnu", "fariq",
)

MAX_PAGES = 5
PAGE_TIMEOUT = 8

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r'mailto:([^"\'?>\s]+)', re.IGNORECASE)
_CF_RE = re.compile(r'data-cfemail="([0-9a-fA-F]+)"')

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_WHATSAPP_RE = re.compile(r"https?://(?:wa\.me|api\.whatsapp\.com|web\.whatsapp\.com)/", re.I)
_FACEBOOK_RE = re.compile(r"https?://(?:www\.)?facebook\.com/(?!sharer|share\.php)[A-Za-z0-9._\-]+/?", re.I)
_INSTAGRAM_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?!p/|explore/)[A-Za-z0-9._\-]+/?", re.I)
_LINKEDIN_COMPANY_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9._\-]+/?", re.I)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Image assets whose "@2x" suffix parses as an email local part.
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp")

_TECHNICAL_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "nepasrepondre",
    "webmaster", "postmaster", "hostmaster", "abuse", "mailer-daemon",
    "bounce", "bounces", "notification", "notifications", "automated",
})

_GENERIC_LOCALS = frozenset({
    "contact", "contacts", "info", "infos", "information", "hello", "bonjour",
    "commercial", "sales", "vente", "ventes", "support", "service", "sav",
    "admin", "administration", "direction", "secretariat", "accueil",
    "rh", "hr", "recrutement", "jobs", "emploi", "compta", "comptabilite",
    "facturation", "billing", "devis", "marketing", "presse", "press",
})

_WEBMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "outlook.com",
    "outlook.fr", "live.com", "live.fr", "msn.com", "yahoo.com", "yahoo.fr",
    "ymail.com", "aol.com", "icloud.com", "me.com", "protonmail.com",
    "proton.me", "gmx.com", "gmx.fr", "orange.fr", "wanadoo.fr", "free.fr",
    "sfr.fr", "laposte.net", "menara.ma", "iam.net.ma",
})

# Words that precede "at" in ordinary prose. The bracketed masking forms
# ([at], (at)) are unambiguous, but a bare " at " is far more often English
# or French text than an obfuscated address — "find out more at acme.com"
# must not become more@acme.com. A fabricated address is worse than a
# missing one: it is classified, enters the cascade, spends a paid
# verification, and on a catch-all domain is accepted as a real contact.
_PROSE_BEFORE_AT = frozenset({
    "more", "out", "here", "us", "now", "back", "look", "available",
    "based", "located", "arriving", "starting", "us", "home", "online",
    "nous", "ici", "plus", "situe", "situes", "situee", "basee", "bases",
    "disponible", "disponibles", "retrouvez", "retrouvez-nous", "rendez",
})


@dataclass(frozen=True)
class ExtractedEmail:
    value: str
    kind: str          # nominatif_lead | nominatif_autre | generique | webmail
    source_url: str


def decode_cloudflare(html: str) -> str:
    """Replace Cloudflare-obfuscated addresses with their plaintext form.

    Cloudflare hex-encodes the address XOR'd against its own first byte. A
    contact page behind this protection contains no readable address at all,
    so skipping the decode silently turns a perfectly good free lookup into a
    paid one.
    """
    def _decode(match: re.Match) -> str:
        blob = match.group(1)
        try:
            key = int(blob[:2], 16)
            decoded = "".join(
                chr(int(blob[i:i + 2], 16) ^ key) for i in range(2, len(blob), 2)
            )
        except ValueError:
            return match.group(0)
        return f'data-cfemail="{blob}">{decoded}<'

    return _CF_RE.sub(_decode, html)


def _is_plausible(address: str) -> bool:
    lowered = address.lower()
    if lowered.endswith(_IMAGE_EXT):
        return False
    local, _, domain = lowered.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if local in _TECHNICAL_LOCALS:
        return False
    # "logo@2x" and friends: a purely numeric local part is never a mailbox.
    if local.isdigit() or re.fullmatch(r"\d+x", local):
        return False
    return True


def _strip_accents(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _bare_at_replacement(match: re.Match) -> str:
    """Decide whether one bare " word at domain" occurrence is a real mailbox.

    Unlike the bracketed forms, a bare " at " has no unambiguous masking
    intent — it is legitimate English/French prose far more often than an
    obfuscated address. Reject the rewrite (return the match unchanged) when
    the word preceding "at" is known prose, is a single character, or ends in
    a hyphen — all signs of a fragment rather than a real local part.
    """
    local = match.group(1)
    normalized = _strip_accents(local).lower()
    if normalized in _PROSE_BEFORE_AT or len(local) == 1 or local.endswith("-"):
        return match.group(0)
    return f"{local}@"


def _unmask(text: str) -> str:
    """Rewrite [at] / (at) / " at " and their dot equivalents into a real address."""
    unmasked = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text, flags=re.IGNORECASE)
    unmasked = re.sub(
        r"([A-Za-z0-9._%+\-]+)\s+at\s+(?=[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
        _bare_at_replacement,
        unmasked,
        flags=re.IGNORECASE,
    )
    unmasked = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", unmasked, flags=re.IGNORECASE)
    return re.sub(r"\s+dot\s+", ".", unmasked, flags=re.IGNORECASE)


def extract_emails(html: str, source_url: str,
                   company_domain: str = "") -> list[ExtractedEmail]:
    """Collect every plausible address on one page, deduplicated.

    `company_domain` filters out the web agency that built the site: agencies
    sign their work in the footer, and their address is a dead end that costs
    a contact attempt. When it is empty every domain is kept — the caller has
    not told us which one is the prospect's.
    """
    if not html:
        return []

    decoded = decode_cloudflare(html)
    haystack = _unmask(decoded)

    candidates: list[str] = _MAILTO_RE.findall(haystack)
    candidates += _EMAIL_RE.findall(haystack)

    wanted = normalize_name(company_domain).replace(" ", "")
    seen: set[str] = set()
    found: list[ExtractedEmail] = []
    for raw in candidates:
        address = raw.strip().strip(".,;:").lower()
        if address in seen or not _is_plausible(address):
            continue
        if wanted and address.partition("@")[2] != company_domain.lower():
            if address.partition("@")[2] not in _WEBMAIL_DOMAINS:
                continue
        seen.add(address)
        found.append(ExtractedEmail(value=address, kind="", source_url=source_url))
    return found


def classify_email(email: str, first_name: str, last_name: str, domain: str) -> str:
    """Sort one address into the four buckets the cascade branches on.

    Order matters: webmail is checked first because a personal Gmail belonging
    to the lead is still not the corporate mailbox, and treating it as a
    nominative company address would send mail to the wrong place.
    """
    local, _, mail_domain = (email or "").lower().partition("@")
    if mail_domain in _WEBMAIL_DOMAINS:
        return "webmail"
    if local in _GENERIC_LOCALS:
        return "generique"

    first = normalize_name(first_name).replace(" ", "")
    last = normalize_name(last_name).replace(" ", "")
    stripped = re.sub(r"[^a-z0-9]", "", local)
    if not first and not last:
        return "nominatif_autre"

    # A local part that contains the surname, or the initial plus the surname,
    # or both given and family name in either order, belongs to this lead.
    matches = (
        (first and last and first in stripped and last in stripped)
        or (last and stripped == last)
        or (first and stripped == first)
        or (last and first and stripped == f"{first[0]}{last}")
        or (last and first and stripped == f"{last}{first[0]}")
    )
    return "nominatif_lead" if matches else "nominatif_autre"


def internal_contact_links(html: str, base_url: str) -> list[str]:
    """Same-host links whose path matches a contact-page slug, capped at MAX_PAGES."""
    if not html:
        return []
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    seen: set[str] = set()
    links: list[str] = []
    for href in _HREF_RE.findall(html):
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower().removeprefix("www.") != base_host:
            continue
        path = parsed.path.rstrip("/").lower()
        slug = path.rsplit("/", 1)[-1]
        if not slug or not any(slug.startswith(s) for s in EXTRACTION_SLUGS):
            continue
        canonical = f"{parsed.scheme}://{parsed.netloc}{path}"
        if canonical in seen:
            continue
        seen.add(canonical)
        links.append(canonical)
        if len(links) >= MAX_PAGES:
            break
    return links


def _first(pattern: re.Pattern, html: str):
    match = pattern.search(html or "")
    return match.group(0).rstrip("/") if match else None


def extract_social(html: str) -> dict:
    """Social handles and, crucially, whether the company publishes a WhatsApp link.

    whatsapp is true only when the company put the link on its own site. We
    never probe whether a number is registered on WhatsApp: that queries a
    third party's account without their knowledge, for a signal the company
    would have advertised if it wanted to be reached that way.
    """
    return {
        "whatsapp": bool(_WHATSAPP_RE.search(html or "")),
        "facebook_url": _first(_FACEBOOK_RE, html),
        "instagram_url": _first(_INSTAGRAM_RE, html),
        "linkedin_company_url": _first(_LINKEDIN_COMPANY_RE, html),
    }


def _robots_allows(base_url: str, path: str) -> bool:
    """Honour robots.txt. A site that cannot be reached for its robots file is
    treated as permissive — the same default a browser applies."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.read()
        return parser.can_fetch(_UA, path)
    except Exception:
        return True


def harvest_contacts(lead: dict, page) -> dict:
    """Walk the homepage plus up to MAX_PAGES contact pages and collect everything.

    Returns emails already classified, phone numbers, social handles and the
    source URL of each find. Never raises: a site that blocks us costs the
    lead its free contact route, not the run.

    `website` gates the whole function: Task 7 established that `_page_fetch`
    stays populated even when the coherence check rejects the site as
    belonging to a different company, in which case `lead["website"]` is
    None. Without this gate we would crawl and harvest another company's
    contact pages.
    """
    website = lead.get("website") or ""
    if not website or page is None or not getattr(page, "html", ""):
        return {"emails": [], "phones": [], "social": extract_social(""), "pages_crawled": 0}

    domain = urlparse(website).netloc.lower().removeprefix("www.")
    first = (lead.get("first_name") or "")
    last = (lead.get("last_name") or "")
    location = lead.get("location") or ""

    collected: dict[str, ExtractedEmail] = {}
    collected_phones: dict[str, ExtractedPhone] = {}
    social = extract_social(page.html)
    home_url = page.url or website
    for found in extract_emails(page.html, home_url, company_domain=domain):
        collected[found.value] = found
    for found in extract_phones(page.html, location, source_url=home_url):
        collected_phones[found.e164] = found

    pages = 0
    for url in internal_contact_links(page.html, website):
        if not _robots_allows(website, urlparse(url).path):
            logger.debug(f"robots.txt disallows {url}")
            continue
        try:
            resp = requests.get(url, headers={"User-Agent": _UA},
                                timeout=PAGE_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.debug(f"Contact page unreachable {url}: {exc}")
            continue
        pages += 1
        for found in extract_emails(resp.text, url, company_domain=domain):
            collected.setdefault(found.value, found)
        for found in extract_phones(resp.text, location, source_url=url):
            collected_phones.setdefault(found.e164, found)
        for key, value in extract_social(resp.text).items():
            if key == "whatsapp":
                social[key] = social[key] or value
            elif not social.get(key):
                social[key] = value
        time.sleep(config.REQUEST_DELAY / 2)

    classified = [
        ExtractedEmail(value=e.value,
                       kind=classify_email(e.value, first, last, domain),
                       source_url=e.source_url)
        for e in collected.values()
    ]
    return {
        "emails": classified,
        "phones": list(collected_phones.values()),
        "social": social,
        "pages_crawled": pages,
    }
