import pytest

from enrichers.contact_extractor import (
    classify_email,
    decode_cloudflare,
    extract_emails,
)


def _values(html, url="https://acme.ma/contact"):
    return {e.value for e in extract_emails(html, url)}


def test_plain_text_email_is_found():
    assert "karim@acme.ma" in _values("<p>Contact : karim@acme.ma</p>")


def test_mailto_is_found():
    assert "karim@acme.ma" in _values('<a href="mailto:karim@acme.ma?subject=Hi">Écrire</a>')


@pytest.mark.parametrize("masked,expected", [
    ("karim[at]acme.ma", "karim@acme.ma"),
    ("karim(at)acme.ma", "karim@acme.ma"),
    ("karim at acme.ma", "karim@acme.ma"),
    ("karim [AT] acme [DOT] ma", "karim@acme.ma"),
    ("karim(at)acme(dot)ma", "karim@acme.ma"),
])
def test_masked_forms_are_recovered(masked, expected):
    assert expected in _values(f"<p>{masked}</p>")


def test_cloudflare_protected_email_is_decoded():
    """Cloudflare replaces the address with a hex blob XOR'd against its first
    byte. Without decoding, a protected contact page yields nothing at all."""
    # "karim@acme.ma" encoded with key 0x7a. Computed directly (key byte
    # followed by each plaintext byte XOR'd against it) and round-tripped
    # through decode_cloudflare's own algorithm to confirm it is correct: the
    # brief's original fixture string does not decode to this address under
    # any of the 256 possible keys.
    encoded = "7a111b0813173a1b19171f54171b"
    html = f'<a href="/cdn-cgi/l/email-protection#{encoded}" class="__cf_email__" data-cfemail="{encoded}">[email&#160;protected]</a>'
    decoded = decode_cloudflare(html)
    assert "karim@acme.ma" in decoded


def test_image_filenames_are_not_emails():
    """logo@2x.png is a retina asset, not a contact."""
    assert _values('<img src="logo@2x.png"><img src="hero@3x.jpg">') == set()


@pytest.mark.parametrize("address", [
    "noreply@acme.ma", "no-reply@acme.ma", "donotreply@acme.ma",
    "webmaster@acme.ma", "postmaster@acme.ma", "abuse@acme.ma",
])
def test_technical_addresses_are_rejected(address):
    assert _values(f"<p>{address}</p>") == set()


def test_the_web_agency_address_is_rejected():
    """Agencies sign their work in the footer. Their address is not the
    prospect's, and mailing it wastes a contact attempt."""
    html = '<footer>Site réalisé par Studio Digital — contact@studiodigital.ma</footer><p>info@acme.ma</p>'
    values = {e.value for e in extract_emails(html, "https://acme.ma/", company_domain="acme.ma")}
    assert values == {"info@acme.ma"}


def test_source_url_is_recorded():
    extracted = extract_emails("<p>karim@acme.ma</p>", "https://acme.ma/contact")
    assert extracted[0].source_url == "https://acme.ma/contact"


def test_duplicates_are_collapsed_case_insensitively():
    html = "<p>Karim@Acme.ma</p><p>karim@acme.ma</p>"
    assert len(extract_emails(html, "https://acme.ma/")) == 1


# ── Classement ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("address", [
    "karim.elamrani@acme.ma", "k.elamrani@acme.ma", "karim@acme.ma",
    "kelamrani@acme.ma", "elamrani.karim@acme.ma",
])
def test_the_lead_own_address_is_nominatif_lead(address):
    assert classify_email(address, "Karim", "El Amrani", "acme.ma") == "nominatif_lead"


def test_another_person_address_is_nominatif_autre():
    assert classify_email("sara.bennani@acme.ma", "Karim", "El Amrani", "acme.ma") == "nominatif_autre"


@pytest.mark.parametrize("address", [
    "contact@acme.ma", "info@acme.ma", "commercial@acme.ma",
    "hello@acme.ma", "bonjour@acme.ma", "sales@acme.ma", "rh@acme.ma",
])
def test_role_addresses_are_generique(address):
    assert classify_email(address, "Karim", "El Amrani", "acme.ma") == "generique"


@pytest.mark.parametrize("address", [
    "karim.elamrani@gmail.com", "karim@hotmail.fr",
    "karim@yahoo.fr", "karim@outlook.com",
])
def test_free_providers_are_webmail(address):
    assert classify_email(address, "Karim", "El Amrani", "acme.ma") == "webmail"


def test_webmail_wins_over_nominatif():
    """A personal Gmail is a webmail first: it is not the company mailbox and
    must not be treated as a corporate nominative address."""
    assert classify_email("karim.elamrani@gmail.com", "Karim", "El Amrani", "acme.ma") == "webmail"


def test_accented_lead_name_still_matches():
    assert classify_email("aicha.benitez@acme.ma", "Aïcha", "Benîtez", "acme.ma") == "nominatif_lead"


# ── False positives beyond the brief ────────────────────────────────────────
#
# The unmasking regexes rewrite " at " and " dot " into "@" and ".", so it is
# worth confirming they leave already-valid addresses alone even when those
# addresses contain the letters "at" as a substring of a longer token (never
# as a standalone, whitespace-delimited word).

def test_at_inside_a_normal_local_part_is_left_alone():
    assert _values("<p>nathalie@acme.ma</p>") == {"nathalie@acme.ma"}


def test_at_inside_a_generic_local_part_is_left_alone():
    assert _values("<p>contact@acme.ma</p>") == {"contact@acme.ma"}


def test_purely_numeric_local_part_is_not_an_email():
    """A numeric local part (as seen in asset filenames like img_2024@2x) is
    never a real mailbox."""
    assert _values("<p>See ref 12345@acme.ma in the invoice.</p>") == set()


def test_masked_form_does_not_fire_on_unrelated_text():
    """"chat" ends in the letters "at", but "at" only unmasks when it stands
    alone as a separate, whitespace-delimited word — so a sentence merely
    containing "at" near a domain-looking token must not be rewritten into an
    address that was never there."""
    assert _values("<p>Come chat with the acme.ma team at the fair.</p>") == set()


# ── Bare " at " must not fabricate addresses from ordinary prose ───────────
#
# The bracketed masking forms ([at], (at)) are unambiguous. A bare " at " is
# not: it is far more often English or French prose than an obfuscated
# address. A fabricated address is worse than a missing one — it gets
# classified, enters the cascade, spends a paid verification, and on a
# catch-all domain is accepted outright as a real contact.

def test_bare_at_does_not_fabricate_from_english_prose():
    assert _values("<p>Find out more at acme.com</p>", "https://acme.com/about") == set()


def test_bare_at_does_not_fabricate_from_french_prose_based():
    assert _values("<p>Nous sommes basés at casablanca.ma</p>", "https://casablanca.ma/about") == set()


def test_bare_at_does_not_fabricate_a_fragment_from_french_prose():
    """The old regex captured only the tail of "basés" (the accent breaks the
    email-local-part character class), fabricating "s@casablanca.ma"."""
    assert "s@casablanca.ma" not in _values(
        "<p>Nous sommes basés at casablanca.ma</p>", "https://casablanca.ma/about"
    )


def test_bare_at_does_not_fabricate_from_french_imperative():
    assert _values("<p>Retrouvez-nous at atlas.ma</p>", "https://atlas.ma/about") == set()


def test_bare_at_still_recovers_a_real_masked_address():
    """The existing, legitimate use case must keep working."""
    assert "karim@acme.ma" in _values("<p>Contact : karim at acme.ma</p>")
