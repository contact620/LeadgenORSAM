import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

# ── LLM model used by enrichers/angle_writer.py (Step 8) ──────────────────────
# Sonnet 4.6 default — better reasoning than Haiku for B2B context analysis
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")

# ── File Paths ─────────────────────────────────────────────────────────────────
APOLLO_COOKIES_PATH = os.getenv("APOLLO_COOKIES_PATH", "apollo_cookies.json")
OUTPUT_DIR = "output"

# ── Behavior ──────────────────────────────────────────────────────────────────
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2.0"))
HIT_THRESHOLD = int(os.getenv("HIT_THRESHOLD", "50"))
MAX_LEADS = int(os.getenv("MAX_LEADS", "500"))
# Run browser visibly — bypasses Apollo anti-bot detection (recommended: False = visible)
APOLLO_HEADLESS = os.getenv("APOLLO_HEADLESS", "false").lower() == "true"

# ── ICP Scoring ──────────────────────────────────────────────────────────────
ICP_BATCH_SIZE = int(os.getenv("ICP_BATCH_SIZE", "5"))

# ── Quotas fournisseurs ───────────────────────────────────────────────────────
# Valeurs par défaut du plan gratuit de chaque fournisseur, corrigées au
# démarrage de chaque run par enrichers/providers/quota_sync.py quand le
# fournisseur expose son solde. Jamais codées en dur ailleurs.
PROVIDER_ALLOCATIONS: dict[str, float] = {
    "prospeo": float(os.getenv("PROSPEO_MONTHLY_ALLOCATION", "100")),
    "hunter": float(os.getenv("HUNTER_MONTHLY_ALLOCATION", "50")),
    "getprospect": float(os.getenv("GETPROSPECT_MONTHLY_ALLOCATION", "50")),
    "getprospect_verify": float(os.getenv("GETPROSPECT_VERIFY_ALLOCATION", "100")),
}

# Report des crédits non consommés, exprimé en multiples de l'allocation.
# 0.0 = aucun report. GetProspect reporte jusqu'à un mois d'allocation.
PROVIDER_ROLLOVER_CAP: dict[str, float] = {
    "prospeo": float(os.getenv("PROSPEO_ROLLOVER_CAP", "0")),
    "hunter": float(os.getenv("HUNTER_ROLLOVER_CAP", "0")),
    "getprospect": float(os.getenv("GETPROSPECT_ROLLOVER_CAP", "1")),
    "getprospect_verify": float(os.getenv("GETPROSPECT_VERIFY_ROLLOVER_CAP", "1")),
}

PROSPEO_API_KEY = os.getenv("PROSPEO_API_KEY", "")
GETPROSPECT_API_KEY = os.getenv("GETPROSPECT_API_KEY", "")


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
            "sameSite": sameSite_map.get((c.get("sameSite") or "lax").lower(), "Lax"),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp:
            cookie["expires"] = int(exp)
        cookies.append(cookie)
    return cookies


def _is_placeholder(value: str) -> bool:
    """Return True if the value looks like an unedited .env.example placeholder."""
    v = value.strip().lower()
    return not v or v.startswith("your_") or v in ("changeme", "xxx", "todo")


def validate_config():
    missing = []
    if _is_placeholder(ANTHROPIC_API_KEY):
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        logging.warning(f"Missing environment variables: {', '.join(missing)}")
    return missing
