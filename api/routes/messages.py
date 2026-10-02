"""
LinkedIn outreach message generation (POST /api/leads/linkedin-message).

The route writes a short first-contact message for one lead, in the language
of the prospect's market. It applies the same rule as the conversion angle:
the message may only contain what the provided facts contain. "No source, no
fact" is enforced twice — the prompt forbids invention, and the code rejects
any message carrying a number that appears nowhere in the inputs.
"""
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from enrichers.angle_writer import recent_appointment
from enrichers.fact_extractor import APPOINTMENT_LABELS, VALID_SOURCES
from processors.icp_rules import load_rules
from enrichers.retry import (
    CREDIT_EXHAUSTED_MESSAGE,
    AuthError,
    CreditExhausted,
    retry_api_call,
)

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_LANGUAGE = "fr"

LANGUAGE_LABELS = {
    "fr": "français",
    "en": "anglais",
    "ar": "arabe",
    "pt": "portugais",
    "es": "espagnol",
    "nl": "néerlandais",
    "de": "allemand",
    "it": "italien",
}

# Language name used inside the prompt, written in that language's own
# English name so the instruction is unambiguous to the model.
_PROMPT_LANGUAGE_NAMES = {
    "fr": "French", "en": "English", "ar": "Arabic", "pt": "Portuguese",
    "es": "Spanish", "nl": "Dutch", "de": "German", "it": "Italian",
}

# Country -> language of business correspondence. Only countries with a single
# dominant working language are listed: a multilingual market (Belgium,
# Switzerland, Canada...) is a "no reliable hint" case and falls back to
# French rather than guessing. Names are accent-stripped and lower-cased
# (see _normalize); both French and English spellings appear because the
# fact extractor writes French country names while Apollo locations are
# usually English.
_COUNTRY_LANGUAGE: dict[str, str] = {}
for _lang, _names in {
    "fr": ["maroc", "morocco", "france", "algerie", "algeria", "tunisie", "tunisia",
           "senegal", "cote d'ivoire", "ivory coast", "cameroun", "cameroon", "mali",
           "burkina faso", "guinee", "gabon", "madagascar"],
    "en": ["etats-unis", "etats unis", "united states", "usa", "us", "royaume-uni",
           "royaume uni", "united kingdom", "uk", "great britain", "irlande", "ireland",
           "australie", "australia", "nouvelle-zelande", "new zealand",
           "emirats arabes unis", "united arab emirates", "uae", "arabie saoudite",
           "saudi arabia", "inde", "india", "nigeria", "kenya", "ghana",
           "afrique du sud", "south africa", "singapour", "singapore",
           # Anglophone countries of the ICP's "rest of Africa" zone
           # (config/icp_rules.json). Bilingual or ambiguous ones (Rwanda,
           # Mauritius, Seychelles, Ethiopia...) are left out on purpose.
           "tanzanie", "tanzania", "ouganda", "uganda", "zambie", "zambia",
           "zimbabwe", "namibie", "namibia", "botswana", "malawi", "lesotho",
           "eswatini", "sierra leone", "liberia", "gambie", "gambia",
           "soudan du sud", "south sudan"],
    "es": ["espagne", "spain", "mexique", "mexico", "argentine", "argentina",
           "colombie", "colombia", "chili", "chile", "perou", "peru"],
    "pt": ["portugal", "bresil", "brazil", "brasil",
           # Lusophone countries of the ICP's "rest of Africa" zone
           "angola", "mozambique", "cap-vert", "cap vert", "cabo verde",
           "cape verde", "guinee-bissau", "guinee bissau", "guinea-bissau",
           "sao tome-et-principe", "sao tome et principe", "sao tome"],
    "de": ["allemagne", "germany", "deutschland", "autriche", "austria"],
    "it": ["italie", "italy", "italia"],
    "nl": ["pays-bas", "netherlands", "the netherlands"],
}.items():
    for _name in _names:
        _COUNTRY_LANGUAGE[_name] = _lang

# Facts the message may draw on. Everything else the extractor produces
# (competitor flag, digital-maturity grade, identity check) is an internal
# judgement, not something to say to a prospect.
_MESSAGE_FACT_KEYS = ("pays", "secteur", "effectif")


class LinkedinMessageRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    conversion_angle: Optional[str] = None
    # The lead's facts, as stored on the lead (JSON string) or already parsed.
    facts_json: Optional[str] = None
    facts: Optional[dict] = None
    # Operator's explicit choice ("fr", "en", "ar"...). When given it is
    # authoritative and the country/location deduction is skipped.
    langue: Optional[str] = None


def _normalize(text: str) -> str:
    """Lower-case and strip accents so "Sénégal" and "senegal" compare equal."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def _load_facts(req: LinkedinMessageRequest) -> dict:
    if isinstance(req.facts, dict):
        return req.facts
    if req.facts_json:
        try:
            parsed = json.loads(req.facts_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _sourced_value(fact) -> Optional[object]:
    """The value of a fact, only if it carries a recognised source."""
    if not isinstance(fact, dict):
        return None
    value = fact.get("value")
    if value in (None, "", 0):
        return None
    if fact.get("source") not in VALID_SOURCES:
        return None
    return value


def _recent_appointment(facts: dict, today: date) -> Optional[dict]:
    """The contact's move into the post, when it is sourced and still recent.

    Recency is decided by the same window as the angle
    (enrichers/angle_writer.recent_appointment, itself reading
    icp_rules.signal_recency_months): the operator tunes one number, and the
    message cannot congratulate someone on an arrival the angle already
    considers old. An older appointment is not denied — it stays a true fact
    in the lead's facts — it simply stops being something to open on.

    The source check is this route's own: it receives facts over HTTP, so it
    re-applies "no source, no fact" instead of trusting the caller.
    """
    appointment = recent_appointment({"facts": facts}, load_rules(), today)
    if not appointment or appointment.get("source") not in VALID_SOURCES:
        return None
    return {
        "date": appointment.get("value"),
        # The wording the angle uses for the same move, so the two texts
        # cannot describe it differently.
        "mouvement": APPOINTMENT_LABELS[appointment["type"]],
    }


def sourced_facts(facts: dict, today: Optional[date] = None) -> dict:
    """Keep only the facts the message is allowed to rest on.

    A fact without a recognised source is dropped here, in Python: the same
    "no source, no fact" rule the extractor enforces before scoring.
    """
    kept: dict = {}
    for key in _MESSAGE_FACT_KEYS:
        value = _sourced_value(facts.get(key))
        if value is not None:
            kept[key] = value
    appointment = _recent_appointment(facts, today or date.today())
    if appointment:
        kept["prise_de_poste"] = appointment
    signals = []
    for signal in facts.get("signaux") or []:
        if (isinstance(signal, dict) and signal.get("source") in VALID_SOURCES
                and signal.get("citation")):
            signals.append({
                "type": signal.get("type"),
                "date": signal.get("date"),
                "citation": signal.get("citation"),
            })
    if signals:
        kept["signaux"] = signals
    return kept


def _language_of_country(text: Optional[str]) -> Optional[str]:
    """Language for a country or a "City, Region, Country" string, or None.

    Whole comma-separated segments are compared, never substrings, so that
    "Indiana" is not read as "India". The last segment is tried first: in a
    location string it is the country.
    """
    if not text:
        return None
    segments = [s for s in (_normalize(p) for p in text.split(",")) if s]
    for segment in reversed(segments):
        if segment in _COUNTRY_LANGUAGE:
            return _COUNTRY_LANGUAGE[segment]
    return None


def detect_language(facts: dict, location: Optional[str]) -> tuple[str, str]:
    """Deduce the message language from the lead's data, never from a name.

    Returns (language code, basis) where basis is "pays" (country fact),
    "localisation" (declared location) or "defaut" (no reliable hint).
    """
    country = _sourced_value(facts.get("pays"))
    lang = _language_of_country(str(country)) if country else None
    if lang:
        return lang, "pays"
    lang = _language_of_country(location)
    if lang:
        return lang, "localisation"
    return DEFAULT_LANGUAGE, "defaut"


SYSTEM_PROMPT = """You write the first LinkedIn message of a cold outreach for \
BoxCom, a digital communication agency based in Morocco (services: digital \
marketing, creative content, web development, lead generation).

You are given a prospect, verified FACTS with their source, and a recommended \
ANGLE.

Rules:
1. Write only what the facts and the angle contain. No number, no date, no \
client name, no technology, no news item that is not in the data provided. \
No source, no fact.
2. No superlatives or filler ("leader", "reference", "since X years", \
"team of X people") unless they appear in the data.
3. Short: 3 to 4 sentences, 80 words maximum. Greet the prospect by first \
name, connect one precise fact to one BoxCom service, end with one simple \
open question.
4. Do not sign: the sender adds their own name. No placeholders such as \
[Name].
5. Never mention scores, "angle", "facts", or any automated analysis.
6. Write the whole message in {language}, whatever the language of the data \
below. Write any number with Western digits (0-9).
7. If the facts carry a "prise_de_poste", open on that move, described exactly \
as the fact words it and dated as the fact dates it: someone who has just \
taken a post is at the one moment they reconsider their providers. If there is \
no "prise_de_poste" in the facts, do not mention one, not even obliquely — \
"congratulations on your new role" is an invention like any other.

Reply with the message text only, no quotes, no preamble."""

USER_PROMPT_TEMPLATE = """Prospect: {profile}

Verified facts (each one is sourced):
{facts}

Recommended angle:
{angle}

Write the message."""


def _numbers_in(text: str) -> set[str]:
    """Digit runs in the text, with every script mapped to 0-9.

    The regex digit class matches Arabic-Indic digits too; without the mapping a
    message that renders the source's "45" as "٤٥" would be rejected as
    inventing a number.
    """
    return {
        "".join(str(unicodedata.decimal(c)) for c in run)
        for run in re.findall(r"\d+", text)
    }


def invented_numbers(message: str, source_text: str) -> set[str]:
    """Numbers present in the message but nowhere in the inputs."""
    return _numbers_in(message) - _numbers_in(source_text)


def _call_model(system: str, user: str) -> str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _do_request() -> str:
        response = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=400,
            temperature=0.4,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text.strip()

    return retry_api_call(_do_request, max_retries=2, operation_name="LinkedIn message")


def _resolve_language(req: LinkedinMessageRequest, raw_facts: dict) -> tuple[str, str]:
    """The operator's explicit choice wins; otherwise the deduction.

    Returns (language code, basis); basis is "choix" for an explicit choice.
    """
    if req.langue is not None and req.langue.strip():
        code = req.langue.strip().lower()
        if code not in LANGUAGE_LABELS:
            raise HTTPException(
                status_code=422,
                detail=f"Langue non prise en charge : « {req.langue.strip()} ».",
            )
        return code, "choix"
    # Raw facts, not the filtered ones: detect_language does its own source check.
    return detect_language(raw_facts, req.location)


@router.post("/leads/linkedin-message/language")
def suggest_linkedin_message_language(req: LinkedinMessageRequest):
    """The language the deduction would pick, so the UI can pre-select it.

    No model call and no API key needed: the operator sees what was deduced,
    and why, before choosing.
    """
    code, basis = detect_language(_load_facts(req), req.location)
    return {"language": code, "language_label": LANGUAGE_LABELS[code], "language_basis": basis}


@router.post("/leads/linkedin-message")
def generate_linkedin_message(req: LinkedinMessageRequest):
    angle = (req.conversion_angle or "").strip()
    if not angle:
        # Without an angle there is nothing sourced to say. The UI disables
        # the button in that case; this guards direct callers.
        raise HTTPException(
            status_code=422,
            detail="Aucun angle de conversion pour ce lead : le message ne "
                   "pourrait s'appuyer sur aucun fait.",
        )
    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        raise HTTPException(
            status_code=503,
            detail="Clé Anthropic absente : renseignez-la dans les paramètres.",
        )

    raw_facts = _load_facts(req)
    facts = sourced_facts(raw_facts)
    language, basis = _resolve_language(req, raw_facts)

    system = SYSTEM_PROMPT.format(language=_PROMPT_LANGUAGE_NAMES[language])
    full_name = " ".join(p for p in (req.first_name, req.last_name) if p)
    profile = ", ".join(p for p in (
        full_name,
        req.job_title,
        f"at {req.company}" if req.company else None,
    ) if p) or "(no details)"
    user = USER_PROMPT_TEMPLATE.format(
        profile=profile,
        facts=json.dumps(facts, ensure_ascii=False) if facts else "(none)",
        angle=angle,
    )
    # Everything the model was shown: a number outside this text is invented.
    source_text = " ".join([
        req.first_name or "", req.last_name or "", req.job_title or "",
        req.company or "", angle, json.dumps(facts, ensure_ascii=False),
    ])

    message = ""
    for attempt in range(2):
        try:
            message = _call_model(system, user)
        except CreditExhausted:
            raise HTTPException(status_code=502, detail=CREDIT_EXHAUSTED_MESSAGE)
        except AuthError:
            raise HTTPException(status_code=502, detail="Clé Anthropic refusée.")
        except Exception as exc:
            logger.error(f"LinkedIn message generation failed: {exc}")
            raise HTTPException(
                status_code=502,
                detail="La génération du message a échoué. Réessayez dans un instant.",
            )
        invented = invented_numbers(message, source_text)
        if message and not invented:
            return {
                "message": message,
                "language": language,
                "language_label": LANGUAGE_LABELS[language],
                "language_basis": basis,
            }
        logger.warning(
            f"LinkedIn message attempt {attempt + 1} rejected "
            f"(empty={not message}, invented numbers={sorted(invented)})"
        )

    raise HTTPException(
        status_code=502,
        detail="Le message généré contenait une information absente des faits "
               "et a été écarté. Réessayez.",
    )
