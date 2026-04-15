from datetime import datetime

from ..clients.sonar import fetch_sonar_issues


def register_issue_routes(app, issues_collection):
    @app.get("/issues")
    def get_issues():
        sonar_issues = fetch_sonar_issues()
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
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }

            if issue_data["key"]:
                seen_keys.append(issue_data["key"])

            issues_collection.update_one(
                {"key": issue_data["key"]},
                {"$set": issue_data},
                upsert=True,
            )

            issues.append(issue_data)

        # Mark issues that no longer appear in Sonar as closed (keeps history, avoids stale "open" items)
        if seen_keys:
            issues_collection.update_many(
                {"key": {"$nin": seen_keys}, "status": "open"},
                {"$set": {"status": "closed", "updated_at": datetime.now()}},
            )

        return {"issues": issues}

