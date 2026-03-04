import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from dotenv import set_key, load_dotenv

import config as pipeline_config

router = APIRouter()

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")


class ConfigUpdate(BaseModel):
    serper_api_key: Optional[str] = None
    dropcontact_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    hit_threshold: Optional[int] = None
    max_leads: Optional[int] = None


@router.get("/config")
def get_config():
    # Always reload .env so manual edits are reflected without a server restart
    load_dotenv(_ENV_PATH, override=True)
    pipeline_config.SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
    pipeline_config.DROPCONTACT_API_KEY = os.getenv("DROPCONTACT_API_KEY", "")
    pipeline_config.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    pipeline_config.HIT_THRESHOLD = int(os.getenv("HIT_THRESHOLD", "50"))
    pipeline_config.MAX_LEADS = int(os.getenv("MAX_LEADS", "500"))

    return {
        "serper_api_key": bool(pipeline_config.SERPER_API_KEY),
        "dropcontact_api_key": bool(pipeline_config.DROPCONTACT_API_KEY),
        "anthropic_api_key": bool(pipeline_config.ANTHROPIC_API_KEY),
        "apollo_cookies": os.path.exists(pipeline_config.APOLLO_COOKIES_PATH),
        "hit_threshold": pipeline_config.HIT_THRESHOLD,
        "max_leads": pipeline_config.MAX_LEADS,
    }


@router.post("/config")
def update_config(body: ConfigUpdate):
    # Ensure .env exists
    if not os.path.exists(_ENV_PATH):
        open(_ENV_PATH, "w").close()

    updates: dict[str, str] = {}
    if body.serper_api_key is not None:
        updates["SERPER_API_KEY"] = body.serper_api_key
    if body.dropcontact_api_key is not None:
        updates["DROPCONTACT_API_KEY"] = body.dropcontact_api_key
    if body.anthropic_api_key is not None:
        updates["ANTHROPIC_API_KEY"] = body.anthropic_api_key
    if body.hit_threshold is not None:
        updates["HIT_THRESHOLD"] = str(body.hit_threshold)
    if body.max_leads is not None:
        updates["MAX_LEADS"] = str(body.max_leads)

    for env_key, value in updates.items():
        set_key(_ENV_PATH, env_key, value)

    # Reload into os.environ and update the live module variables
    load_dotenv(_ENV_PATH, override=True)
    pipeline_config.SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
    pipeline_config.DROPCONTACT_API_KEY = os.getenv("DROPCONTACT_API_KEY", "")
    pipeline_config.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
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


