import secrets
import time
from typing import Any, Dict, Optional

import requests
from fastapi import Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth import sign_user_token, get_user_from_auth_header
from ..core.config import (
    BACKEND_PUBLIC_URL,
    FRONTEND_PUBLIC_URL,
    GITHUB_OAUTH_CLIENT_ID,
    GITHUB_OAUTH_CLIENT_SECRET,
)


def _require_oauth_config() -> None:
    if not (GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET):
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
    if not FRONTEND_PUBLIC_URL:
        raise HTTPException(status_code=500, detail="FRONTEND_PUBLIC_URL not configured")
    if not BACKEND_PUBLIC_URL:
        raise HTTPException(status_code=500, detail="BACKEND_PUBLIC_URL not configured")


def register_auth_routes(app, users_collection):
    @app.get("/auth/github/login")
    def github_login(state: Optional[str] = None):
        """
        Redirect to GitHub OAuth authorize.
        """
        _require_oauth_config()
        st = state or secrets.token_urlsafe(16)
        url = (
            "https://github.com/login/oauth/authorize"
            f"?client_id={GITHUB_OAUTH_CLIENT_ID}"
            f"&redirect_uri={requests.utils.quote(_callback_url(), safe='')}"
            f"&scope=read:user"
            f"&state={st}"
        )
        return RedirectResponse(url=url, status_code=302)

    @app.get("/auth/github/callback")
    def github_callback(code: Optional[str] = None, state: Optional[str] = None):
        """
        Exchange code -> user identity, then redirect to frontend with token.
        """
        _require_oauth_config()
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")

        tok = _exchange_code_for_token(code)
        user = _fetch_github_user(tok)
        login = str(user.get("login") or "")
        gh_id = str(user.get("id") or "")
        if not login or not gh_id:
            raise HTTPException(status_code=400, detail="Unable to identify GitHub user")

        # Upsert user record (no OAuth token stored; GitHub App handles repo access)
        doc = {
            "provider": "github",
            "provider_user_id": gh_id,
            "login": login,
            "updated_at": int(time.time()),
        }
        users_collection.update_one(
            {"provider": "github", "provider_user_id": gh_id},
            {"$set": doc},
            upsert=True,
        )
        rec = users_collection.find_one({"provider": "github", "provider_user_id": gh_id}, {"_id": 0}) or doc
        user_id = f"github:{gh_id}"

        jwt_tok = sign_user_token(user_id=user_id, login=login)
        # Redirect back to frontend with token in URL hash (not sent to server logs)
        redir = f"{FRONTEND_PUBLIC_URL.rstrip('/')}/#auth=1&token={jwt_tok}"
        return RedirectResponse(url=redir, status_code=302)

    @app.get("/me")
    def me(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Dict[str, Any]:
        user = get_user_from_auth_header(authorization)
        if not user:
            return {"ok": True, "authenticated": False}
        return {"ok": True, "authenticated": True, "user": {"id": user["user_id"], "login": user.get("login")}}


def _callback_url() -> str:
    return f"{str(BACKEND_PUBLIC_URL).rstrip('/')}/auth/github/callback"


def _exchange_code_for_token(code: str) -> str:
    r = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_OAUTH_CLIENT_ID,
            "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
            "code": code,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json() if isinstance(r.json(), dict) else {}
    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="OAuth exchange failed")
    return str(access_token)


def _fetch_github_user(access_token: str) -> Dict[str, Any]:
    r = requests.get(
        "https://api.github.com/user",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}

