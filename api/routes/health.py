import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter
import config as pipeline_config

router = APIRouter()


@router.get("/health")
def health_check():
    missing = pipeline_config.validate_config()
    apollo_cookies_ok = os.path.exists(pipeline_config.APOLLO_COOKIES_PATH)
    linkedin_cookies_ok = os.path.exists(pipeline_config.LINKEDIN_COOKIES_PATH)

    return {
        "status": "ok",
        "missing_keys": missing,
        "apollo_cookies": apollo_cookies_ok,
        "linkedin_cookies": linkedin_cookies_ok,
        "hit_threshold": pipeline_config.HIT_THRESHOLD,
        "max_leads_default": pipeline_config.MAX_LEADS,
    }
