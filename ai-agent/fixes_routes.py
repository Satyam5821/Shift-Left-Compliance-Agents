import json
from datetime import datetime

from fastapi import Query

from fixes_service import generate_fix_for_issue
from sonar_client import fetch_sonar_issues


def register_fix_routes(app, fixes_collection, prompts_collection):
    @app.get("/fixes")
    def get_fixes(limit: int = Query(5, ge=1, le=20), refresh: bool = False):
        sonar_issues = fetch_sonar_issues()
        results = []

        def to_fix_string_from_legacy(fix_data):
            if isinstance(fix_data, str):
                return fix_data
            if isinstance(fix_data, (dict, list)):
                return json.dumps(fix_data, ensure_ascii=False, indent=2)
            return str(fix_data)

        for issue in sonar_issues[:limit]:
            issue_key = issue.get("key")

            cached = None
            if issue_key and not refresh:
                cached = fixes_collection.find_one({"issue_key": issue_key}, {"_id": 0})

            # Serve cache if possible
            if cached and cached.get("fix"):
                cached_fix = cached.get("fix")
                cached_raw = cached.get("fix_raw") or cached_fix
                cached_json = cached.get("fix_json")

                # Backfill missing json/raw for old rows
                if cached_json is None:
                    # Wrap into a stable shape (no extra LLM call here)
                    parsed = None
                    if isinstance(cached_raw, str):
                        try:
                            parsed = json.loads(cached_raw)
                        except Exception:
                            parsed = None
                    if isinstance(parsed, dict):
                        cached_json = parsed
                        cached_json.setdefault("problem", issue.get("message") or "Sonar issue")
                        cached_json.setdefault("solution", "")
                        cached_json.setdefault("code_changes", [])
                    else:
                        cached_json = {
                            "problem": issue.get("message") or "Sonar issue",
                            "solution": cached_raw if isinstance(cached_raw, str) else str(cached_raw),
                            "code_changes": [],
                        }
                    fixes_collection.update_one(
                        {"issue_key": issue_key},
                        {
                            "$set": {
                                "fix_raw": cached_raw,
                                "fix_json": cached_json,
                                "fix": json.dumps(cached_json, ensure_ascii=False, indent=2),
                                "updated_at": datetime.now(),
                            }
                        },
                    )
                    cached_fix = json.dumps(cached_json, ensure_ascii=False, indent=2)

                if cached.get("fix_raw") is None:
                    fixes_collection.update_one(
                        {"issue_key": issue_key},
                        {"$set": {"fix_raw": cached_raw, "updated_at": datetime.now()}},
                    )

                results.append(
                    {
                        "issue": {
                            "key": issue_key,
                            "message": issue.get("message"),
                            "severity": issue.get("severity"),
                            "file": issue.get("component"),
                            "line": issue.get("line"),
                        },
                        "fix": cached_fix,
                        "fix_raw": cached_raw,
                        "fix_json": cached_json,
                        "source": "cache",
                    }
                )
                continue

            # Migrate legacy field if present (old records stored fix_data)
            if cached and cached.get("fix_data") is not None and issue_key and not refresh:
                fix_string = to_fix_string_from_legacy(cached.get("fix_data"))
                fixes_collection.update_one(
                    {"issue_key": issue_key},
                    {
                        "$set": {
                            "fix": fix_string,
                            "fix_raw": cached.get("fix_raw")
                            or (cached.get("fix_data") if isinstance(cached.get("fix_data"), str) else None),
                            "fix_json": cached.get("fix_json")
                            or (cached.get("fix_data") if isinstance(cached.get("fix_data"), (dict, list)) else None),
                            "updated_at": datetime.now(),
                        }
                    },
                )
                results.append(
                    {
                        "issue": {
                            "key": issue_key,
                            "message": issue.get("message"),
                            "severity": issue.get("severity"),
                            "file": issue.get("component"),
                            "line": issue.get("line"),
                        },
                        "fix": fix_string,
                        "fix_raw": cached.get("fix_raw"),
                        "fix_json": cached.get("fix_json"),
                        "source": "cache",
                    }
                )
                continue

            # Generate new fix (uses GitHub-only context)
            gen = generate_fix_for_issue(issue, prompts_collection)
            fix_text = gen["fix_text"]
            fix_json = gen["fix_json"]
            fix_string = gen["fix_string"]

            fix_record = {
                "issue_key": issue_key,
                "issue_rule": issue.get("rule"),
                "fix": fix_string,
                "fix_raw": fix_text,
                "fix_json": fix_json,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }

            if issue_key:
                fixes_collection.update_one(
                    {"issue_key": issue_key},
                    {"$set": fix_record},
                    upsert=True,
                )

            results.append(
                {
                    "issue": {
                        "key": issue_key,
                        "message": issue.get("message"),
                        "severity": issue.get("severity"),
                        "file": issue.get("component"),
                        "line": issue.get("line"),
                    },
                    "fix": fix_string,
                    "fix_raw": fix_text,
                    "fix_json": fix_json,
                    "source": "generated",
                }
            )

        return {"results": results}

