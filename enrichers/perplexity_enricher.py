"""
Step 5c — Perplexity Sonar enrichment (hit leads only).

For each hit lead, calls Perplexity Sonar API to research:
  1. digital_maturity: score and assessment of the company's digital presence
  2. estimated_budget: revenue/size/funding estimates
  3. business_signals: hiring, fundraising, product launches, news

Perplexity is only called for hit leads to keep costs low.
"""
import json
import logging
import time
from typing import Optional

import requests

import config
from api.provider_status import StepOutcome
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

SEARCH_PROMPT = """Tu es un analyste B2B. Pour l'entreprise ci-dessous, recherche et structure les informations suivantes.

Entreprise : {company}
Site web : {website}
Localisation : {location}
Secteur estimé (via le poste du contact) : {job_title}

Recherche et retourne un JSON avec exactement ces 3 clés :

1. "digital_maturity" : Évalue la maturité digitale de l'entreprise (score de 1 à 10) avec une justification courte. Analyse : présence sur les réseaux sociaux, qualité du site web, outils marketing/tech utilisés, blog actif, SEO visible. Format: "Score: X/10 — [justification en 1-2 phrases]"

2. "estimated_budget" : Estime la taille/budget de l'entreprise. Cherche : chiffre d'affaires, nombre d'employés, levées de fonds, taille de l'équipe. Si les données exactes ne sont pas trouvées, donne une estimation basée sur les indices disponibles. Format: "[effectif estimé] employés — [CA ou fourchette si disponible] — [autres indices financiers]"

3. "business_signals" : Liste les signaux business récents (6 derniers mois). Cherche : recrutements en cours, levées de fonds, lancements de produits, nouveaux partenariats, expansion géographique, changements de direction, actualités. Pour CHAQUE signal trouvé, indique sa date au format ISO "AAAA-MM" (année-mois) entre crochets en début de puce, par exemple "- [2026-05] Levée de fonds de 2M€". Si tu ne connais que le mois approximatif, donne ta meilleure estimation plutôt que d'omettre la date — un signal sans date ne peut pas être évalué comme récent en aval. Format: liste à puces datées, ou "Aucun signal récent identifié" si rien trouvé.

Réponds UNIQUEMENT en JSON brut avec ces 3 clés. Pas de markdown, pas d'explication."""

_perplexity_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _perplexity_disabled
    _perplexity_disabled = False


def _call_perplexity(lead: dict, enrich_instructions: str = "") -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Call Perplexity Sonar for a single lead. Returns (digital_maturity, estimated_budget, business_signals)."""
    global _perplexity_disabled
    if _perplexity_disabled:
        return None, None, None

    company = lead.get("company", "") or "Inconnue"
    website = lead.get("website", "") or "Non disponible"
    location = lead.get("location", "") or "Non disponible"
    job_title = lead.get("job_title", "") or "Non disponible"
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    prompt = SEARCH_PROMPT.format(
        company=company,
        website=website,
        location=location,
        job_title=job_title,
    )

    if enrich_instructions:
        prompt += f"\n\nINSTRUCTIONS SPÉCIFIQUES DE RECHERCHE :\n{enrich_instructions}\nConcentre ta recherche sur les signaux et déclencheurs mentionnés ci-dessus."

    headers = {
        "Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "sonar",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        # "year", not "month": the prompt above asks for signals from the
        # last 6 months, and a 1-month recency filter silently cut off
        # everything older than that — the actual cause of "Aucun signal
        # récent identifié" on 9 pilot leads out of 10. Freshness is then
        # arbitrated downstream by icp_rules.signal_recency_months, not by
        # this filter; a wider filter here is safe because it only widens
        # what Perplexity is allowed to search, not what the scorer counts
        # as recent.
        "search_recency_filter": "year",
    }

    def _do_request():
        resp = requests.post(PERPLEXITY_API_URL, json=payload, headers=headers, timeout=60)

        if resp.status_code in (401, 403):
            raise AuthError(f"Perplexity auth failed (HTTP {resp.status_code})")

        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"Raw Perplexity response for {company}: {content[:200]!r}")

        # Parse JSON from response (handle markdown code blocks)
        if content.startswith("```"):
            import re
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()

        result = json.loads(content)
        return (
            result.get("digital_maturity", "").strip() if result.get("digital_maturity") else None,
            result.get("estimated_budget", "").strip() if result.get("estimated_budget") else None,
            result.get("business_signals", "").strip() if isinstance(result.get("business_signals"), str) else json.dumps(result.get("business_signals"), ensure_ascii=False) if result.get("business_signals") else None,
        )

    try:
        return retry_api_call(_do_request, max_retries=2, operation_name=f"Perplexity ({company})")
    except AuthError as e:
        _perplexity_disabled = True
        logger.error(f"Perplexity auth failed — disabled for this run: {e}")
        return None, None, None
    except json.JSONDecodeError as e:
        logger.warning(f"Perplexity returned non-JSON for {company}: {e}")
        return None, None, None
    except Exception as e:
        logger.error(f"Perplexity enrichment failed for {company}: {e}")
        return None, None, None


def enrich_leads_perplexity(hit_leads: list[dict], enrich_instructions: str = "", registry=None) -> list[dict]:
    """
    For each hit lead, call Perplexity Sonar and store:
      lead["digital_maturity"]
      lead["estimated_budget"]
      lead["business_signals"]
    """
    if config._is_placeholder(config.PERPLEXITY_API_KEY):
        logger.warning("PERPLEXITY_API_KEY not set. Skipping Perplexity enrichment.")
        for lead in hit_leads:
            lead["digital_maturity"] = None
            lead["estimated_budget"] = None
            lead["business_signals"] = None
        return hit_leads

    total = len(hit_leads)
    success = 0

    # Deduplicate: only call once per company
    company_cache: dict[str, tuple] = {}

    for i, lead in enumerate(hit_leads, 1):
        company = (lead.get("company") or "").strip().lower()
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Perplexity enrichment [{i}/{total}]: {name} ({lead.get('company', '')})")

        if company and company in company_cache:
            maturity, budget, signals = company_cache[company]
            logger.debug(f"  Using cached Perplexity result for {lead.get('company', '')}")
        else:
            maturity, budget, signals = _call_perplexity(lead, enrich_instructions)
            if company:
                company_cache[company] = (maturity, budget, signals)

        lead["digital_maturity"] = maturity
        lead["estimated_budget"] = budget
        lead["business_signals"] = signals

        if maturity:
            success += 1

        if _perplexity_disabled:
            logger.warning(f"Perplexity disabled — skipping remaining {total - i} leads")
            for remaining in hit_leads[i:]:
                remaining["digital_maturity"] = None
                remaining["estimated_budget"] = None
                remaining["business_signals"] = None
            break

        if i < total:
            time.sleep(1.0)  # Rate limiting

    unique_companies = len(company_cache)
    logger.info(
        f"Perplexity enrichment complete. {success}/{total} leads enriched "
        f"({unique_companies} unique companies queried)."
    )
    if registry:
        status = "degraded" if _perplexity_disabled else "ok"
        registry.record(StepOutcome("perplexity", status, None, success))
    return hit_leads
