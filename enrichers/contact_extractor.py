"""
Step 3d — Contact extraction from the prospect's own website.

Every address found here is free and already verified by the fact that the
company published it. The cascade tries this before spending a single credit,
so the quality of this module decides how much of a 50-credit month survives.
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from api.quota_db import normalize_name

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


def _unmask(text: str) -> str:
    """Rewrite [at] / (at) / " at " and their dot equivalents into a real address."""
    unmasked = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text, flags=re.IGNORECASE)
    unmasked = re.sub(r"\s+at\s+(?=[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", "@", unmasked, flags=re.IGNORECASE)
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
