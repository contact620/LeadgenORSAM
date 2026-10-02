import pytest

from enrichers.contact_extractor import (
    classify_email,
    decode_cloudflare,
    extract_emails,
)
from enrichers.contact_extractor import (
    MAX_PAGES, ExtractedEmail, extract_social, find_colleague,
    harvest_contacts, internal_contact_links,
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


# ── Crawl des pages contact ──────────────────────────────────────────────────

def test_contact_pages_are_followed():
    html = """
      <a href="/contact">Contact</a>
      <a href="/a-propos">À propos</a>
      <a href="/notre-equipe">Équipe</a>
      <a href="/blog/article-42">Blog</a>
      <a href="/produits">Produits</a>
    """
    links = internal_contact_links(html, "https://acme.ma/")
    assert "https://acme.ma/contact" in links
    assert "https://acme.ma/a-propos" in links
    assert "https://acme.ma/notre-equipe" in links
    assert not any("blog" in l or "produits" in l for l in links)


def test_transliterated_arabic_slugs_are_followed():
    links = internal_contact_links('<a href="/ittasal-bina">اتصل بنا</a>', "https://acme.ma/")
    assert "https://acme.ma/ittasal-bina" in links


def test_external_links_are_never_followed():
    html = '<a href="https://autre-site.ma/contact">Contact</a>'
    assert internal_contact_links(html, "https://acme.ma/") == []


def test_at_most_five_pages_are_followed():
    html = "".join(f'<a href="/contact-{i}">c</a>' for i in range(30))
    assert len(internal_contact_links(html, "https://acme.ma/")) <= MAX_PAGES


def test_the_same_page_is_not_queued_twice():
    html = '<a href="/contact">A</a><a href="/contact">B</a><a href="/contact/">C</a>'
    assert len(internal_contact_links(html, "https://acme.ma/")) == 1


# ── WhatsApp et réseaux ───────────────────────────────────────────────────────

@pytest.mark.parametrize("href", [
    "https://wa.me/212600000000",
    "https://api.whatsapp.com/send?phone=212600000000",
    "https://web.whatsapp.com/send?phone=212600000000",
])
def test_whatsapp_link_published_by_the_company_is_detected(href):
    assert extract_social(f'<a href="{href}">WhatsApp</a>')["whatsapp"] is True


def test_no_whatsapp_link_means_false_not_a_probe():
    """We never test whether a number is registered on WhatsApp: that probes a
    third party's account. Only a link the company published itself counts."""
    assert extract_social("<p>+212 6 00 00 00 00</p>")["whatsapp"] is False


def test_social_profiles_are_extracted():
    html = """
      <a href="https://www.facebook.com/acme.maroc">FB</a>
      <a href="https://instagram.com/acme_maroc">IG</a>
      <a href="https://www.linkedin.com/company/acme-maroc">LI</a>
    """
    social = extract_social(html)
    assert social["facebook_url"] == "https://www.facebook.com/acme.maroc"
    assert social["instagram_url"] == "https://instagram.com/acme_maroc"
    assert social["linkedin_company_url"] == "https://www.linkedin.com/company/acme-maroc"


def test_a_personal_linkedin_profile_is_not_the_company_page():
    html = '<a href="https://www.linkedin.com/in/karim-elamrani">Karim</a>'
    assert extract_social(html)["linkedin_company_url"] is None


def test_share_widgets_are_not_company_profiles():
    """Share buttons point at facebook.com/sharer, not at a page we can use."""
    html = '<a href="https://www.facebook.com/sharer/sharer.php?u=https://acme.ma">Partager</a>'
    assert extract_social(html)["facebook_url"] is None


# ── Format d'entreprise déduit d'un collègue ──────────────────────────────────

def _autre(value):
    return ExtractedEmail(value=value, kind="nominatif_autre",
                          source_url="https://acme.ma/equipe")


def test_a_team_card_ties_the_address_to_its_owner():
    """What infer_format needs and never received: the name that explains the
    local part. Three paid verifications become one."""
    html = """
      <div class="card">
        <h3>Sara Bennani</h3>
        <p>Directrice commerciale</p>
        <a href="mailto:s.bennani@acme.ma">s.bennani@acme.ma</a>
      </div>
    """
    assert find_colleague(html, [_autre("s.bennani@acme.ma")], "Acme") == {
        "email": "s.bennani@acme.ma", "first_name": "Sara", "last_name": "Bennani",
    }


def test_the_name_is_found_after_the_address_too():
    html = '<p>s.bennani@acme.ma — Sara Bennani, direction commerciale</p>'
    colleague = find_colleague(html, [_autre("s.bennani@acme.ma")], "Acme")
    assert colleague["first_name"] == "Sara"


def test_a_name_the_address_does_not_match_is_discarded():
    """The safety margin: a pair that explains nothing about the local part is
    not reported. Guessing would hand the cascade a candidate in the wrong
    format and spend a verification on an address nobody owns."""
    html = '<p>Sara Bennani</p><p>sb2024@acme.ma</p>'
    assert find_colleague(html, [_autre("sb2024@acme.ma")], "Acme") is None


def test_a_name_too_far_from_the_address_is_not_its_owner():
    html = ("<p>Sara Bennani</p>" + "<p>texte de remplissage. </p>" * 40
            + "<p>s.bennani@acme.ma</p>")
    assert find_colleague(html, [_autre("s.bennani@acme.ma")], "Acme") is None


def test_the_company_name_is_never_taken_for_a_person():
    """"Atlas Maroc" next to a.maroc@ reproduces the p.nom format exactly, so
    the format test alone would accept it. The company signing its own page is
    not a colleague, and the address is not built from its name."""
    html = '<footer>Atlas Maroc<br>a.maroc@atlas.ma</footer>'
    assert find_colleague(html, [_autre("a.maroc@atlas.ma")], "Atlas Maroc") is None


def test_the_lead_own_address_is_not_a_colleague():
    """A nominatif_lead address is the contact itself: the cascade takes it
    outright at step (a) and has no format to deduce."""
    html = '<p>Karim El Amrani — k.elamrani@acme.ma</p>'
    own = ExtractedEmail(value="k.elamrani@acme.ma", kind="nominatif_lead",
                         source_url="https://acme.ma/equipe")
    assert find_colleague(html, [own], "Acme") is None


def test_a_cloudflare_protected_colleague_is_still_associated():
    """The address only exists once decoded, so the association has to run on
    the decoded page or the whole feature misses every protected site."""
    # "s.bennani@acme.ma" XOR'd against key 0x7a, as Cloudflare encodes it.
    plain = "s.bennani@acme.ma"
    blob = "7a" + "".join(f"{ord(c) ^ 0x7a:02x}" for c in plain)
    html = (f'<h3>Sara Bennani</h3><a class="__cf_email__" '
            f'data-cfemail="{blob}">[email&#160;protected]</a>')
    colleague = find_colleague(html, [_autre(plain)], "Acme")
    assert colleague["last_name"] == "Bennani"


def test_harvest_contacts_publishes_the_colleague_it_found():
    """End to end: the key email_cascade step (b) reads."""
    class _Page:
        url = "https://acme.ma/"
        html = """
          <h3>Sara Bennani</h3>
          <a href="mailto:s.bennani@acme.ma">Écrire</a>
        """

    lead = {"first_name": "Karim", "last_name": "El Amrani", "company": "Acme",
            "website": "https://acme.ma", "location": "Casablanca, Maroc"}
    contacts = harvest_contacts(lead, _Page())

    assert contacts["colleague"] == {
        "email": "s.bennani@acme.ma", "first_name": "Sara", "last_name": "Bennani",
    }


def test_harvest_contacts_reports_no_colleague_rather_than_a_guess():
    class _Page:
        url = "https://acme.ma/"
        html = '<p>Nous Contacter : contact@acme.ma</p>'

    lead = {"first_name": "Karim", "last_name": "El Amrani", "company": "Acme",
            "website": "https://acme.ma", "location": "Casablanca, Maroc"}
    assert harvest_contacts(lead, _Page())["colleague"] is None
