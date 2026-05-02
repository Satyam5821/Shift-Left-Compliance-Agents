import time
from typing import Any, Dict, Optional

import jwt
from fastapi import Header, HTTPException

from .core.config import AUTH_JWT_SECRET, AUTH_JWT_TTL_S


def _require_jwt_secret() -> str:
    if not AUTH_JWT_SECRET:
        raise HTTPException(status_code=500, detail="AUTH_JWT_SECRET not configured")
    return str(AUTH_JWT_SECRET)


def sign_user_token(user_id: str, login: str) -> str:
    secret = _require_jwt_secret()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "login": str(login),
        "iat": now,
        "exp": now + int(AUTH_JWT_TTL_S),
        "typ": "slca_user",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_user_token(token: str) -> Dict[str, Any]:
    secret = _require_jwt_secret()
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not isinstance(data, dict) or data.get("typ") != "slca_user":
        raise HTTPException(status_code=401, detail="Invalid token")
    return data


def get_user_from_auth_header(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization or not isinstance(authorization, str):
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    tok = parts[1].strip()
    if not tok:
        return None
    data = verify_user_token(tok)
    uid = str(data.get("sub") or "")
    login = str(data.get("login") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user_id": uid, "login": login}


def require_user(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Dict[str, Any]:
    user = get_user_from_auth_header(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Missing Authorization")
    return user

