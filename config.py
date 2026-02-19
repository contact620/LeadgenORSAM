import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX = os.getenv("GOOGLE_CX", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
DROPCONTACT_API_KEY = os.getenv("DROPCONTACT_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── File Paths ─────────────────────────────────────────────────────────────────
APOLLO_COOKIES_PATH = os.getenv("APOLLO_COOKIES_PATH", "apollo_cookies.json")
LINKEDIN_COOKIES_PATH = os.getenv("LINKEDIN_COOKIES_PATH", "linkedin_cookies.json")
OUTPUT_DIR = "output"

# ── Behavior ──────────────────────────────────────────────────────────────────
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2.0"))
HIT_THRESHOLD = int(os.getenv("HIT_THRESHOLD", "50"))
DROPCONTACT_BATCH_SIZE = int(os.getenv("DROPCONTACT_BATCH_SIZE", "50"))
MAX_LEADS = int(os.getenv("MAX_LEADS", "500"))
# Run browser visibly — bypasses Apollo anti-bot detection (recommended: False = visible)
APOLLO_HEADLESS = os.getenv("APOLLO_HEADLESS", "false").lower() == "true"

# ── Hit Score Weights ─────────────────────────────────────────────────────────
SCORE_EMAIL = 40
SCORE_LINKEDIN = 30
SCORE_PHONE = 20
SCORE_WEBSITE = 10


def load_cookies(path: str) -> list[dict]:
    """Load cookies and normalize Cookie-Editor format → Playwright format."""
    if not os.path.exists(path):
        logging.warning(f"Cookie file not found: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    sameSite_map = {"no_restriction": "None", "lax": "Lax", "strict": "Strict", "unspecified": "Lax"}
    cookies = []
    for c in raw:
        cookie = {
            "name":     c.get("name", ""),
            "value":    c.get("value", ""),
            "domain":   c.get("domain", ""),
            "path":     c.get("path", "/"),
            "httpOnly": c.get("httpOnly", False),
            "secure":   c.get("secure", False),
            "sameSite": sameSite_map.get(c.get("sameSite", "lax").lower(), "Lax"),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp:
            cookie["expires"] = int(exp)
        cookies.append(cookie)
    return cookies


def validate_config():
    missing = []
    if not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if not GOOGLE_CX:
        missing.append("GOOGLE_CX")
    # DROPCONTACT_API_KEY is optional — email/phone enrichment is skipped if absent
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        logging.warning(f"Missing environment variables: {', '.join(missing)}")
    return missing
