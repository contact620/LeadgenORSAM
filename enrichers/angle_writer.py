"""
Step 8 — Commercial angle writing.

Runs last, on validated facts only, and only for leads worth contacting.
Separating this from evaluation is deliberate: a model asked to judge and to
sell in the same breath will justify the sale it just wrote.
"""
import json
import logging
import time

import anthropic

import config
from api.provider_status import StepOutcome
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu rédiges des accroches de prospection pour BoxCom, agence de \
communication digitale basée au Maroc (+10 ans d'expertise).

Services : Marketing Digital, Contenu Créatif, Développement Web, Lead Generation.

On te transmet des FAITS déjà vérifiés et sourcés. Tu n'as pas accès aux sources brutes.

Règles :
1. Tu n'écris que ce que les faits contiennent. Aucun chiffre, aucune date, aucune
   technologie qui ne figure pas dans les faits fournis.
2. Interdits : "leader du marché", "acteur de référence", "depuis X années",
   "équipe de X personnes" — sauf si présents dans les faits.
3. Si les faits sont pauvres, écris un résumé court plutôt qu'un texte étoffé.

Produis :
- "activity_summary" : 2-3 phrases décrivant l'activité de l'entreprise.
- "conversion_angle" : une accroche personnalisée reliant un fait précis à un
  service BoxCom nommé.

Réponds UNIQUEMENT par ce JSON, sans markdown :
{"activity_summary": "...", "conversion_angle": "..."}"""

USER_PROMPT_TEMPLATE = """Prospect : {first_name} {last_name}, {job_title} chez {company}

Faits vérifiés :
{facts_json}

Évaluation ICP : {icp_tier} ({icp_score}/100)
{icp_rationale}

Rédige le JSON demandé."""

_writer_disabled = False


def _reset_state():
    global _writer_disabled
    _writer_disabled = False


def should_write(lead: dict) -> bool:
    """Only evidenced, non-disqualified leads deserve the token spend."""
    if lead.get("icp_tier") == "disqualified":
        return False
    return bool(lead.get("evidence_verified"))


def _write_one(lead: dict, enrich_instructions: str = "") -> dict:
    global _writer_disabled
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
        icp_tier=lead.get("icp_tier", "?"),
        icp_score=lead.get("icp_score", "?"),
        icp_rationale=lead.get("icp_rationale", ""),
    )
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=600,
            temperature=0.3,
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

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Angle writing ({name})")
    except AuthError as e:
        _writer_disabled = True
        logger.error(f"Angle writing auth failed — disabled for this run: {e}")
        return empty
    except Exception as e:
        logger.error(f"Angle writing failed for {name}: {e}")
        return empty


def write_leads_angles(leads: list[dict], enrich_instructions: str = "", registry=None) -> list[dict]:
    """Write summary and angle for every lead that qualifies."""
    _reset_state()

    eligible = [l for l in leads if should_write(l)]
    skipped = len(leads) - len(eligible)
    logger.info(f"Angle writing: {len(eligible)} eligible leads, {skipped} skipped")

    for lead in leads:
        lead.setdefault("activity_summary", None)
        lead.setdefault("conversion_angle", None)

    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping angle writing.")
        if registry:
            registry.record(StepOutcome("anthropic", "skipped", "clé API absente", 0))
        return leads

    written = 0
    total = len(eligible)
    for i, lead in enumerate(eligible, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Angle writing [{i}/{total}]: {name}")
        result = _write_one(lead, enrich_instructions)
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
        registry.record(StepOutcome("anthropic", "degraded" if _writer_disabled else "ok", None, written))
    return leads
