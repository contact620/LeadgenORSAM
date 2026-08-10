"""
Evidence accounting for ICP scoring.

`evidence_level` is measured, never declared by the model: a model that says
it is confident has no bearing on whether sources actually exist.

LinkedIn is deliberately absent — scrapers/website_scraper.py forces
linkedin_text = "" to avoid getting the account banned, so it can never be
a source.
"""
from dataclasses import dataclass, field

MIN_SOURCE_CHARS = 200

# Perplexity's polite way of saying it found nothing.
_PERPLEXITY_EMPTY_MARKERS = (
    "aucun signal récent identifié",
    "aucun signal recent identifie",
    "non disponible",
    "aucune information",
)

SOURCE_PROVIDERS = frozenset({"website", "perplexity"})


@dataclass
class Evidence:
    """Raw material available to score one lead."""
    website_text: str = ""
    website_coherent: bool = False
    perplexity_fields: dict[str, str | None] = field(default_factory=dict)
    enabled_providers: frozenset[str] = frozenset()


def _perplexity_is_substantive(fields: dict[str, str | None]) -> bool:
    for value in (fields or {}).values():
        if not value:
            continue
        lowered = str(value).strip().lower()
        if len(lowered) < 10:
            continue
        if any(marker in lowered for marker in _PERPLEXITY_EMPTY_MARKERS):
            continue
        return True
    return False


def usable_sources(ev: Evidence) -> set[str]:
    """Sources that actually carry exploitable content."""
    found: set[str] = set()
    if ev.website_coherent and len(ev.website_text or "") >= MIN_SOURCE_CHARS:
        found.add("website")
    if _perplexity_is_substantive(ev.perplexity_fields):
        found.add("perplexity")
    return found


def expected_sources(ev: Evidence) -> set[str]:
    """Sources we are entitled to expect, given the providers enabled this run."""
    return set(SOURCE_PROVIDERS & ev.enabled_providers)


def compute_evidence_level(ev: Evidence, identity_confirmed: bool) -> str:
    """Return 'none' | 'weak' | 'sufficient'."""
    if not identity_confirmed:
        return "none"

    usable = usable_sources(ev)
    if not usable:
        return "none"

    expected = expected_sources(ev)
    if expected and usable >= expected:
        return "sufficient"
    if not expected:
        # No provider declared enabled but content exists — trust the content.
        return "sufficient"
    return "weak"
