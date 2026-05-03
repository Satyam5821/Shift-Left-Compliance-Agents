import time
from typing import Any, Dict, List, Optional

from fastapi import Header, HTTPException
from pymongo.collection import Collection

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


def _repos_from_workspace_doc(doc: Optional[Dict[str, Any]]) -> List[str]:
    if not doc or not isinstance(doc, dict):
        return []
    out: List[str] = []
    repos = doc.get("repos")
    if isinstance(repos, list):
        for x in repos:
            if isinstance(x, str) and "/" in x.strip():
                s = x.strip()
                if s not in out:
                    out.append(s)
    primary = doc.get("repoFullName")
    if isinstance(primary, str) and "/" in primary.strip():
        s = primary.strip()
        if s not in out:
            out.append(s)
    return out


def _purge_scans_for_repos(
    scans_collection: Collection,
    scan_issues_collection: Collection,
    scan_fix_attempts_collection: Collection,
    repos: List[str],
) -> int:
    """Delete scans and child rows for the given repo full names. Returns deleted scan count."""
    if not repos:
        return 0
    q = {"repo": {"$in": repos}}
    scan_docs = list(scans_collection.find(q, {"scan_id": 1}))
    scan_ids = [d["scan_id"] for d in scan_docs if isinstance(d, dict) and d.get("scan_id")]
    if scan_ids:
        scan_issues_collection.delete_many({"scan_id": {"$in": scan_ids}})
        scan_fix_attempts_collection.delete_many({"scan_id": {"$in": scan_ids}})
    r = scans_collection.delete_many(q)
    return int(getattr(r, "deleted_count", 0) or 0)


def register_workspace_routes(
    app,
    workspaces_collection: Collection,
    scans_collection: Collection,
    scan_issues_collection: Collection,
    scan_fix_attempts_collection: Collection,
):
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
        repo_single = str(body.get("repoFullName") or "").strip()
        inst = body.get("installationId")

        repos_in = body.get("repos")
        repo_list: List[str] = []
        if isinstance(repos_in, list):
            for x in repos_in:
                if isinstance(x, str) and "/" in x.strip():
                    repo_list.append(x.strip())
        if repo_single and "/" in repo_single:
            repo_list.append(repo_single)
        # de-dupe, stable order
        seen = set()
        repos_norm: List[str] = []
        for r in repo_list:
            if r not in seen:
                seen.add(r)
                repos_norm.append(r)

        if not wid:
            raise HTTPException(status_code=400, detail="Missing workspace id")
        if not name:
            raise HTTPException(status_code=400, detail="Missing workspace name")
        if not repos_norm:
            raise HTTPException(status_code=400, detail="Missing/invalid repos (need at least one owner/repo)")
        if not isinstance(inst, int) or inst <= 0:
            raise HTTPException(status_code=400, detail="Missing/invalid installationId")

        primary = repos_norm[0]

        doc = {
            "client_id": None if user else x_client_id,
            "user_id": user["user_id"] if user else None,
            "id": wid,
            "name": name,
            "repoFullName": primary,
            "repos": repos_norm,
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
        owner_q: Dict[str, Any] = {"user_id": user["user_id"], "id": wid} if user else {"client_id": x_client_id, "id": wid}
        doc = workspaces_collection.find_one(owner_q, {"_id": 0, "repos": 1, "repoFullName": 1})
        repos_in_ws = _repos_from_workspace_doc(doc if isinstance(doc, dict) else None)

        r = workspaces_collection.delete_one(owner_q)
        deleted = int(getattr(r, "deleted_count", 0) or 0)

        scans_removed = 0
        repos_purged: List[str] = []
        if deleted and repos_in_ws:
            user_filter: Dict[str, Any] = {"user_id": user["user_id"]} if user else {"client_id": x_client_id}
            others = list(workspaces_collection.find(user_filter, {"_id": 0, "repos": 1, "repoFullName": 1}))
            still_referenced: set = set()
            for w in others:
                for x in _repos_from_workspace_doc(w if isinstance(w, dict) else None):
                    still_referenced.add(x)
            repos_purged = [x for x in repos_in_ws if x not in still_referenced]
            if repos_purged:
                scans_removed = _purge_scans_for_repos(
                    scans_collection,
                    scan_issues_collection,
                    scan_fix_attempts_collection,
                    repos_purged,
                )

        return {
            "ok": True,
            "deleted": deleted,
            "scans_removed": scans_removed,
            "repos_purged": repos_purged,
        }

