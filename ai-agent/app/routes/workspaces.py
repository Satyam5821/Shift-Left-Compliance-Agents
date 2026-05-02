import time
from typing import Any, Dict, List, Optional

from fastapi import Header, HTTPException

from ..core.config import SHIFTLEFT_API_KEY
from ..auth import get_user_from_auth_header


def _require_api_key(x_api_key: Optional[str]) -> None:
    if not SHIFTLEFT_API_KEY:
        # If not configured, keep endpoints closed by default in hosted mode.
        raise HTTPException(status_code=500, detail="SHIFTLEFT_API_KEY not configured")
    if not x_api_key or x_api_key != SHIFTLEFT_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _now_ms() -> int:
    return int(time.time() * 1000)


def register_workspace_routes(app, workspaces_collection):
    """
    Simple persistence for frontend workspaces (multi-project).
    Auth: X-API-Key header must equal SHIFTLEFT_API_KEY.
    Identity: X-Client-Id header (anonymous, generated in browser).
    """

    @app.get("/workspaces")
    def list_workspaces(
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
        x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        limit: int = 50,
    ) -> Dict[str, Any]:
        user = get_user_from_auth_header(authorization)
        if not user:
            _require_api_key(x_api_key)
            if not x_client_id:
                raise HTTPException(status_code=400, detail="Missing X-Client-Id")
        lim = max(1, min(int(limit or 50), 200))
        cur = (
            workspaces_collection.find(
                {"user_id": user["user_id"]} if user else {"client_id": x_client_id},
                {"_id": 0},
            )
            .sort("updated_at", -1)
            .limit(lim)
        )
        items: List[Dict[str, Any]] = [d for d in cur if isinstance(d, dict)]
        return {"ok": True, "count": len(items), "workspaces": items}

    @app.post("/workspaces")
    def upsert_workspace(
        body: Dict[str, Any],
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
        x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> Dict[str, Any]:
        user = get_user_from_auth_header(authorization)
        if not user:
            _require_api_key(x_api_key)
            if not x_client_id:
                raise HTTPException(status_code=400, detail="Missing X-Client-Id")

        wid = str(body.get("id") or "").strip()
        name = str(body.get("name") or "").strip()
        repo = str(body.get("repoFullName") or "").strip()
        inst = body.get("installationId")

        if not wid:
            raise HTTPException(status_code=400, detail="Missing workspace id")
        if not name:
            raise HTTPException(status_code=400, detail="Missing workspace name")
        if not repo or "/" not in repo:
            raise HTTPException(status_code=400, detail="Missing/invalid repoFullName")
        if not isinstance(inst, int) or inst <= 0:
            raise HTTPException(status_code=400, detail="Missing/invalid installationId")

        doc = {
            "client_id": None if user else x_client_id,
            "user_id": user["user_id"] if user else None,
            "id": wid,
            "name": name,
            "repoFullName": repo,
            "installationId": inst,
            "updated_at": _now_ms(),
            "created_at": int(body.get("createdAt") or _now_ms()),
        }
        workspaces_collection.update_one(
            ({"user_id": user["user_id"], "id": wid} if user else {"client_id": x_client_id, "id": wid}),
            {"$set": doc},
            upsert=True,
        )
        return {"ok": True, "workspace": doc}

    @app.delete("/workspaces/{workspace_id}")
    def delete_workspace(
        workspace_id: str,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
        x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> Dict[str, Any]:
        user = get_user_from_auth_header(authorization)
        if not user:
            _require_api_key(x_api_key)
            if not x_client_id:
                raise HTTPException(status_code=400, detail="Missing X-Client-Id")
        wid = (workspace_id or "").strip()
        if not wid:
            raise HTTPException(status_code=400, detail="Missing workspace id")
        r = workspaces_collection.delete_one(
            ({"user_id": user["user_id"], "id": wid} if user else {"client_id": x_client_id, "id": wid})
        )
        return {"ok": True, "deleted": int(getattr(r, "deleted_count", 0) or 0)}

