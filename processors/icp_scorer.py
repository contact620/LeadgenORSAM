"""
Step 5 — ICP scoring (hit leads only).

Evaluates each hit lead's fit as a potential BoxCom client using Claude Haiku.
Leads are batched (default 5 per API call) for cost efficiency.
The ICP (Ideal Customer Profile) is defined in the system prompt — not user input.

Produces per lead:
  - icp_score (0-100, weighted from 4 axes)
  - icp_tier  ("hot" / "warm" / "cold")
  - icp_rationale (2-3 sentence justification)
  - icp_scores_detail (JSON string with per-axis scores)
"""
import json
import logging
import os
import re
import time
from typing import Optional

import anthropic

import config
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

# ── Axis weights (must sum to 1.0) ──────────────────────────────────────────
AXIS_WEIGHTS = {
    "secteur": 0.20,
    "taille": 0.20,
    "localisation": 0.20,
    "signaux": 0.40,
}

DEFAULT_SYSTEM_PROMPT = """\
Tu es un expert en qualification de leads B2B pour BoxCom, une agence de communication digitale \
basée au Maroc avec +10 ans d'expertise.

BoxCom propose 4 services principaux :
- Marketing Digital (stratégie, ads, SEO, réseaux sociaux)
- Contenu Créatif (branding, vidéo, motion design, social media)
- Développement Web (sites vitrines, e-commerce, landing pages)
- Lead Generation (funnels, lead scoring, campagnes d'acquisition)

Pour chaque prospect, évalue sa pertinence comme client potentiel pour BoxCom \
sur 4 axes (score 0-100 chacun) :

1. **secteur** (20%) — L'entreprise opère-t-elle dans un secteur où BoxCom apporte une forte \
valeur ajoutée ? (e-commerce, SaaS, services B2B, immobilier, éducation, santé, tourisme = élevé)
2. **taille** (20%) — PME/ETI 10-500 employés = élevé ; micro-entreprise ou grand groupe = moyen/bas
3. **localisation** (20%) — Maroc, Afrique francophone, France = élevé
4. **signaux** (40%) — Signaux de besoin pour les services BoxCom ? (site obsolète, pas de social media, \
recrutement marketing, lancement produit, levée de fonds, expansion, refonte digitale, croissance rapide...)

Note : le poste/séniorité n'est PAS évalué ici — déjà filtré en amont via Apollo.

Puis génère :
- "icp_rationale" : 2-3 phrases justifiant les scores, mentionnant les services BoxCom pertinents.

Réponds UNIQUEMENT en JSON : un tableau d'objets dans le même ordre que les prospects.
Chaque objet a les clés : "secteur" (int), "taille" (int), "localisation" (int), "signaux" (int), \
"icp_rationale" (string).
Pas de markdown, pas d'explication, juste le JSON brut."""

_icp_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _icp_disabled
    _icp_disabled = False


def _load_system_prompt() -> str:
    """Load system prompt from file, falling back to embedded default."""
    prompt_path = config.ICP_PROMPT_PATH
    # Resolve relative to project root
    if not os.path.isabs(prompt_path):
        project_root = os.path.dirname(os.path.dirname(__file__))
        prompt_path = os.path.join(project_root, prompt_path)
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return content
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"Cannot load ICP prompt from {prompt_path}: {e}. Using default.")
    return DEFAULT_SYSTEM_PROMPT


def _build_batch_user_prompt(leads: list[dict]) -> str:
    """Build the user prompt for a batch of leads."""
    parts = [
        "Évalue chaque prospect ci-dessous comme client potentiel pour BoxCom.\n",
    ]
    for i, lead in enumerate(leads, 1):
        parts.append(f"Prospect {i} :")
        parts.append(f"  Prénom: {lead.get('first_name', 'N/A')}")
        parts.append(f"  Nom: {lead.get('last_name', 'N/A')}")
        parts.append(f"  Poste: {lead.get('job_title', 'N/A')}")
        parts.append(f"  Entreprise: {lead.get('company', 'N/A')}")
        parts.append(f"  Localisation: {lead.get('location', 'N/A')}")
        parts.append(f"  Email: {lead.get('email', 'N/A')}")
        parts.append(f"  LinkedIn: {lead.get('linkedin_url', 'N/A')}")
        parts.append(f"  Site web: {lead.get('website', 'N/A')}")
        parts.append("")
    return "\n".join(parts)


def _compute_weighted_score(scores: dict) -> int:
    """Compute weighted ICP score from per-axis scores."""
    total = 0.0
    for axis, weight in AXIS_WEIGHTS.items():
        value = scores.get(axis, 0)
        if not isinstance(value, (int, float)):
            value = 0
        total += max(0, min(100, value)) * weight
    return round(total)


def _score_to_tier(score: int) -> str:
    """Map numeric score to tier label."""
    if score > 70:
        return "hot"
    elif score >= 40:
        return "warm"
    return "cold"


def _parse_response(text: str, expected_count: int) -> list[Optional[dict]]:
    """Parse Claude's JSON response, returning a list of score dicts (or None for failures)."""
    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()

    # Try direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) == expected_count:
            return data
    except json.JSONDecodeError:
        pass

    # Fallback: extract JSON array with regex
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list) and len(data) == expected_count:
                return data
        except json.JSONDecodeError:
            pass

    logger.warning(f"ICP: could not parse response or count mismatch (expected {expected_count})")
    return [None] * expected_count


def _call_claude_batch(leads: list[dict]) -> list[Optional[dict]]:
    """Call Claude Haiku for a batch of leads. Returns list of score dicts."""
    global _icp_disabled
    if _icp_disabled:
        return [None] * len(leads)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system_prompt = _load_system_prompt()
    user_prompt = _build_batch_user_prompt(leads)

    batch_size = len(leads)
    lead_names = ", ".join(
        f"{l.get('first_name', '')} {l.get('last_name', '')}".strip() for l in leads
    )

    def _do_request():
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200 * batch_size,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = message.content[0].text.strip()
        logger.debug(f"Raw ICP response: {content!r}")
        return _parse_response(content, batch_size)

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"ICP scoring ({lead_names})")
    except AuthError as e:
        _icp_disabled = True
        logger.error(f"ICP scoring auth failed — disabled for this run: {e}")
        return [None] * batch_size
    except Exception as e:
        logger.error(f"ICP scoring failed after retries for batch [{lead_names}]: {e}")
        return [None] * batch_size


def score_leads_icp(hit_leads: list[dict]) -> list[dict]:
    """
    Score hit leads against BoxCom's ICP. Sets on each lead:
      lead["icp_score"]         — int 0-100
      lead["icp_tier"]          — "hot" / "warm" / "cold"
      lead["icp_rationale"]     — string
      lead["icp_scores_detail"] — JSON string {"secteur": .., "taille": .., ...}
    """
    _reset_state()

    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping ICP scoring.")
        for lead in hit_leads:
            lead["icp_score"] = None
            lead["icp_tier"] = None
            lead["icp_rationale"] = None
            lead["icp_scores_detail"] = None
        return hit_leads

    total = len(hit_leads)
    batch_size = config.ICP_BATCH_SIZE
    scored = 0

    for batch_start in range(0, total, batch_size):
        batch = hit_leads[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"ICP scoring [batch {batch_num}/{total_batches}]: {len(batch)} leads")

        results = _call_claude_batch(batch)

        for lead, result in zip(batch, results):
            if result and isinstance(result, dict):
                detail = {
                    "secteur": result.get("secteur", 0),
                    "taille": result.get("taille", 0),
                    "localisation": result.get("localisation", 0),
                    "signaux": result.get("signaux", 0),
                }
                score = _compute_weighted_score(detail)
                lead["icp_score"] = score
                lead["icp_tier"] = _score_to_tier(score)
                lead["icp_rationale"] = result.get("icp_rationale", "")
                lead["icp_scores_detail"] = json.dumps(detail)
                scored += 1
            else:
                lead["icp_score"] = None
                lead["icp_tier"] = None
                lead["icp_rationale"] = None
                lead["icp_scores_detail"] = None

        if _icp_disabled:
            logger.warning(f"ICP disabled — skipping remaining {total - batch_start - len(batch)} leads")
            for remaining in hit_leads[batch_start + len(batch):]:
                remaining["icp_score"] = None
                remaining["icp_tier"] = None
                remaining["icp_rationale"] = None
                remaining["icp_scores_detail"] = None
            break

        # Rate limit between batches
        if batch_start + batch_size < total:
            time.sleep(0.5)

    logger.info(f"ICP scoring complete. {scored}/{total} leads scored.")
    return hit_leads
