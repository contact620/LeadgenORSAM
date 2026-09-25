import pytest

from enrichers.email_patterns import (
    MAX_CANDIDATES, generate, infer_format, split_name,
)


# ── Normalisation des noms ────────────────────────────────────────────────────

@pytest.mark.parametrize("first,last,expected", [
    ("Karim", "El Amrani", ("karim", "elamrani")),
    ("Fatima", "Ben Ali", ("fatima", "benali")),
    ("Mohamed", "Ait Bella", ("mohamed", "aitbella")),
    ("Ahmed", "Ould Cheikh", ("ahmed", "ouldcheikh")),
    ("Jean-Pierre", "Dupont", ("jeanpierre", "dupont")),
    ("Marie", "Durand-Martin", ("marie", "durandmartin")),
    ("Aïcha", "Benîtez", ("aicha", "benitez")),
    ("  KARIM  ", " el amrani ", ("karim", "elamrani")),
])
def test_particles_and_compounds_are_folded(first, last, expected):
    assert split_name(first, last) == expected


# ── Ordre par défaut ──────────────────────────────────────────────────────────

def test_default_order_is_respected_and_capped():
    candidates = generate("Karim", "El Amrani", "acme.ma")
    assert candidates == [
        "karim.elamrani@acme.ma",
        "kelamrani@acme.ma",
        "karim@acme.ma",
    ]
    assert len(candidates) <= MAX_CANDIDATES


def test_no_duplicate_candidates():
    """When first and last collapse to the same string, several patterns
    produce one address. Verifying it twice would waste a credit."""
    assert len(generate("Ali", "Ali", "acme.ma")) == len(set(generate("Ali", "Ali", "acme.ma")))


def test_a_missing_name_yields_nothing():
    assert generate("", "El Amrani", "acme.ma") == []
    assert generate("Karim", "", "acme.ma") == []
    assert generate("Karim", "El Amrani", "") == []


def test_apollo_spelling_is_used_verbatim():
    """We never invent "Mohammed" from "Mohamed" or vice versa: a plausible
    variant costs a verification and lands on a mailbox that does not exist.

    Not every candidate carries the full first name verbatim — the
    initial-based "pnom" pattern keeps only its first letter, e.g.
    "malaoui@acme.ma" — so the invariant is that the Apollo spelling
    ("mohamed") shows up wherever the full first name is used, and that no
    misspelled variant ("mohammed") is ever produced.
    """
    candidates = generate("Mohamed", "Alaoui", "acme.ma")
    assert "mohammed" not in " ".join(candidates)
    assert any("mohamed" in c for c in candidates)


# ── Déduction du format d'entreprise ──────────────────────────────────────────

@pytest.mark.parametrize("email,first,last,expected", [
    ("sara.bennani@acme.ma", "Sara", "Bennani", "prenom.nom"),
    ("sbennani@acme.ma", "Sara", "Bennani", "pnom"),
    ("sara@acme.ma", "Sara", "Bennani", "prenom"),
    ("bennani.sara@acme.ma", "Sara", "Bennani", "nom.prenom"),
    ("sarabennani@acme.ma", "Sara", "Bennani", "prenomnom"),
    ("s.bennani@acme.ma", "Sara", "Bennani", "p.nom"),
])
def test_format_is_inferred_from_a_colleague_address(email, first, last, expected):
    assert infer_format(email, first, last) == expected


def test_an_unrecognized_shape_yields_no_format():
    assert infer_format("sb2024@acme.ma", "Sara", "Bennani") is None


def test_an_inferred_format_produces_exactly_one_candidate():
    """Knowing the company format turns three paid verifications into one."""
    candidates = generate(
        "Karim", "El Amrani", "acme.ma",
        known_email="sbennani@acme.ma", known_first="Sara", known_last="Bennani",
    )
    assert candidates == ["kelamrani@acme.ma"]


def test_an_uninferable_colleague_address_falls_back_to_the_default_order():
    candidates = generate(
        "Karim", "El Amrani", "acme.ma",
        known_email="sb2024@acme.ma", known_first="Sara", known_last="Bennani",
    )
    assert candidates[0] == "karim.elamrani@acme.ma"
    assert len(candidates) == MAX_CANDIDATES


def test_inference_handles_a_colleague_with_a_particle():
    assert infer_format("y.elidrissi@acme.ma", "Youssef", "El Idrissi") == "p.nom"
