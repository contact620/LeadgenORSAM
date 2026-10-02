import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from dotenv import set_key, load_dotenv

import config as pipeline_config
from config import _is_placeholder
from enrichers.retry import CREDIT_EXHAUSTED_MESSAGE, is_credit_exhausted

router = APIRouter()

_ENV_PATH = pipeline_config.ENV_PATH


class ConfigUpdate(BaseModel):
    serper_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    hunter_api_key: Optional[str] = None
    prospeo_api_key: Optional[str] = None
    getprospect_api_key: Optional[str] = None
    hit_threshold: Optional[int] = None
    max_leads: Optional[int] = None
    services: Optional[list[str]] = None


@router.get("/config")
def get_config():
    # Always reload .env so manual edits are reflected without a server restart
    load_dotenv(_ENV_PATH, override=True)
    pipeline_config.SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
    pipeline_config.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    pipeline_config.PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
    pipeline_config.HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
    pipeline_config.PROSPEO_API_KEY = os.getenv("PROSPEO_API_KEY", "")
    pipeline_config.GETPROSPECT_API_KEY = os.getenv("GETPROSPECT_API_KEY", "")
    pipeline_config.HIT_THRESHOLD = int(os.getenv("HIT_THRESHOLD", "50"))
    pipeline_config.MAX_LEADS = int(os.getenv("MAX_LEADS", "500"))

    # Load services list
    services = []
    services_str = os.getenv("BOXCOM_SERVICES", "")
    if services_str:
        services = [s.strip() for s in services_str.split("|") if s.strip()]

    from api import quota_db
    quotas = {
        name: {
            "remaining": quota_db.get_quota(name)["remaining"],
            "allocation": quota_db.get_quota(name)["allocation"],
            "reset_date": quota_db.get_quota(name)["reset_date"],
        }
        for name in pipeline_config.PROVIDER_ALLOCATIONS
    }

    return {
        "serper_api_key": not _is_placeholder(pipeline_config.SERPER_API_KEY),
        "anthropic_api_key": not _is_placeholder(pipeline_config.ANTHROPIC_API_KEY),
        "perplexity_api_key": not _is_placeholder(pipeline_config.PERPLEXITY_API_KEY),
        "hunter_api_key": not _is_placeholder(pipeline_config.HUNTER_API_KEY),
        "prospeo_api_key": not _is_placeholder(pipeline_config.PROSPEO_API_KEY),
        "getprospect_api_key": not _is_placeholder(pipeline_config.GETPROSPECT_API_KEY),
        "apollo_cookies": os.path.exists(pipeline_config.APOLLO_COOKIES_PATH),
        "hit_threshold": pipeline_config.HIT_THRESHOLD,
        "max_leads": pipeline_config.MAX_LEADS,
        "services": services,
        "quotas": quotas,
    }


@router.post("/config")
def update_config(body: ConfigUpdate):
    # Ensure .env exists
    if not os.path.exists(_ENV_PATH):
        open(_ENV_PATH, "w").close()

    updates: dict[str, str] = {}
    if body.serper_api_key is not None:
        updates["SERPER_API_KEY"] = body.serper_api_key
    if body.anthropic_api_key is not None:
        updates["ANTHROPIC_API_KEY"] = body.anthropic_api_key
    if body.perplexity_api_key is not None:
        updates["PERPLEXITY_API_KEY"] = body.perplexity_api_key
    if body.hunter_api_key is not None:
        updates["HUNTER_API_KEY"] = body.hunter_api_key
    if body.prospeo_api_key is not None:
        updates["PROSPEO_API_KEY"] = body.prospeo_api_key
    if body.getprospect_api_key is not None:
        updates["GETPROSPECT_API_KEY"] = body.getprospect_api_key
    if body.hit_threshold is not None:
        updates["HIT_THRESHOLD"] = str(body.hit_threshold)
    if body.max_leads is not None:
        updates["MAX_LEADS"] = str(body.max_leads)
    if body.services is not None:
        updates["BOXCOM_SERVICES"] = "|".join(body.services)

    for env_key, value in updates.items():
        set_key(_ENV_PATH, env_key, value)

    # Reload into os.environ and update the live module variables
    load_dotenv(_ENV_PATH, override=True)
    pipeline_config.SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
    pipeline_config.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    pipeline_config.PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
    pipeline_config.HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
    pipeline_config.PROSPEO_API_KEY = os.getenv("PROSPEO_API_KEY", "")
    pipeline_config.GETPROSPECT_API_KEY = os.getenv("GETPROSPECT_API_KEY", "")
    if body.hit_threshold is not None:
        pipeline_config.HIT_THRESHOLD = body.hit_threshold
    if body.max_leads is not None:
        pipeline_config.MAX_LEADS = body.max_leads

    return {"ok": True}


async def _save_cookies(file: UploadFile, path: str) -> dict:
    content = await file.read()
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Fichier JSON invalide")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Le fichier doit contenir une liste de cookies (array JSON)")

    with open(path, "wb") as f:
        f.write(content)

    return {"ok": True, "count": len(data)}


@router.post("/cookies/apollo")
async def upload_apollo_cookies(file: UploadFile = File(...)):
    return await _save_cookies(file, pipeline_config.APOLLO_COOKIES_PATH)


@router.post("/config/validate-key")
async def validate_api_key(body: dict):
    """Test an API key before saving. Returns {valid: bool, error?: str}."""
    key_type = body.get("type", "")
    key_value = body.get("value", "")

    if not key_value:
        return {"valid": False, "error": "Clé vide"}

    try:
        if key_type == "serper":
            import requests
            resp = requests.get(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key_value, "Content-Type": "application/json"},
                json={"q": "test", "num": 1},
                timeout=10,
            )
            if resp.status_code in (401, 403):
                return {"valid": False, "error": "Clé invalide (401/403)"}
            return {"valid": True}

        elif key_type == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=key_value)
            try:
                client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=5,
                    messages=[{"role": "user", "content": "hi"}],
                )
            except Exception as e:
                # Without these two branches the fallback below answered with
                # repr(SDK error) truncated at 200 characters: an English
                # payload dump in which a spent balance (HTTP 400) and a bad
                # key (HTTP 401) look alike, although the operator has to do
                # something different about each.
                if is_credit_exhausted(e):
                    return {"valid": False,
                            "error": f"Clé valide, mais {CREDIT_EXHAUSTED_MESSAGE}."}
                if getattr(e, "status_code", None) in (401, 403):
                    return {"valid": False, "error": "Clé invalide"}
                raise
            return {"valid": True}

        elif key_type == "perplexity":
            import requests
            resp = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {key_value}", "Content-Type": "application/json"},
                json={"model": "sonar", "messages": [{"role": "user", "content": "test"}], "max_tokens": 5},
                timeout=10,
            )
            if resp.status_code in (401, 403):
                return {"valid": False, "error": "Clé invalide"}
            return {"valid": True}

        elif key_type == "hunter":
            import requests
            # /account is the lightest authenticated endpoint
            resp = requests.get(
                "https://api.hunter.io/v2/account",
                params={"api_key": key_value},
                timeout=10,
            )
            if resp.status_code in (401, 403):
                return {"valid": False, "error": "Clé invalide"}
            if resp.status_code >= 400:
                return {"valid": False, "error": f"Erreur Hunter.io ({resp.status_code})"}
            return {"valid": True}

        elif key_type == "prospeo":
            import requests
            # /account-information is documented as free.
            resp = requests.get(
                "https://api.prospeo.io/account-information",
                headers={"X-KEY": key_value}, timeout=10,
            )
            body = resp.json() if resp.content else {}
            if body.get("error") and body.get("error_code") == "INVALID_API_KEY":
                return {"valid": False, "error": "Clé invalide"}
            return {"valid": True}

        elif key_type == "getprospect":
            import requests
            # No account endpoint exists: a minimal find against a domain that
            # yields nothing is refunded, so this costs no credit.
            resp = requests.post(
                "https://api.getprospect.com/v2/email/find",
                headers={"x-api-key": key_value, "Content-Type": "application/json"},
                json={"data": {"first_name": "Zzqx", "last_name": "Vbnm",
                               "domain": "example.com"}},
                timeout=15,
            )
            if resp.status_code == 401:
                return {"valid": False, "error": "Clé invalide"}
            return {"valid": True}

        else:
            return {"valid": True}  # unknown key type, skip validation

    except Exception as e:
        return {"valid": False, "error": str(e)[:200]}


@router.post("/config/cleanup-csv")
async def cleanup_old_csv(body: dict = {"max_age_days": 30}):
    """Delete CSV files older than max_age_days."""
    import time
    max_age = body.get("max_age_days", 30) * 86400
    output_dir = pipeline_config.OUTPUT_DIR
    deleted = 0
    if os.path.isdir(output_dir):
        now = time.time()
        for fname in os.listdir(output_dir):
            if fname.endswith(".csv"):
                fpath = os.path.join(output_dir, fname)
                if now - os.path.getmtime(fpath) > max_age:
                    os.remove(fpath)
                    deleted += 1
    return {"deleted": deleted}


