from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from ..core.config import SONAR_TOKEN_ENC_KEY


def _get_fernet() -> Fernet:
    """
    Server-side encryption helper.

    SONAR_TOKEN_ENC_KEY must be a urlsafe base64-encoded 32-byte key (Fernet key).
    Generate one locally:
      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    if not SONAR_TOKEN_ENC_KEY or not str(SONAR_TOKEN_ENC_KEY).strip():
        raise HTTPException(status_code=500, detail="SONAR_TOKEN_ENC_KEY not configured")
    try:
        return Fernet(str(SONAR_TOKEN_ENC_KEY).strip().encode("utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid SONAR_TOKEN_ENC_KEY")


def encrypt_sonar_token(token: str) -> str:
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(status_code=400, detail="Missing Sonar token")
    f = _get_fernet()
    return f.encrypt(token.strip().encode("utf-8")).decode("utf-8")


def decrypt_sonar_token(token_enc: str) -> Optional[str]:
    if not token_enc or not isinstance(token_enc, str):
        return None
    f = _get_fernet()
    try:
        return f.decrypt(token_enc.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None
    except Exception:
        return None

