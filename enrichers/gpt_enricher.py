"""
Step 5b — Claude enricher (hit leads only).

For each hit lead, calls claude-haiku-4-5 to generate:
  1. activity_summary: 2-3 sentences on the person's professional activity.
  2. conversion_angle: A personalized outreach hook tailored to their context.

Claude is only called for hit leads to keep costs low.
"""
import json
import logging
import re
import time
from typing import Optional

import anthropic

import config
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un expert en prospection B2B.
À partir des informations sur un prospect (profil LinkedIn, site web de l'entreprise),
tu génères deux éléments concis pour personnaliser une approche commerciale :

1. activity_summary: résumé de l'activité professionnelle de la personne en 2-3 phrases.
2. conversion_angle: un angle d'approche personnalisé et actionnable pour décrocher un rendez-vous
   (ex: "automatiser sa gestion de stock", "réduire ses coûts d'acquisition client", etc.).

Réponds UNIQUEMENT en JSON avec exactement deux clés : "activity_summary" et "conversion_angle".
Pas d'explication, pas de markdown, juste le JSON brut."""

USER_PROMPT_TEMPLATE = """Prospect :
Prénom : {first_name}
Nom : {last_name}
Poste : {job_title}
Entreprise : {company}
Localisation : {location}

Profil LinkedIn (extrait) :
{linkedin_text}

Site web de l'entreprise (extrait) :
{website_text}

Génère le JSON avec activity_summary et conversion_angle."""


_claude_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _claude_disabled
    _claude_disabled = False


def _call_claude(lead: dict) -> tuple[Optional[str], Optional[str]]:
    """Call claude-haiku-4-5 for a single lead with retry. Returns (activity_summary, conversion_angle)."""
    global _claude_disabled
    if _claude_disabled:
        return None, None

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    linkedin_text = lead.get("linkedin_text", "") or "Non disponible"
    website_text = lead.get("website_text", "") or "Non disponible"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        job_title=lead.get("job_title", ""),
        company=lead.get("company", ""),
        location=lead.get("location", ""),
        linkedin_text=linkedin_text[:2000],
        website_text=website_text[:1500],
    )

    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = message.content[0].text.strip()
        logger.debug(f"Raw Claude response: {content!r}")
        if content.startswith("```"):
            content_clean = re.sub(r"^```[a-z]*\n?", "", content)
            content_clean = re.sub(r"\n?```$", "", content_clean).strip()
        else:
            content_clean = content
        data = json.loads(content_clean)
        return data.get("activity_summary", "").strip(), data.get("conversion_angle", "").strip()

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Claude AI ({name})")
    except AuthError as e:
        _claude_disabled = True
        logger.error(f"Claude auth failed — disabled for this run: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Claude enrichment failed after retries for {name}: {e}")
        return None, None


def enrich_leads_gpt(hit_leads: list[dict]) -> list[dict]:
    """
    For each hit lead, call Claude and store:
      lead["activity_summary"]
      lead["conversion_angle"]
    """
    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping Claude enrichment.")
        for lead in hit_leads:
            lead["activity_summary"] = None
            lead["conversion_angle"] = None
        return hit_leads

    total = len(hit_leads)
    success = 0

    for i, lead in enumerate(hit_leads, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"GPT enrichment [{i}/{total}]: {name}")

        summary, angle = _call_claude(lead)
        lead["activity_summary"] = summary
        lead["conversion_angle"] = angle

        if summary:
            success += 1

        if _claude_disabled:
            logger.warning(f"Claude disabled — skipping remaining {total - i} leads")
            for remaining in hit_leads[i:]:
                remaining["activity_summary"] = None
                remaining["conversion_angle"] = None
            break

        if i < total:
            time.sleep(0.5)

    logger.info(f"GPT enrichment complete. {success}/{total} leads enriched.")
    return hit_leads


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {
            "first_name": "Jean",
            "last_name": "Dupont",
            "job_title": "CEO",
            "company": "Acme Corp",
            "location": "Paris",
            "linkedin_text": "Jean Dupont est entrepreneur depuis 10 ans, spécialisé dans le SaaS B2B.",
            "website_text": "Acme Corp développe des solutions de gestion pour les PME.",
        }
    ]

    result = enrich_leads_gpt(test_leads)
    for lead in result:
        print(f"\nActivity summary : {lead.get('activity_summary')}")
        print(f"Conversion angle : {lead.get('conversion_angle')}")
