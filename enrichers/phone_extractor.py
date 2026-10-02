"""
Phone extraction from the prospect's own website.

Since no mobile is ever purchased (a Prospeo mobile costs 10 credits, a tenth
of the monthly allowance), every phone in the export comes from here.
Typing mobile vs landline matters: the two carry different weight in
reachability, and only phonenumbers knows that Morocco's 07 range is mobile
or that Côte d'Ivoire renumbered in 2021.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

import phonenumbers
from phonenumbers import PhoneNumberType

from processors.icp_rules import normalize_label

logger = logging.getLogger(__name__)

# Country hints, keyed on what an Apollo "location" column actually contains:
# a city, a country, or "City, Country". Kept deliberately small and focused
# on the target markets; an unknown location yields None, which drops national
# numbers rather than minting a wrong E.164 (see _parse).
COUNTRY_HINTS: dict[str, str] = {
    "maroc": "MA", "morocco": "MA", "casablanca": "MA", "rabat": "MA",
    "marrakech": "MA", "tanger": "MA", "tangier": "MA", "fes": "MA",
    "agadir": "MA", "kenitra": "MA", "oujda": "MA", "tetouan": "MA",
    # Mid-size Moroccan cities, and the English spelling Apollo uses for
    # Marrakech. A location cell often carries only the city.
    "marrakesh": "MA", "meknes": "MA", "mohammedia": "MA", "settat": "MA",
    "el jadida": "MA", "nador": "MA", "essaouira": "MA", "ouarzazate": "MA",
    "khouribga": "MA", "berrechid": "MA", "temara": "MA", "beni mellal": "MA",
    "laayoune": "MA", "dakhla": "MA",
    "algerie": "DZ", "algeria": "DZ", "alger": "DZ", "algiers": "DZ", "oran": "DZ",
    "tunisie": "TN", "tunisia": "TN", "tunis": "TN", "sfax": "TN",
    "senegal": "SN", "dakar": "SN",
    "cote d'ivoire": "CI", "cote d ivoire": "CI", "ivory coast": "CI",
    "abidjan": "CI", "yamoussoukro": "CI",
    "cameroun": "CM", "cameroon": "CM", "douala": "CM", "yaounde": "CM",
    "gabon": "GA", "libreville": "GA",
    "benin": "BJ", "cotonou": "BJ",
    "burkina faso": "BF", "ouagadougou": "BF",
    "mali": "ML", "bamako": "ML",
    "niger": "NE", "niamey": "NE",
    "togo": "TG", "lome": "TG",
    "guinee": "GN", "guinea": "GN", "conakry": "GN",
    "congo": "CG", "brazzaville": "CG",
    "rdc": "CD", "drc": "CD", "kinshasa": "CD",
    "madagascar": "MG", "antananarivo": "MG",
    "mauritanie": "MR", "mauritania": "MR", "nouakchott": "MR",
    "tchad": "TD", "chad": "TD", "ndjamena": "TD",
    "nigeria": "NG", "lagos": "NG", "abuja": "NG",
    "ghana": "GH", "accra": "GH",
    "kenya": "KE", "nairobi": "KE",
    "egypte": "EG", "egypt": "EG", "le caire": "EG", "cairo": "EG",
    "afrique du sud": "ZA", "south africa": "ZA", "johannesburg": "ZA",
    "france": "FR", "paris": "FR", "lyon": "FR", "marseille": "FR",
    "belgique": "BE", "belgium": "BE", "bruxelles": "BE", "brussels": "BE",
    "suisse": "CH", "switzerland": "CH", "geneve": "CH", "geneva": "CH",
    "luxembourg": "LU",
    "canada": "CA", "montreal": "CA", "quebec": "CA", "toronto": "CA",
}

_MOBILE_TYPES = frozenset({
    PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE,
})

# Runs of digits long enough to be company identifiers rather than phones.
_TOO_LONG_RE = re.compile(r"\d{15,}")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ExtractedPhone:
    e164: str
    kind: str          # "mobile" | "fixe"
    source_url: str = ""


def country_hint(location: str) -> Optional[str]:
    """Resolve an Apollo location string to an ISO alpha-2 code, or None.

    The longest matching key wins so that "Congo Kinshasa" resolves to CD
    rather than CG, mirroring the tie-break rule in processors/icp_rules.py.
    """
    normalized = normalize_label(location or "")
    if not normalized:
        return None
    best_key, best_len = None, 0
    for key, code in COUNTRY_HINTS.items():
        if key in normalized and len(key) > best_len:
            best_key, best_len = code, len(key)
    return best_key


def _kind(number) -> Optional[str]:
    number_type = phonenumbers.number_type(number)
    if number_type in _MOBILE_TYPES:
        return "mobile"
    if number_type == PhoneNumberType.FIXED_LINE:
        return "fixe"
    return None


def extract_phones(html: str, location: str, source_url: str = "") -> list[ExtractedPhone]:
    """Collect valid phone numbers from a page, normalized to E.164.

    A national-format number without a country hint is dropped, not guessed:
    "0661234567" is a Moroccan mobile, a French mobile or an Ivorian landline
    depending on where you stand, and an invented +212 would look exactly as
    trustworthy as a real one in the export.
    """
    if not html:
        return []
    # A newline, not a plain space, replaces each tag: libphonenumber's
    # matcher treats two whitespace-only-separated digit runs as one
    # over-long candidate and discards it rather than splitting it back into
    # two valid numbers ("<p>05...</p><p>06...</p>" collapsed to a single
    # space between the numbers silently dropped both).
    text = _TAG_RE.sub("\n", html)
    text = _TOO_LONG_RE.sub(" ", text)
    region = country_hint(location)

    seen: set[str] = set()
    found: list[ExtractedPhone] = []
    for region_hint in (region, None):
        if region_hint is None and region is not None:
            continue
        for match in phonenumbers.PhoneNumberMatcher(
            text, region_hint, leniency=phonenumbers.Leniency.VALID
        ):
            e164 = phonenumbers.format_number(
                match.number, phonenumbers.PhoneNumberFormat.E164
            )
            if e164 in seen:
                continue
            kind = _kind(match.number)
            if kind is None:
                continue
            seen.add(e164)
            found.append(ExtractedPhone(e164=e164, kind=kind, source_url=source_url))
    return found


def best_phone(phones: list[ExtractedPhone]) -> Optional[ExtractedPhone]:
    """A mobile always beats a landline: it reaches a person, not a switchboard."""
    if not phones:
        return None
    return next((p for p in phones if p.kind == "mobile"), phones[0])
