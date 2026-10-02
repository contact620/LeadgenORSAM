"""
Step 5b — Email candidate generation.

Every candidate costs a verification credit, so the module is built to emit as
few as possible: one when a colleague's address on the site reveals the
company format, at most three otherwise. It never invents a spelling variant —
"Mohammed" for "Mohamed" doubles the cost for a mailbox that probably does not
exist, and the Apollo spelling is the only one we have any evidence for.
"""
import re
from typing import Optional

from api.quota_db import normalize_name

MAX_CANDIDATES = 3

# Ordered by how often each format is the house rule. "nom" sits last on
# purpose: it is a common enough format that infer_format must recognise it —
# before this it could not, and a colleague's "bennani@" taught us nothing —
# but MAX_CANDIDATES stops the generator at three, so it is never guessed
# blindly. It only ever produces an address when a colleague's published
# address proves the company uses it.
DEFAULT_ORDER: tuple[str, ...] = (
    "prenom.nom", "pnom", "prenom", "nom.prenom", "prenomnom", "p.nom", "nom",
)

_BUILDERS = {
    "prenom.nom": lambda f, l: f"{f}.{l}",
    "pnom": lambda f, l: f"{f[0]}{l}",
    "prenom": lambda f, l: f,
    "nom.prenom": lambda f, l: f"{l}.{f}",
    "prenomnom": lambda f, l: f"{f}{l}",
    "p.nom": lambda f, l: f"{f[0]}.{l}",
    "nom": lambda f, l: l,
}


def split_name(first: str, last: str) -> tuple[str, str]:
    """Fold a name into its email-safe form.

    Particles are joined rather than dropped: "El Amrani" becomes "elamrani",
    which is how Moroccan and Maghrebi mailboxes are actually spelled. Dropping
    the particle ("amrani") would generate an address for a different person.
    """
    def _fold(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", normalize_name(value))

    return _fold(first), _fold(last)


def infer_format(known_email: str, known_first: str, known_last: str) -> Optional[str]:
    """Recover the company's email format from one colleague's address.

    Returns a key of DEFAULT_ORDER, or None when the local part matches none
    of them — an address like "sb2024@" tells us nothing transferable.
    """
    if not known_email or "@" not in known_email:
        return None
    local = known_email.split("@", 1)[0].strip().lower()
    first, last = split_name(known_first, known_last)
    if not first or not last:
        return None
    for name in DEFAULT_ORDER:
        if _BUILDERS[name](first, last) == local:
            return name
    return None


def generate(first: str, last: str, domain: str,
             known_email: Optional[str] = None,
             known_first: Optional[str] = None,
             known_last: Optional[str] = None) -> list[str]:
    """Produce at most MAX_CANDIDATES addresses, best first.

    A recognised company format collapses the list to a single candidate,
    turning three paid verifications into one.
    """
    folded_first, folded_last = split_name(first, last)
    clean_domain = (domain or "").strip().lower().removeprefix("www.")
    if not folded_first or not folded_last or not clean_domain:
        return []

    inferred = infer_format(known_email or "", known_first or "", known_last or "")
    order = (inferred,) if inferred else DEFAULT_ORDER

    candidates: list[str] = []
    for name in order:
        address = f"{_BUILDERS[name](folded_first, folded_last)}@{clean_domain}"
        if address not in candidates:
            candidates.append(address)
        if len(candidates) >= (1 if inferred else MAX_CANDIDATES):
            break
    return candidates
