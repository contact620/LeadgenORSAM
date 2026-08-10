"""
Company-name and website coherence helpers.

Used to reject search results that belong to a different company than the
Apollo prospect. The matching rule is deliberately strict: a single generic
word in common (``financial``, ``group``, ``digital``...) must never be
enough to accept a domain.
"""
import re
import unicodedata
from dataclasses import dataclass

# Legal forms carry no identifying signal.
LEGAL_SUFFIXES = frozenset({
    "sarl", "sa", "sas", "sasu", "eurl", "sci", "snc", "scop",
    "llc", "inc", "ltd", "limited", "plc", "corp", "corporation",
    "gmbh", "ag", "bv", "nv", "srl", "spa", "oy", "ab",
})

# Words too common to identify a company on their own.
GENERIC_TOKENS = frozenset({
    "financial", "finance", "group", "groupe", "holding", "holdings",
    "tech", "technologies", "technology", "consulting", "conseil",
    "services", "service", "solutions", "solution", "digital",
    "international", "partners", "associes", "company", "agency",
    "agence", "systems", "global", "france", "maroc", "africa",
})

# Words that make up whole homepage titles and name no company. A title built
# only from these ("Accueil", "Bienvenue sur notre site", "Home | Contact")
# identifies nobody, so its silence about the prospect proves nothing.
PAGE_TITLE_NOISE = frozenset({
    "accueil", "bienvenue", "home", "welcome", "index", "page", "site",
    "web", "officiel", "official", "website", "internet", "portail",
    "contact", "contactez", "nous", "propos", "about", "apropos",
    "entreprise", "societe", "boutique", "shop", "store", "blog",
    "actualites", "news", "menu", "connexion", "login",
})

_PUNCTUATION_RE = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_www(netloc: str) -> str:
    """Remove a leading 'www.' prefix. Unlike lstrip, never eats characters."""
    lowered = netloc.lower()
    prefix = "www."
    if lowered.startswith(prefix):
        return lowered[len(prefix):]
    return lowered


def _deaccent(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_tokens(name: str) -> set[str]:
    """Lowercase, strip accents and punctuation, split into tokens."""
    if not name:
        return set()
    cleaned = _PUNCTUATION_RE.sub(" ", _deaccent(name).lower())
    return {t for t in _WHITESPACE_RE.split(cleaned) if t}


def significant_tokens(name: str) -> set[str]:
    """Tokens left once legal forms and generic words are removed."""
    return {
        t for t in normalize_tokens(name)
        if t not in LEGAL_SUFFIXES and t not in GENERIC_TOKENS and len(t) > 2
    }


def title_names_a_company(page_title: str) -> bool:
    """True when the page title identifies some company, whichever one.

    Used to decide whether a title's failure to mention the prospect is
    evidence of a *different* entity or merely an uninformative title.
    """
    return bool(significant_tokens(page_title) - PAGE_TITLE_NOISE)


def names_match(candidate: str, reference: str, min_overlap: float = 0.5) -> bool:
    """
    True when both names plausibly designate the same company.

    Compares significant tokens only. When either side has no significant
    token left, falls back to requiring identical full token sets — this
    keeps "Digital Services" from matching "Digital Solutions".
    """
    if not candidate or not reference:
        return False

    cand_sig = significant_tokens(candidate)
    ref_sig = significant_tokens(reference)

    if not cand_sig or not ref_sig:
        cand_all = normalize_tokens(candidate)
        ref_all = normalize_tokens(reference)
        return bool(cand_all) and cand_all == ref_all

    overlap = len(cand_sig & ref_sig) / min(len(cand_sig), len(ref_sig))
    return overlap >= min_overlap


MIN_TEXT_FOR_VERDICT = 80  # characters below which the page proves nothing


@dataclass
class CoherenceResult:
    """Outcome of a company/website coherence check."""
    coherent: bool
    verified: bool          # False = not enough data to conclude, never a rejection
    reason: str | None = None


def check_site_coherence(
    company: str,
    page_title: str,
    page_text: str,
) -> CoherenceResult:
    """
    Decide whether a scraped page really belongs to the prospect's company.

    Rejects only on positive evidence of a different entity: the page names
    an identifiable company and it is not this one. Everything else — a thin
    page, a title that names no company, a prospect whose name is entirely
    generic — returns coherent=True with verified=False. A rejection costs
    the lead its website, ten hit-score points and any chance of reaching
    evidence_level="sufficient", so it must be earned, not assumed.

    Country-contradiction checking was deliberately removed (2026-08-10): it
    produced hard rejects on the client's core market, e.g. a Paris firm
    whose page mentions "investir à Casablanca" being flagged France/Maroc,
    or a Tunisian company naming a Lausanne partner being assigned
    Switzerland because the longer alias won the tie-break. The trade-off is
    explicit — cross-border homonyms (a Paris shop vs. an unrelated Dakar
    company both named "Atlas Technologies") are no longer caught — in
    exchange for zero false rejections on legitimate Franco-Maghrebi
    prospects, which matter far more for this pipeline. Do not reintroduce a
    country check without re-reading this note.
    """
    combined = f"{page_title} {page_text}".strip()
    if len(combined) < MIN_TEXT_FOR_VERDICT:
        return CoherenceResult(coherent=True, verified=False,
                               reason="page trop pauvre pour conclure")

    # 1. Company name present in the title or anywhere on the page.
    #    The needle is the significant part of the name when there is one;
    #    for a fully generic name ("Digital Solutions") every token is
    #    generic, so the full token set is used instead — otherwise
    #    names_match falls back to requiring identical token sets and reports
    #    "ne mentionne pas « Digital Solutions »" about a title that spells
    #    it out word for word.
    company_sig = significant_tokens(company)
    needle = company_sig or normalize_tokens(company)
    page_tokens = normalize_tokens(f"{page_title} {page_text}")
    name_found = names_match(page_title, company) or (
        bool(needle) and needle.issubset(page_tokens)
    )

    if not name_found:
        # A name with nothing discriminating in it cannot ground a rejection:
        # "Groupe Conseil" absent from a page proves nothing about whose page
        # it is.
        if not company_sig:
            return CoherenceResult(coherent=True, verified=False,
                                   reason="nom trop générique pour conclure")
        # Rejection requires positive evidence of a *different* entity. A
        # title like "Accueil", "Bienvenue" or "Home" names no company at
        # all, so its silence about the prospect is not evidence of anything.
        if not title_names_a_company(page_title):
            return CoherenceResult(
                coherent=True, verified=False,
                reason="le site ne nomme aucune entreprise identifiable",
            )
        title_label = page_title.strip() or "le site"
        return CoherenceResult(
            coherent=False, verified=True,
            reason=f"{title_label} ne mentionne pas « {company} »",
        )

    return CoherenceResult(coherent=True, verified=True)
