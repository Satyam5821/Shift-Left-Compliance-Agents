import json
import os
from typing import Dict

from dotenv import load_dotenv


load_dotenv()


SONAR_TOKEN = os.getenv("SONAR_TOKEN")
SONAR_PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")
SONAR_VERIFY = os.getenv("SONAR_VERIFY", "true").lower() not in ("false", "0", "no")
SONAR_TOKEN_ENC_KEY = os.getenv("SONAR_TOKEN_ENC_KEY")

# Optional JSON map: {"owner/repo": "SonarCloudProjectKey", ...} when the key is not owner_repo.
_sonar_map_raw = (os.getenv("SONAR_PROJECT_KEYS_JSON") or "").strip()
SONAR_PROJECT_KEYS_BY_REPO: Dict[str, str] = {}
if _sonar_map_raw:
    try:
        parsed = json.loads(_sonar_map_raw)
        if isinstance(parsed, dict):
            SONAR_PROJECT_KEYS_BY_REPO = {str(k).strip(): str(v).strip() for k, v in parsed.items() if k and v}
    except Exception:
        SONAR_PROJECT_KEYS_BY_REPO = {}

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

# Gemini intentionally unused/disabled (OpenRouter only), kept for env compatibility
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

# GitHub-only code context source (repo being scanned/fixed)
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME")
GITHUB_REF = os.getenv("GITHUB_REF", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Webhook/PR automation (GitHub App) - optional, used for "no files in target repo" mode
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")  # numeric string
GITHUB_APP_PRIVATE_KEY_PEM = os.getenv("GITHUB_APP_PRIVATE_KEY_PEM")  # full PEM string
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")  # for X-Hub-Signature-256 verification

# GitHub App install onboarding / non-webhook API access
# - For hosted mode, you can set GITHUB_INSTALLATION_ID once and the backend can call GitHub
#   without requiring a user PAT.
GITHUB_APP_SLUG = os.getenv("GITHUB_APP_SLUG")  # e.g. "shiftleft-bot" (from https://github.com/apps/<slug>)
_inst = os.getenv("GITHUB_INSTALLATION_ID")
try:
    GITHUB_INSTALLATION_ID = int(_inst) if _inst else None
except Exception:
    GITHUB_INSTALLATION_ID = None

# Safety: basic protection for costly endpoints
SHIFTLEFT_API_KEY = os.getenv("SHIFTLEFT_API_KEY")  # used by webhook-triggered runs and/or clients

# Runner defaults
SHIFTLEFT_FIX_LIMIT = int(os.getenv("SHIFTLEFT_FIX_LIMIT", "5"))

# Webhook behavior
# - "validate": use cache only if it still matches current repo content; otherwise regenerate.
# - "refresh": always regenerate fixes (ignores cache).
SHIFTLEFT_WEBHOOK_MODE = os.getenv("SHIFTLEFT_WEBHOOK_MODE", "validate").lower()

# Auth (GitHub OAuth -> JWT for frontend)
AUTH_JWT_SECRET = os.getenv("AUTH_JWT_SECRET")  # required for account-based workspaces
AUTH_JWT_TTL_S = int(os.getenv("AUTH_JWT_TTL_S", "1209600"))  # 14 days

GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
GITHUB_OAUTH_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
FRONTEND_PUBLIC_URL = os.getenv("FRONTEND_PUBLIC_URL")  # e.g. https://your-frontend.onrender.com
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL")  # e.g. https://your-backend.onrender.com

