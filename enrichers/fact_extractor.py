"""
Step 6 — Sourced fact extraction.

The model's only job here is to read the collected sources and report what
they say, with a source label on every claim. It does not grade, rank or sell.
Anything it reports without a usable source is discarded in Python before
scoring: a rule enforced in code cannot be talked around by a confident model.
"""
import json
import logging
import re
import time
from typing import Optional

import anthropic

import config
from api.provider_status import StepOutcome
from enrichers.retry import retry_api_call, AuthError
from processors.evidence import Evidence, compute_evidence_level

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
VALID_SOURCES = frozenset({"website", "linkedin", "perplexity"})

SYSTEM_PROMPT = """Tu es un analyste qui extrait des faits vérifiables sur une entreprise.

Tu ne notes pas. Tu ne vends pas. Tu ne rédiges pas d'argumentaire.
Tu lis les sources fournies et tu rapportes ce qu'elles disent.

═══ RÈGLE ABSOLUE : PAS DE SOURCE, PAS DE FAIT ═══

Chaque fait que tu rapportes doit porter une clé "source" valant exactement
"website", "linkedin" ou "perplexity", désignant la source où tu l'as lu.

Si une information n'apparaît dans AUCUNE source fournie, tu mets le champ à null.
Tu n'as pas le droit de la déduire, de l'estimer ou de la compléter par ta
connaissance générale de l'entreprise. Un champ null est un résultat correct
et attendu. Une invention est une faute.

═══ CONFIRMATION D'IDENTITÉ ═══

"identite_confirmee" vaut true si les sources décrivent bien l'entreprise du
prospect. Il vaut false uniquement si les sources décrivent manifestement une
AUTRE entité (homonymie : même nom, pays ou métier sans rapport).

Ne mets PAS false dans ces cas :
- le champ localisation du prospect est vide, tronqué ou incohérent (artefact
  de saisie) — ignore-le et juge sur les sources ;
- la localisation est une ville et la source mentionne le pays correspondant ;
- le poste du contact ne colle pas parfaitement au secteur.

En cas de doute : true.

═══ CHAMPS ═══

- "pays" : pays d'opération principal, en français ("Maroc", "France", "Sénégal"...)
- "secteur" : secteur d'activité en français, en deux mots maximum
- "effectif" : nombre d'employés, entier. null si aucune source ne le donne.
- "est_concurrent" : true si l'entreprise est une agence de communication,
  de marketing digital, de création ou de développement web.
- "maturite_digitale" : entier de 1 à 10 si une source l'évalue, sinon null
- "signaux" : événements datés des 12 derniers mois (recrutement, levée de fonds,
  lancement, expansion, refonte). Liste vide si aucune source n'en mentionne.

═══ FORMAT ═══

Réponds UNIQUEMENT par ce JSON, sans markdown ni commentaire :
{
  "identite_confirmee": true,
  "pays": {"value": "Maroc", "source": "website"},
  "secteur": {"value": "immobilier", "source": "website"},
  "effectif": {"value": 45, "source": "perplexity"},
  "est_concurrent": false,
  "maturite_digitale": {"value": 4, "source": "perplexity"},
  "signaux": [
    {"type": "recrutement_marketing", "date": "2026-04",
     "source": "perplexity", "citation": "extrait littéral de la source"}
  ]
}"""

USER_PROMPT_TEMPLATE = """Prospect (données Apollo, non vérifiées) :
Nom : {first_name} {last_name}
Poste : {job_title}
Entreprise : {company}
Localisation déclarée : {location}

═══ SOURCE "website" ═══
{website_text}

═══ SOURCE "perplexity" ═══
Maturité digitale : {digital_maturity}
Taille / budget : {estimated_budget}
Signaux business : {business_signals}

Extrais les faits au format JSON demandé."""

_EMPTY_FACTS = {
    "identite_confirmee": False,
    "pays": None,
    "secteur": None,
    "effectif": None,
    "est_concurrent": False,
    "maturite_digitale": None,
    "signaux": [],
}

_extractor_disabled = False


def _reset_state():
    global _extractor_disabled
    _extractor_disabled = False


def _sourced(fact) -> Optional[dict]:
    """Keep a fact only when it carries a recognised source and a value."""
    if not isinstance(fact, dict):
        return None
    if fact.get("source") not in VALID_SOURCES:
        return None
    if fact.get("value") in (None, "", []):
        return None
    return {"value": fact["value"], "source": fact["source"]}


def _as_int(fact: Optional[dict]) -> Optional[dict]:
    if fact is None:
        return None
    try:
        value = int(str(fact["value"]).strip())
    except (ValueError, TypeError):
        return None
    if value < 0:
        return None
    return {"value": value, "source": fact["source"]}


def sanitize_facts(raw: dict) -> dict:
    """Drop every unsourced or malformed fact. Always returns a complete shape.

    Guarantee: never raises and always returns the full 7-key shape, whatever
    the input — including a non-dict `raw` (list, string, int, bool, None) or
    a non-list `signaux`. This is the enforcement point for "no source, no
    fact"; callers (present and future, see task 12) must be able to rely on
    it without wrapping it in their own try/except.
    """
    if not isinstance(raw, dict):
        raw = {}
    raw_signals = raw.get("signaux")
    if not isinstance(raw_signals, list):
        raw_signals = []
    signals = []
    for signal in raw_signals:
        if not isinstance(signal, dict):
            continue
        if signal.get("source") not in VALID_SOURCES:
            continue
        signals.append({
            "type": signal.get("type") or "signal",
            "date": signal.get("date") or None,
            "source": signal["source"],
            "citation": signal.get("citation") or "",
        })

    return {
        "identite_confirmee": bool(raw.get("identite_confirmee", False)),
        "pays": _sourced(raw.get("pays")),
        "secteur": _sourced(raw.get("secteur")),
        "effectif": _as_int(_sourced(raw.get("effectif"))),
        "est_concurrent": str(raw.get("est_concurrent", "")).strip().lower() in ("true", "1", "yes")
                          or raw.get("est_concurrent") is True,
        "maturite_digitale": _as_int(_sourced(raw.get("maturite_digitale"))),
        "signaux": signals,
    }


def _parse_json(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    return json.loads(cleaned)


def extract_facts(lead: dict, ev: Evidence) -> dict:
    """Call the model for one lead and return sanitized facts."""
    global _extractor_disabled
    if _extractor_disabled:
        return dict(_EMPTY_FACTS)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    perplexity = ev.perplexity_fields or {}
    user_prompt = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        job_title=lead.get("job_title", ""),
        company=lead.get("company", ""),
        location=lead.get("location", ""),
        website_text=(ev.website_text or "Non disponible")[:4000],
        digital_maturity=perplexity.get("digital_maturity") or "Non disponible",
        estimated_budget=perplexity.get("estimated_budget") or "Non disponible",
        business_signals=perplexity.get("business_signals") or "Non disponible",
    )
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return sanitize_facts(_parse_json(message.content[0].text.strip()))

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Fact extraction ({name})")
    except AuthError as e:
        _extractor_disabled = True
        logger.error(f"Fact extraction auth failed — disabled for this run: {e}")
        return dict(_EMPTY_FACTS)
    except Exception as e:
        logger.error(f"Fact extraction failed for {name}: {e}")
        return dict(_EMPTY_FACTS)


def extract_leads_facts(
    leads: list[dict],
    enabled_providers: frozenset[str],
    registry=None,
) -> list[dict]:
    """
    Extract facts for every lead and compute its evidence level.

    Sets lead['facts'], lead['facts_json'] and lead['evidence_level'].
    """
    _reset_state()

    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping fact extraction.")
        for lead in leads:
            lead["facts"] = dict(_EMPTY_FACTS)
            lead["facts_json"] = json.dumps(_EMPTY_FACTS, ensure_ascii=False)
            lead["evidence_level"] = "none"
        if registry:
            registry.record(StepOutcome("anthropic", "skipped", "clé API absente", 0))
        return leads

    total = len(leads)
    extracted = 0
    for i, lead in enumerate(leads, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Fact extraction [{i}/{total}]: {name}")

        ev = Evidence(
            website_text=lead.get("website_text", "") or "",
            website_coherent=lead.get("website_coherent") is not False,
            perplexity_fields={
                "digital_maturity": lead.get("digital_maturity"),
                "estimated_budget": lead.get("estimated_budget"),
                "business_signals": lead.get("business_signals"),
            },
            enabled_providers=enabled_providers,
        )

        facts = extract_facts(lead, ev)
        lead["facts"] = facts
        lead["facts_json"] = json.dumps(facts, ensure_ascii=False)
        lead["evidence_level"] = compute_evidence_level(ev, facts["identite_confirmee"])

        if facts["identite_confirmee"]:
            extracted += 1
        if _extractor_disabled:
            logger.warning(f"Fact extraction disabled — skipping remaining {total - i} leads")
            for remaining in leads[i:]:
                remaining["facts"] = dict(_EMPTY_FACTS)
                remaining["facts_json"] = json.dumps(_EMPTY_FACTS, ensure_ascii=False)
                remaining["evidence_level"] = "none"
            break
        if i < total:
            time.sleep(0.3)

    logger.info(f"Fact extraction complete. {extracted}/{total} identities confirmed.")
    if registry:
        status = "degraded" if _extractor_disabled else "ok"
        registry.record(StepOutcome("anthropic", status, None, extracted))
    return leads
