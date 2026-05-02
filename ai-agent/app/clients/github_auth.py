import time
from typing import Optional

from ..core.config import (
    GITHUB_APP_ID,
    GITHUB_APP_PRIVATE_KEY_PEM,
    GITHUB_INSTALLATION_ID,
    GITHUB_TOKEN,
)
from .github_app import get_installation_token

_cached_token: Optional[str] = None
_cached_until: int = 0


def get_github_api_token(installation_id: Optional[int] = None) -> Optional[str]:
    """
    Returns a GitHub API token.
    Preference order:
    1) GitHub App installation token (if app config + installation id are present)
    2) Legacy env PAT (GITHUB_TOKEN)
    """
    global _cached_token, _cached_until

    inst = installation_id if isinstance(installation_id, int) and installation_id > 0 else GITHUB_INSTALLATION_ID
    if (
        GITHUB_APP_ID
        and GITHUB_APP_PRIVATE_KEY_PEM
        and isinstance(inst, int)
        and inst > 0
    ):
        now = int(time.time())
        # Installation tokens expire; use a short cache to avoid re-minting on every request.
        if _cached_token and now < _cached_until and inst == GITHUB_INSTALLATION_ID:
            return _cached_token
        try:
            tok = get_installation_token(inst)
            if inst == GITHUB_INSTALLATION_ID:
                _cached_token = tok
                _cached_until = now + 8 * 60  # safe-ish (GitHub max is 1 hour)
            return tok
        except Exception:
            # Fall back to PAT if present
            return GITHUB_TOKEN

    return GITHUB_TOKEN

