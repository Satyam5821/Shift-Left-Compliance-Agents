from datetime import datetime
from typing import Any, Dict, Optional


def register_scan_routes(app, scans_collection, scan_issues_collection, scan_fix_attempts_collection):
    @app.get("/scans")
    def list_scans(limit: int = 20):
        docs = list(
            scans_collection.find({}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 200)))
        )
        return {"scans": docs, "count": len(docs)}

    @app.get("/scans/latest")
    def latest_scan():
        doc = scans_collection.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
        if not doc:
            return {"ok": False, "error": "No scans found"}
        return {"ok": True, "scan": doc}

    @app.get("/scans/{scan_id}")
    def get_scan(scan_id: str):
        scan = scans_collection.find_one({"scan_id": scan_id}, {"_id": 0})
        if not scan:
            return {"ok": False, "error": "Scan not found", "scan_id": scan_id}

        issues = list(scan_issues_collection.find({"scan_id": scan_id}, {"_id": 0}))
        fixes = list(scan_fix_attempts_collection.find({"scan_id": scan_id}, {"_id": 0}))
        return {"ok": True, "scan": scan, "issues": issues, "fix_attempts": fixes}

