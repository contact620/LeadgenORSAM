"""
Step 8 — Commercial angle writing.

Runs last, on validated facts only, and only for leads worth contacting.
Separating this from evaluation is deliberate: a model asked to judge and to
sell in the same breath will justify the sale it just wrote. The same
separation is why this step receives facts and never the raw sources — it
cannot verify anything, so it is given nothing to verify.

The angle consolidates the two halves of the research in one text: what the
company does, and who the contact is. When the facts carry a recent
appointment, that is where the angle starts — see recent_appointment.
"""
import json
import logging
import time
from datetime import date
from typing import Optional

import anthropic

import config
from api.provider_status import StepOutcome
from enrichers.fact_extractor import APPOINTMENT_LABELS
from enrichers.retry import (
    CREDIT_EXHAUSTED_MESSAGE,
    AuthError,
    CreditExhausted,
    retry_api_call,
)
from processors.icp_rules import IcpRules, load_rules
from processors.icp_scorer import months_between

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu rédiges des accroches de prospection pour BoxCom, agence de \
communication digitale basée au Maroc (+10 ans d'expertise).

Services : Marketing Digital, Contenu Créatif, Développement Web, Lead Generation.

On te transmet des FAITS déjà vérifiés et sourcés, sur l'ENTREPRISE et sur la
PERSONNE. Tu n'as pas accès aux sources brutes : tu ne peux donc rien vérifier,
et tu n'ajoutes rien.

Règles :
1. Tu n'écris que ce que les faits contiennent. Aucun chiffre, aucune date, aucune
   technologie, aucun poste qui ne figure pas dans les faits fournis.
2. Interdits : "leader du marché", "acteur de référence", "depuis X années",
   "équipe de X personnes" — sauf si présents dans les faits.
3. Si les faits sont pauvres, écris un résumé court plutôt qu'un texte étoffé.
4. Une seule accroche, qui tient la personne ET son entreprise : à qui tu
   écris, ce que son entreprise fait, et le service BoxCom que ce rapprochement
   appelle. Une accroche qui ne parle que de l'entreprise rate la moitié du
   travail.
5. PRIORITÉ ABSOLUE : si une prise de poste récente figure dans les faits,
   l'accroche part de là. Quelqu'un qui vient d'arriver à son poste est au seul
   moment où il remet en question les prestataires en place. Nomme le mouvement
   tel que les faits le décrivent — nouveau poste dans la même entreprise, ou
   arrivée dans l'entreprise — et sa date, puis enchaîne sur l'entreprise.
6. Aucune prise de poste dans les faits ? N'en évoque aucune, même à mots
   couverts : "félicitations pour votre nouveau rôle" est une invention comme
   une autre.

Produis :
- "activity_summary" : 2-3 phrases décrivant l'activité de l'entreprise.
- "conversion_angle" : une accroche personnalisée reliant un fait précis à un
  service BoxCom nommé, adressée à cette personne à son poste.

Réponds UNIQUEMENT par ce JSON, sans markdown :
{"activity_summary": "...", "conversion_angle": "..."}"""

USER_PROMPT_TEMPLATE = """Prospect : {first_name} {last_name}, {job_title} chez {company}

Faits vérifiés :
{facts_json}
{appointment_note}
Rédige le JSON demandé."""

# What the priority instruction says when the facts carry a recent appointment.
# The model is told the move and its date, never the source: the writer judges
# nothing and verifies nothing, which is why it is kept away from the sources.
APPOINTMENT_NOTICE = (
    "\nSIGNAL PRIORITAIRE — prise de poste récente : {month}, {wording}.\n"
    "L'accroche part de ce mouvement, sans rien y ajouter.\n"
)

_writer_disabled = False
# Why the step gave up, in words the operator can act on (reaches the run's
# provider panel). None while the step is healthy.
_disabled_reason: Optional[str] = None
# Calls actually sent and calls that came back with text.
_calls_attempted = 0
_calls_succeeded = 0


def _reset_state():
    global _writer_disabled, _disabled_reason
    global _calls_attempted, _calls_succeeded
    _writer_disabled = False
    _disabled_reason = None
    _calls_attempted = 0
    _calls_succeeded = 0


def should_write(lead: dict) -> bool:
    """Write for every lead that is not refused and has something to say.

    The ICP score no longer reaches the operator — a written angle replaces it
    — so it must not gate the writing either. Neither of the two surviving
    conditions is a grade:

    - ``disqualification_reason`` is a factual refusal ("grand groupe",
      "secteur exclu", "hors zone géographique", "concurrent direct"), already
      carried by every branch of processors/icp_scorer.py that refuses a
      prospect. Nothing to sell to someone we cannot sell to.
    - ``evidence_level != "none"`` is a floor, not a quality bar. "none" is the
      state of EVERY lead when extraction fails: fact_extractor returns
      _EMPTY_FACTS, identite_confirmee is False and compute_evidence_level
      answers "none". Without this floor an Anthropic outage would produce
      twenty invented angles instead of twenty empty cells — a silent failure
      replacing a visible one. "weak" is deliberately allowed through: thin
      sourced facts make a thin angle, which is a correct outcome.
    """
    if lead.get("disqualification_reason"):
        return False
    return (lead.get("evidence_level") or "none") != "none"


def _facts_of(lead: dict) -> dict:
    """The lead's validated facts, from the dict or from the stored JSON."""
    facts = lead.get("facts")
    if isinstance(facts, dict):
        return facts
    try:
        parsed = json.loads(lead.get("facts_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def recent_appointment(lead: dict, rules: IcpRules, today: date) -> Optional[dict]:
    """The contact's appointment, when it is recent enough to lead the angle.

    "Recent" is icp_rules.signal_recency_months, the same window the scorer
    applies to a company signal: the operator tunes one number, not two. An
    older appointment is not discarded — it stays a true fact in facts_json —
    it simply stops being the hook, because "vous venez de prendre vos
    fonctions" addressed to someone in post for three years reads as a form
    letter.
    """
    appointment = _facts_of(lead).get("prise_de_poste")
    if not isinstance(appointment, dict):
        return None
    if appointment.get("type") not in APPOINTMENT_LABELS:
        return None
    age = months_between(appointment.get("value"), today)
    if age is None or not 0 <= age <= rules.signal_recency_months:
        return None
    return appointment


def _appointment_note(appointment: Optional[dict]) -> str:
    """The priority instruction for a recent appointment, or nothing."""
    if not appointment:
        return ""
    return APPOINTMENT_NOTICE.format(
        month=appointment.get("value"),
        wording=APPOINTMENT_LABELS[appointment["type"]],
    )


def _write_one(lead: dict, enrich_instructions: str = "",
               appointment: Optional[dict] = None) -> dict:
    global _writer_disabled, _disabled_reason
    global _calls_attempted, _calls_succeeded
    empty = {"activity_summary": None, "conversion_angle": None}
    if _writer_disabled:
        return empty

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system = SYSTEM_PROMPT
    if enrich_instructions:
        system += (
            "\n\nINSTRUCTIONS SPÉCIFIQUES DE L'UTILISATEUR :\n"
            f"{enrich_instructions}\n"
            "Oriente l'accroche selon ces instructions, sans inventer de fait."
        )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        job_title=lead.get("job_title", ""),
        company=lead.get("company", ""),
        facts_json=lead.get("facts_json") or json.dumps(lead.get("facts") or {}, ensure_ascii=False),
        appointment_note=_appointment_note(appointment),
    )
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=600,
            # temperature is not a parameter of messages.create in the 1.x SDK.
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = message.content[0].text.strip()
        if content.startswith("```"):
            import re
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()
        data = json.loads(content)
        return {
            "activity_summary": (data.get("activity_summary") or "").strip() or None,
            "conversion_angle": (data.get("conversion_angle") or "").strip() or None,
        }

    _calls_attempted += 1
    try:
        written = retry_api_call(
            _do_request, max_retries=3, operation_name=f"Angle writing ({name})"
        )
    except CreditExhausted as e:
        # Caught before AuthError, which it subclasses: the operator has to
        # top up a balance here, not fix a key.
        _writer_disabled = True
        _disabled_reason = CREDIT_EXHAUSTED_MESSAGE
        logger.error(f"Angle writing stopped — disabled for this run: {e}")
        return empty
    except AuthError as e:
        _writer_disabled = True
        _disabled_reason = "clé Anthropic refusée"
        logger.error(f"Angle writing auth failed — disabled for this run: {e}")
        return empty
    except Exception as e:
        logger.error(f"Angle writing failed for {name}: {e}")
        return empty
    _calls_succeeded += 1
    return written


def write_leads_angles(
    leads: list[dict],
    enrich_instructions: str = "",
    registry=None,
    rules: Optional[IcpRules] = None,
    run_date: Optional[date] = None,
) -> list[dict]:
    """Write summary and angle for every lead that qualifies.

    ``rules`` and ``run_date`` only arbitrate how recent an appointment has to
    be to lead the angle; they are loaded once per run, not once per lead.
    """
    _reset_state()
    active_rules = rules or load_rules()
    today = run_date or date.today()

    eligible = [l for l in leads if should_write(l)]
    skipped = len(leads) - len(eligible)
    logger.info(f"Angle writing: {len(eligible)} eligible leads, {skipped} skipped")

    for lead in leads:
        lead.setdefault("activity_summary", None)
        lead.setdefault("conversion_angle", None)

    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping angle writing.")
        if registry:
            registry.record(StepOutcome("anthropic_angles", "skipped", "clé API absente", 0))
        return leads

    written = 0
    total = len(eligible)
    for i, lead in enumerate(eligible, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Angle writing [{i}/{total}]: {name}")
        result = _write_one(
            lead, enrich_instructions,
            recent_appointment(lead, active_rules, today),
        )
        lead["activity_summary"] = result["activity_summary"]
        lead["conversion_angle"] = result["conversion_angle"]
        if result["activity_summary"]:
            written += 1
        if _writer_disabled:
            logger.warning(f"Angle writing disabled — skipping remaining {total - i} leads")
            break
        if i < total:
            time.sleep(0.3)

    logger.info(f"Angle writing complete. {written}/{total} written.")
    if registry:
        registry.record(StepOutcome("anthropic_angles", *_health(), written))
    return leads


def _health() -> tuple[str, Optional[str]]:
    """Status and reason for this run's angle writing.

    A run where every call failed used to report "ok": each lead got a pair
    of empty fields, which is also what an unevidenced lead gets, so total
    failure and nothing-to-say were indistinguishable.
    """
    if _writer_disabled:
        return "degraded", _disabled_reason
    if _calls_attempted and not _calls_succeeded:
        return "degraded", f"aucun appel abouti sur {_calls_attempted}"
    return "ok", None
