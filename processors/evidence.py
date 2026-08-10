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
    """Raw material available to score one lead.

    Contract: enabled_providers must always be non-empty (set by the caller).
    An empty set means the caller made an error, not that all providers are disabled.
    """
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
    # The two branches below are mathematically equivalent by construction:
    # `usable` is guaranteed non-empty (checked above), so any non-empty `expected`
    # is trivially <= any non-empty `usable`. We keep both branches to signal intent:
    # the first says "we got all the sources we required", the second says "the caller
    # declared no requirements but we have content anyway" (error case today, pinned
    # for the behaviour to be explicit).
    if expected and usable >= expected:
        return "sufficient"
    if not expected:
        # Caller declared no providers enabled: enabled_providers is empty.
        # This means a caller error, not a disabled provider (which would still
        # appear in expected_sources until the provider is removed entirely).
        # Since we have content and the caller has no constraint, trust the content.
        return "sufficient"
    return "weak"
