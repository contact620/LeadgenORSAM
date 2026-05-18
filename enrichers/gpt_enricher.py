"""
Step 6b — Claude enricher (hit leads only).

For each hit lead, calls the configured Claude model (default Sonnet 4.6) to generate:
  1. activity_summary       : 2-3 sentences grounded in the sources (no invention).
  2. conversion_angle       : Personalized outreach hook tied to a BoxCom service.
  3. inconsistency_detected : True if Apollo data and scraped sources describe
                              two different entities (homonymous company case).
  4. inconsistency_reason   : Short explanation when inconsistency_detected is True.
  5. confidence             : "high" | "medium" | "low" — model's own confidence.

The model is run only on hit leads to keep costs under control.
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

SYSTEM_PROMPT = """Tu es un expert en prospection B2B pour BoxCom, une agence de communication digitale basée au Maroc avec +10 ans d'expertise.

BoxCom propose 4 services principaux :
- Marketing Digital (stratégie, ads, SEO, réseaux sociaux)
- Contenu Créatif (branding, vidéo, motion design, social media)
- Développement Web (sites vitrines, e-commerce, landing pages)
- Lead Generation (funnels, lead scoring, campagnes d'acquisition)

À partir des informations sur un prospect, tu génères une analyse JSON.

═══ RÈGLES ANTI-HALLUCINATION (NON NÉGOCIABLES) ═══

1. CHAQUE affirmation dans activity_summary DOIT s'appuyer sur le texte du site web
   ou du profil LinkedIn fourni. Si une info n'est pas dans les sources, tu N'AS PAS
   le droit de l'inventer. Pas de chiffres, dates, technologies, prix, taille d'équipe,
   chiffre d'affaires ou années d'existence inventés.

2. Si les sources sont vides ou trop pauvres, mets activity_summary à
   "Données insuffisantes pour résumer l'activité" et confidence à "low".

3. Interdit absolu : "leader mondial", "acteur de référence", "depuis X années",
   "équipe de X personnes", "CA de X" — sauf si EXPLICITEMENT écrit dans les sources.

═══ DÉTECTION D'INCOHÉRENCE — RÈGLES STRICTES ═══

Le but de ce flag est UNIQUEMENT de détecter les cas d'HOMONYMIE D'ENTREPRISE :
deux sociétés DIFFÉRENTES portant le même nom, où la source scrapée décrit
manifestement une AUTRE entité que celle du prospect Apollo.

Tu dois mettre inconsistency_detected = true UNIQUEMENT si TOUS ces critères
sont réunis :

1. Le site web ou le LinkedIn scrapé décrit une entreprise dont le pays
   d'opération, le secteur d'activité ou la nature fondamentale ne correspond
   PAS du tout à ce qui est attendu pour le prospect Apollo.
2. Cette divergence est suffisamment forte pour suggérer qu'il s'agit littéralement
   d'une autre société (ex: Apollo pointe sur "Atlas Technologies" cabinet de
   conseil parisien, mais le site décrit "Atlas Technologies" agroalimentaire au
   Sénégal — clairement deux entités distinctes).

NE PAS flagger dans ces cas (qui ne sont PAS des homonymies) :
- Le champ Apollo `location` contient une valeur bizarre, vide, tronquée, ou
  manifestement corrompue (ex: "Access Mobile", "N/A", une simple chaîne de
  chiffres, un mot anglais sans sens géographique). Ce sont des artefacts de
  saisie Apollo — ignore-les complètement et fais ton analyse uniquement sur
  les sources scrapées.
- La localisation Apollo est une ville/région et le site mentionne un pays plus
  large compatible (ex: Apollo "Paris" et site qui parle de "France" ou "Europe").
- Le job_title Apollo ne semble pas matcher parfaitement le secteur — c'est
  normal, beaucoup de profils n'explicitent pas leur rôle.
- Les sources scrapées sont vides ou trop pauvres pour conclure. Dans ce cas,
  inconsistency_detected = false et confidence = "low".

En cas de doute : inconsistency_detected = false. Le faux positif (flagger à tort)
est plus coûteux pour l'utilisateur que le faux négatif.

Quand inconsistency_detected = true :
  - inconsistency_reason : 1 phrase courte en français expliquant l'homonymie
  - activity_summary et conversion_angle restent remplis, préfixés de
    "[INCOHÉRENCE DÉTECTÉE] " pour alerter l'utilisateur.

Sinon : inconsistency_detected = false, inconsistency_reason = null.

═══ FORMAT DE SORTIE ═══

Réponds UNIQUEMENT avec un objet JSON valide contenant EXACTEMENT ces clés :
{
  "activity_summary": "...",
  "conversion_angle": "...",
  "inconsistency_detected": false,
  "inconsistency_reason": null,
  "confidence": "high" | "medium" | "low"
}

Pas de markdown, pas de commentaire, juste le JSON brut."""

USER_PROMPT_TEMPLATE = """Prospect (données Apollo) :
Prénom : {first_name}
Nom : {last_name}
Poste : {job_title}
Entreprise : {company}
Localisation : {location}

Profil LinkedIn (extrait) :
{linkedin_text}

Site web de l'entreprise (extrait) :
{website_text}

Génère le JSON avec activity_summary, conversion_angle, inconsistency_detected, inconsistency_reason, confidence."""


_claude_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _claude_disabled
    _claude_disabled = False


def _parse_response(content: str) -> dict:
    """Strip optional markdown fences and parse the JSON body."""
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content).strip()
    return json.loads(content)


def _call_claude(lead: dict, enrich_instructions: str = "") -> dict:
    """
    Call the configured Claude model for a single lead with retry.

    Returns a dict with keys: activity_summary, conversion_angle,
    inconsistency_detected, inconsistency_reason, confidence.
    All values default to None / False on failure.
    """
    global _claude_disabled
    empty = {
        "activity_summary": None,
        "conversion_angle": None,
        "inconsistency_detected": False,
        "inconsistency_reason": None,
        "confidence": None,
    }
    if _claude_disabled:
        return empty

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    linkedin_text = lead.get("linkedin_text", "") or "Non disponible"
    website_text = lead.get("website_text", "") or "Non disponible"

    system = SYSTEM_PROMPT
    if enrich_instructions:
        system += (
            "\n\nINSTRUCTIONS SPÉCIFIQUES DE L'UTILISATEUR :\n"
            f"{enrich_instructions}\n\n"
            "Utilise ces instructions pour orienter le conversion_angle. "
            "Cherche les signaux et déclencheurs mentionnés par l'utilisateur."
        )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        job_title=lead.get("job_title", ""),
        company=lead.get("company", ""),
        location=lead.get("location", ""),
        linkedin_text=linkedin_text[:2000],
        website_text=website_text[:4000],
    )

    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=800,
            temperature=0.3,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = message.content[0].text.strip()
        logger.debug(f"Raw Claude response: {content!r}")
        data = _parse_response(content)
        return {
            "activity_summary": (data.get("activity_summary") or "").strip() or None,
            "conversion_angle": (data.get("conversion_angle") or "").strip() or None,
            "inconsistency_detected": bool(data.get("inconsistency_detected", False)),
            "inconsistency_reason": (data.get("inconsistency_reason") or None),
            "confidence": data.get("confidence") or None,
        }

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Claude AI ({name})")
    except AuthError as e:
        _claude_disabled = True
        logger.error(f"Claude auth failed — disabled for this run: {e}")
        return empty
    except Exception as e:
        logger.error(f"Claude enrichment failed after retries for {name}: {e}")
        return empty


def enrich_leads_gpt(hit_leads: list[dict], enrich_instructions: str = "") -> list[dict]:
    """
    For each hit lead, call Claude and store the enrichment fields.
    Sets all fields to None when the API key is missing.
    """
    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping Claude enrichment.")
        for lead in hit_leads:
            lead["activity_summary"] = None
            lead["conversion_angle"] = None
            lead["inconsistency_detected"] = False
            lead["inconsistency_reason"] = None
            lead["llm_confidence"] = None
        return hit_leads

    logger.info(f"Claude AI: enriching {len(hit_leads)} hit leads with model {config.LLM_MODEL}")
    total = len(hit_leads)
    success = 0
    inconsistencies = 0

    for i, lead in enumerate(hit_leads, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Claude AI enrichment [{i}/{total}]: {name}")

        result = _call_claude(lead, enrich_instructions)
        lead["activity_summary"] = result["activity_summary"]
        lead["conversion_angle"] = result["conversion_angle"]
        lead["inconsistency_detected"] = result["inconsistency_detected"]
        lead["inconsistency_reason"] = result["inconsistency_reason"]
        lead["llm_confidence"] = result["confidence"]

        if result["activity_summary"]:
            success += 1
        if result["inconsistency_detected"]:
            inconsistencies += 1
            logger.warning(
                f"Inconsistency detected for {name} ({lead.get('company')}): "
                f"{result['inconsistency_reason']}"
            )

        if _claude_disabled:
            logger.warning(f"Claude disabled — skipping remaining {total - i} leads")
            for remaining in hit_leads[i:]:
                remaining["activity_summary"] = None
                remaining["conversion_angle"] = None
                remaining["inconsistency_detected"] = False
                remaining["inconsistency_reason"] = None
                remaining["llm_confidence"] = None
            break

        if i < total:
            time.sleep(0.5)

    logger.info(
        f"Claude AI enrichment complete. {success}/{total} enriched, "
        f"{inconsistencies} inconsistencies flagged."
    )
    return hit_leads


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {
            "first_name": "Jean",
            "last_name": "Dupont",
            "job_title": "CEO",
            "company": "Acme Corp",
            "location": "Paris, France",
            "linkedin_text": "Jean Dupont est entrepreneur depuis 10 ans, spécialisé dans le SaaS B2B.",
            "website_text": "Acme Corp développe des solutions de gestion pour les PME en France.",
        },
        {
            # Homonymy trap: Apollo says France, website describes a Senegalese firm
            "first_name": "Test",
            "last_name": "Homonyme",
            "job_title": "Directeur",
            "company": "Atlas Technologies",
            "location": "Paris, France",
            "linkedin_text": "",
            "website_text": "Atlas Technologies est un acteur de l'agroalimentaire au Sénégal, "
                            "basé à Dakar, spécialisé dans la transformation de mangues. "
                            "Notre site exporte vers l'Afrique de l'Ouest.",
        },
    ]

    result = enrich_leads_gpt(test_leads)
    for lead in result:
        print(f"\n→ {lead['first_name']} {lead['last_name']}")
        print(f"  activity_summary       : {lead.get('activity_summary')}")
        print(f"  conversion_angle       : {lead.get('conversion_angle')}")
        print(f"  inconsistency_detected : {lead.get('inconsistency_detected')}")
        print(f"  inconsistency_reason   : {lead.get('inconsistency_reason')}")
        print(f"  llm_confidence         : {lead.get('llm_confidence')}")
