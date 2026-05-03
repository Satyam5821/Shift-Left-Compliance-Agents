from datetime import datetime
from typing import Optional

from fastapi import Query

from ..clients.sonar import fetch_sonar_issues, resolve_sonar_component_key


def register_issue_routes(app, issues_collection):
    @app.get("/issues")
    def get_issues(
        repo: Optional[str] = Query(None, description="GitHub full name, e.g. owner/repo"),
        sonarProjectKey: Optional[str] = Query(None, alias="sonarProjectKey"),
    ):
        component_key = resolve_sonar_component_key(repo=repo, explicit_project_key=sonarProjectKey)
        if not component_key:
            return {"issues": [], "sonarProjectKey": None, "error": "No Sonar project key (set SONAR_PROJECT_KEY or pass sonarProjectKey)"}

        sonar_issues = fetch_sonar_issues(component_key)
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
