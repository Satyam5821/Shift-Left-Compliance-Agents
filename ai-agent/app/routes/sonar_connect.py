from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException
from pymongo.collection import Collection

from ..auth import require_user
from ..services.sonar_secrets import decrypt_sonar_token, encrypt_sonar_token


def _now_ms() -> int:
    return int(time.time() * 1000)


def register_sonar_connect_routes(app, sonar_connections_collection: Collection):
    @app.get("/sonar/status")
    def sonar_status(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Dict[str, Any]:
        user = require_user(authorization)
        doc = sonar_connections_collection.find_one({"user_id": user["user_id"]}, {"_id": 0, "token_enc": 1, "updated_at": 1})
        token_ok = False
        if isinstance(doc, dict) and doc.get("token_enc"):
            token_ok = bool(decrypt_sonar_token(str(doc.get("token_enc") or "")))
        return {"ok": True, "connected": token_ok, "updated_at": doc.get("updated_at") if isinstance(doc, dict) else None}

    @app.post("/sonar/connect")
    def sonar_connect(
        body: Dict[str, Any],
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> Dict[str, Any]:
        user = require_user(authorization)
        token = body.get("token")
        if not isinstance(token, str) or not token.strip():
            raise HTTPException(status_code=400, detail="Missing token")
        token_enc = encrypt_sonar_token(token)
        doc = {"user_id": user["user_id"], "token_enc": token_enc, "updated_at": _now_ms(), "created_at": _now_ms()}
        sonar_connections_collection.update_one({"user_id": user["user_id"]}, {"$set": doc, "$setOnInsert": {"created_at": doc["created_at"]}}, upsert=True)
        return {"ok": True, "connected": True}

    @app.delete("/sonar/connect")
    def sonar_disconnect(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Dict[str, Any]:
        user = require_user(authorization)
        sonar_connections_collection.delete_one({"user_id": user["user_id"]})
        return {"ok": True, "connected": False}

