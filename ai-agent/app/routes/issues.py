from datetime import datetime
from typing import Optional

from fastapi import Header, Query

from ..auth import get_user_from_auth_header
from ..clients.sonar import fetch_sonar_issues, resolve_sonar_component_key
from ..services.sonar_secrets import decrypt_sonar_token


def register_issue_routes(app, issues_collection, sonar_connections_collection=None, workspaces_collection=None):
    @app.get("/issues")
    def get_issues(
        repo: Optional[str] = Query(None, description="GitHub full name, e.g. owner/repo"),
        sonarProjectKey: Optional[str] = Query(None, alias="sonarProjectKey"),
        workspaceId: Optional[str] = Query(None, alias="workspaceId"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ):
        component_key = resolve_sonar_component_key(repo=repo, explicit_project_key=sonarProjectKey)
        if not component_key:
            return {"issues": [], "sonarProjectKey": None, "error": "No Sonar project key (set SONAR_PROJECT_KEY or pass sonarProjectKey)"}

        token_override = None
        user = get_user_from_auth_header(authorization)
        if user:
            # Prefer workspace-scoped token (per project), fallback to user token.
            if workspaceId and workspaces_collection is not None:
                ws = workspaces_collection.find_one(
                    {"user_id": user["user_id"], "id": str(workspaceId).strip()},
                    {"_id": 0, "sonar_token_enc": 1},
                )
                if isinstance(ws, dict) and ws.get("sonar_token_enc"):
                    token_override = decrypt_sonar_token(str(ws.get("sonar_token_enc") or "")) or None

            if token_override is None and sonar_connections_collection is not None:
                doc = sonar_connections_collection.find_one({"user_id": user["user_id"]}, {"_id": 0, "token_enc": 1})
                if isinstance(doc, dict) and doc.get("token_enc"):
                    token_override = decrypt_sonar_token(str(doc.get("token_enc") or "")) or None

        sonar_issues = fetch_sonar_issues(component_key, token_override=token_override)
        issues = []
        seen_keys = []

        for issue in sonar_issues:
            issue_data = {
                "key": issue.get("key"),
                "rule": issue.get("rule"),
                "severity": issue.get("severity"),
                "message": issue.get("message"),
                "file": issue.get("component"),
                "line": issue.get("line"),
                "status": "open",
                "component_key": component_key,
                "repo": repo.strip() if repo and str(repo).strip() else None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }

            k = issue_data["key"]
            if not k:
                continue
            seen_keys.append(k)

            issues_collection.update_one(
                {"key": k},
                {"$set": issue_data},
                upsert=True,
            )

            issues.append(issue_data)

        # Mark issues that no longer appear in Sonar as closed (scoped to this Sonar project)
        if seen_keys:
            issues_collection.update_many(
                {"key": {"$nin": seen_keys}, "status": "open", "component_key": component_key},
                {"$set": {"status": "closed", "updated_at": datetime.now()}},
            )

        return {"issues": issues, "sonarProjectKey": component_key}
