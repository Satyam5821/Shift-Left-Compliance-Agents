import os

from dotenv import load_dotenv


load_dotenv()


SONAR_TOKEN = os.getenv("SONAR_TOKEN")
SONAR_PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")
SONAR_VERIFY = os.getenv("SONAR_VERIFY", "true").lower() not in ("false", "0", "no")

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

# Safety: basic protection for costly endpoints
SHIFTLEFT_API_KEY = os.getenv("SHIFTLEFT_API_KEY")  # used by webhook-triggered runs and/or clients

# Runner defaults
SHIFTLEFT_FIX_LIMIT = int(os.getenv("SHIFTLEFT_FIX_LIMIT", "5"))

# Webhook behavior
# - "validate": use cache only if it still matches current repo content; otherwise regenerate.
# - "refresh": always regenerate fixes (ignores cache).
SHIFTLEFT_WEBHOOK_MODE = os.getenv("SHIFTLEFT_WEBHOOK_MODE", "validate").lower()

