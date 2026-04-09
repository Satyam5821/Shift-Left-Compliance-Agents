from datetime import datetime

from ..clients.sonar import fetch_sonar_issues


def register_issue_routes(app, issues_collection):
    @app.get("/issues")
    def get_issues():
        sonar_issues = fetch_sonar_issues()
        issues = []

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
            }

            issues_collection.update_one(
                {"key": issue_data["key"]},
                {"$set": issue_data},
                upsert=True,
            )

            issues.append(issue_data)

        return {"issues": issues}

