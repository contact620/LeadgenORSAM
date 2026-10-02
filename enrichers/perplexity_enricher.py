"""
Step 5c — Perplexity enrichment (Agent API) (hit leads only).

Two distinct searches, because they have two different scopes:

  COMPANY (SEARCH_PROMPT), cached per company — several leads of the same
  company share one answer:
    1. digital_maturity: score and assessment of the company's digital presence
    2. estimated_budget: revenue/size/funding estimates
    3. business_signals: hiring, fundraising, product launches, news

  PERSON (PERSON_PROMPT), one call per lead and NEVER cached — a person is not
  shared between leads:
    4. person_research: current role and since when, scope inside the company,
       publicly attributed achievements, public appearances.

The person search is the only channel we have on the contact themselves:
scrapers/website_scraper.py forces linkedin_text = "" on purpose so the
account never gets banned, so LinkedIn is never scraped here either. The
person prompt is given the profile URL only to tell homonyms apart.

Perplexity is only called for hit leads to keep costs low.
"""
import json
import logging
import time
from typing import Optional

import requests

import config
from api.provider_status import StepOutcome
from enrichers.retry import AuthError, QuotaExhausted, retry_api_call

logger = logging.getLogger(__name__)

# Agent API. Sonar's /chat/completions answers 403
# "chat_completions_not_available" since 2026-09.
PERPLEXITY_API_URL = "https://api.perplexity.ai/v1/responses"

# 403 payload types meaning the endpoint itself is gone, not a throughput
# ceiling: retrying them is dead time and they will not recover within a run.
_RETIRED_ENDPOINT_ERRORS = frozenset({"chat_completions_not_available"})

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

PERSON_PROMPT = """Tu es un analyste B2B. Recherche des informations publiques sur la PERSONNE ci-dessous — pas sur son entreprise.

Personne : {first_name} {last_name}
Poste déclaré (donnée non vérifiée) : {job_title}
Entreprise : {company}
Localisation : {location}
Profil LinkedIn connu (sert uniquement à écarter les homonymes) : {linkedin_url}

Recherche et retourne un JSON avec exactement ces 4 clés :

1. "poste_actuel" : le poste occupé aujourd'hui et depuis quand, avec la date au format "AAAA-MM" si elle est trouvable. Précise explicitement s'il s'agit d'une prise de poste récente et laquelle des deux : promotion ou changement de poste dans la même entreprise, ou arrivée dans une nouvelle entreprise.
2. "perimetre" : ce que cette personne pilote concrètement — équipes, budgets, zone géographique, fonctions rattachées.
3. "realisations" : projets, lancements, refontes, recrutements ou résultats publiquement associés à CETTE personne. Une puce par élément, datée "[AAAA-MM]" en début de puce.
4. "prises_de_parole" : interviews, conférences, articles, podcasts, publications. Une puce par élément, datée "[AAAA-MM]" en début de puce.

Règles :
- Chaque élément doit être attribuable à une source publique : nomme le média, le site ou la page entre parenthèses à la fin de la puce.
- Pas de source, pas d'élément. Si tu ne trouves rien de sourçable pour une clé, mets "Non disponible". Une clé vide est un résultat correct et attendu ; une supposition est une faute.
- Homonymes : si tu n'as pas la certitude qu'il s'agit bien de cette personne dans cette entreprise, mets "Non disponible" plutôt que de mélanger deux parcours.
- Ne déduis rien du poste déclaré ci-dessus : il vient d'une base non vérifiée et c'est précisément ce que tu dois confirmer ou corriger.

Réponds UNIQUEMENT en JSON brut avec ces 4 clés. Pas de markdown, pas d'explication."""

# The company half of one lead's research, and the person half. Callers that
# merely have to declare the research absent (provider skipped, --skip-gpt,
# unreachable lead) read RESEARCH_FIELDS instead of repeating the field names:
# the old 3-tuple contract was spelled out in four files, so every new field
# had to be propagated by hand to all of them.
COMPANY_RESEARCH_FIELDS: tuple[str, ...] = (
    "digital_maturity", "estimated_budget", "business_signals",
)
PERSON_RESEARCH_FIELDS: tuple[str, ...] = ("person_research",)
RESEARCH_FIELDS: tuple[str, ...] = COMPANY_RESEARCH_FIELDS + PERSON_RESEARCH_FIELDS


def blank_research() -> dict:
    """Every research field, unset — the shape of a lead Perplexity never saw."""
    return {field: None for field in RESEARCH_FIELDS}


_perplexity_disabled = False
# Why the step gave up, in words the operator can act on (reaches the run's
# provider panel). None while the step is healthy.
_disabled_reason: Optional[str] = None
# Calls actually sent and calls that came back with data. Cached hits are not
# counted: they are not evidence that the API still answers.
_calls_attempted = 0
_calls_succeeded = 0


class PerplexityUnavailable(AuthError):
    """The API refuses the request for good (retired endpoint). Subclasses
    AuthError so retry_api_call re-raises it immediately, unretried."""


def _error_type(resp) -> Optional[str]:
    try:
        body = resp.json()
    except Exception:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return None
    return body["error"].get("type")


def _output_text(data: dict) -> str:
    """Concatenate the assistant message text from an Agent API response."""
    parts = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") == "output_text" and block.get("text"):
                parts.append(block["text"])
    return "".join(parts).strip()


def _reset_state():
    """Reset module state between pipeline runs."""
    global _perplexity_disabled, _disabled_reason
    global _calls_attempted, _calls_succeeded
    _perplexity_disabled = False
    _disabled_reason = None
    _calls_attempted = 0
    _calls_succeeded = 0


def _research(prompt: str, label: str) -> Optional[dict]:
    """Send one research prompt and return the parsed JSON object, or None.

    Single owner of the provider's failure modes, shared by the company and the
    person search: a disabling error (spent quota, refused key, retired
    endpoint) sets _perplexity_disabled once and every later call — of either
    kind — short-circuits, instead of each search carrying its own idea of when
    Perplexity has become unusable for this run.
    """
    global _perplexity_disabled, _disabled_reason
    global _calls_attempted, _calls_succeeded
    if _perplexity_disabled:
        return None

    headers = {
        "Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "preset": "fast",
        "input": prompt,
        # "year", not "month": the prompt above asks for signals from the
        # last 6 months, and a 1-month recency filter silently cut off
        # everything older than that — the actual cause of "Aucun signal
        # récent identifié" on 9 pilot leads out of 10. Freshness is then
        # arbitrated downstream by icp_rules.signal_recency_months, not by
        # this filter; a wider filter here is safe because it only widens
        # what Perplexity is allowed to search, not what the scorer counts
        # as recent.
        "tools": [{
            "type": "web_search",
            "filters": {"search_recency_filter": "year"},
        }],
    }

    def _do_request():
        resp = requests.post(PERPLEXITY_API_URL, json=payload, headers=headers, timeout=60)

        # 401 is a credential problem. A bare 403 is treated as a throughput
        # ceiling and retried; only a 403 whose payload says the endpoint is
        # retired disables the provider.
        if resp.status_code == 401:
            raise AuthError(f"Perplexity auth failed (HTTP {resp.status_code})")
        if resp.status_code == 403 and _error_type(resp) in _RETIRED_ENDPOINT_ERRORS:
            raise PerplexityUnavailable(
                f"Perplexity endpoint unavailable (HTTP 403, {_error_type(resp)})"
            )

        resp.raise_for_status()
        data = resp.json()

        content = _output_text(data)
        logger.debug(f"Raw Perplexity response for {label}: {content[:200]!r}")

        # Parse JSON from response (handle markdown code blocks)
        if content.startswith("```"):
            import re
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()

        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None

    _calls_attempted += 1
    try:
        result = retry_api_call(_do_request, max_retries=2, operation_name=f"Perplexity ({label})")
    except QuotaExhausted as e:
        # retry_api_call maps 402/429 here and its contract says the balance
        # will not come back within this run. Honouring that contract means
        # stopping now: the generic branch below used to swallow this one
        # error per company, so an exhausted plan still cost one doomed call
        # per remaining company and the step reported "ok" at the end.
        _perplexity_disabled = True
        _disabled_reason = "quota Perplexity épuisé"
        logger.error(f"Perplexity quota exhausted — disabled for this run: {e}")
        return None
    except AuthError as e:
        _perplexity_disabled = True
        _disabled_reason = "clé Perplexity refusée ou endpoint indisponible"
        logger.error(f"Perplexity unusable — disabled for this run: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Perplexity returned non-JSON for {label}: {e}")
        return None
    except Exception as e:
        logger.error(f"Perplexity enrichment failed for {label}: {e}")
        return None
    _calls_succeeded += 1
    return result


def _text(value) -> Optional[str]:
    """Render one key of a research answer as operator-readable text, or None.

    A model asked for prose sometimes answers with a list or an object; dropping
    those would throw away a correct answer over its container, and passing the
    raw Python repr downstream would put brackets and quotes in front of the
    operator.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        lines = [t for t in (_text(item) for item in value) if t]
        return "\n".join(lines) or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False) or None
    return str(value).strip() or None


def _call_perplexity(lead: dict, enrich_instructions: str = "") -> dict:
    """Company research for one lead, as a COMPANY_RESEARCH_FIELDS dict.

    Returns a dict, not the former 3-tuple: the tuple's arity was duplicated in
    every caller, so adding the person search would have meant editing each of
    them. Keys are always present; a missing value is None.
    """
    company = lead.get("company", "") or "Inconnue"

    prompt = SEARCH_PROMPT.format(
        company=company,
        website=lead.get("website", "") or "Non disponible",
        location=lead.get("location", "") or "Non disponible",
        job_title=lead.get("job_title", "") or "Non disponible",
    )
    if enrich_instructions:
        prompt += f"\n\nINSTRUCTIONS SPÉCIFIQUES DE RECHERCHE :\n{enrich_instructions}\nConcentre ta recherche sur les signaux et déclencheurs mentionnés ci-dessus."

    result = _research(prompt, company)
    if result is None:
        return {field: None for field in COMPANY_RESEARCH_FIELDS}
    return {field: _text(result.get(field)) for field in COMPANY_RESEARCH_FIELDS}


# Labels of the person answer, in the order they are laid out for the fact
# extractor. French because this text is read by the operator in the export.
_PERSON_SECTIONS: tuple[tuple[str, str], ...] = (
    ("poste_actuel", "Poste actuel"),
    ("perimetre", "Périmètre"),
    ("realisations", "Réalisations"),
    ("prises_de_parole", "Prises de parole"),
)


def _call_perplexity_person(lead: dict) -> dict:
    """Person research for one lead, as a PERSON_RESEARCH_FIELDS dict.

    Never cached, unlike the company search: two leads of the same company are
    two different people, and caching this would attribute one person's career
    to their colleague.
    """
    empty = {field: None for field in PERSON_RESEARCH_FIELDS}
    if not _is_a_person(lead):
        return empty

    name = f"{lead.get('first_name', '') or ''} {lead.get('last_name', '') or ''}".strip()
    prompt = PERSON_PROMPT.format(
        first_name=lead.get("first_name", "") or "",
        last_name=lead.get("last_name", "") or "",
        job_title=lead.get("job_title", "") or "Non disponible",
        company=lead.get("company", "") or "Inconnue",
        location=lead.get("location", "") or "Non disponible",
        linkedin_url=lead.get("linkedin_url", "") or "Non disponible",
    )

    result = _research(prompt, name)
    if result is None:
        return empty

    sections = []
    for key, label in _PERSON_SECTIONS:
        text = _text(result.get(key))
        if text and not _says_nothing(text):
            sections.append(f"{label} : {text}")
    return {"person_research": "\n".join(sections) or None}


# What the prompt tells the model to answer when it found nothing sourceable.
# Kept verbatim, these lines pad the fact extractor's prompt with four
# declarations of absence and make an empty answer look like a filled one.
_NOTHING_FOUND = ("non disponible", "aucune information", "non trouvé", "non trouve")


def _says_nothing(text: str) -> bool:
    """Whether a section is the model's way of saying it found nothing."""
    stripped = text.strip().strip(".").lower()
    return stripped in _NOTHING_FOUND


def _is_a_person(lead: dict) -> bool:
    """Whether this row designates someone a person search can be run on.

    Three of the twenty contacts in the 2026-09-25 demo were legal entities
    ("Delta Btp", "Stpv Voire", "Les Marrakech"), flagged on the lead by
    processors/coherence.name_looks_like_a_company. Asking Perplexity what
    "Delta Btp" has achieved in their career cannot succeed, and the call is
    billed all the same.
    """
    if lead.get("name_looks_like_company") is True:
        return False
    name = f"{lead.get('first_name', '') or ''} {lead.get('last_name', '') or ''}".strip()
    return bool(name)


def enrich_leads_perplexity(hit_leads: list[dict], enrich_instructions: str = "", registry=None) -> list[dict]:
    """
    For each hit lead, run both searches and store every RESEARCH_FIELDS key:
    the three company fields (cached per company) and person_research (one
    call per lead, never cached).
    """
    # Without this, _perplexity_disabled stayed true for the life of the
    # server process: one disabling error in run N silently skipped
    # Perplexity in every later run. _reset_state existed but nothing but
    # the tests ever called it.
    _reset_state()

    if config._is_placeholder(config.PERPLEXITY_API_KEY):
        logger.warning("PERPLEXITY_API_KEY not set. Skipping Perplexity enrichment.")
        for lead in hit_leads:
            lead.update(blank_research())
        if registry:
            registry.record(StepOutcome("perplexity", "skipped", "clé API absente", 0))
        return hit_leads

    total = len(hit_leads)
    success = 0
    persons = 0

    # Deduplicate: only call once per company. The person search is excluded
    # from this cache on purpose — see _call_perplexity_person.
    company_cache: dict[str, dict] = {}

    for i, lead in enumerate(hit_leads, 1):
        company = (lead.get("company") or "").strip().lower()
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Perplexity enrichment [{i}/{total}]: {name} ({lead.get('company', '')})")

        cached = company and company in company_cache
        if cached:
            company_research = company_cache[company]
            logger.debug(f"  Using cached Perplexity result for {lead.get('company', '')}")
        else:
            company_research = _call_perplexity(lead, enrich_instructions)
            if company:
                company_cache[company] = company_research

        # Spread the two calls of one lead instead of firing them back to back.
        if not cached and not _perplexity_disabled:
            time.sleep(0.5)

        person_research = _call_perplexity_person(lead)

        lead.update(company_research)
        lead.update(person_research)

        if company_research.get("digital_maturity"):
            success += 1
        if person_research.get("person_research"):
            persons += 1

        if _perplexity_disabled:
            logger.warning(f"Perplexity disabled — skipping remaining {total - i} leads")
            for remaining in hit_leads[i:]:
                remaining.update(blank_research())
            break

        if i < total:
            time.sleep(1.0)  # Rate limiting

    unique_companies = len(company_cache)
    logger.info(
        f"Perplexity enrichment complete. {success}/{total} leads enriched "
        f"({unique_companies} unique companies queried), "
        f"{persons}/{total} person profiles researched."
    )
    if registry:
        registry.record(StepOutcome("perplexity", *_health(), success))
    return hit_leads


def _health() -> tuple[str, Optional[str]]:
    """Status and reason for this run's Perplexity enrichment.

    A run where every call failed used to report "ok": each lead got its
    research fields set to None, which is also what a skipped provider leaves
    behind.
    """
    if _perplexity_disabled:
        return "degraded", _disabled_reason
    if _calls_attempted and not _calls_succeeded:
        return "degraded", f"aucun appel abouti sur {_calls_attempted}"
    return "ok", None
