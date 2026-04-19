import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import requests

from ..core.config import GITHUB_TOKEN


_PR_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?$")


def _parse_pr_url(pr_url: str) -> Optional[Tuple[str, str, int]]:
    m = _PR_RE.match((pr_url or "").strip())
    if not m:
        return None
    owner, repo, num = m.group(1), m.group(2), int(m.group(3))
    return owner, repo, num


def _gh_headers(token: str) -> Dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _refresh_pr_status_if_needed(scans_collection, scan_doc: Dict[str, Any], ttl_s: int = 3600) -> Dict[str, Any]:
    pr_url = scan_doc.get("pr")
    if not isinstance(pr_url, str) or not pr_url:
        return scan_doc

    parsed = _parse_pr_url(pr_url)
    if not parsed:
        return scan_doc

    if not GITHUB_TOKEN:
        # Can't resolve merge state without a token.
        scan_doc.setdefault("pr_number", parsed[2])
        scan_doc.setdefault("pr_merged", None)
        return scan_doc

    now = int(time.time())
    checked_at = scan_doc.get("pr_checked_at")
    if isinstance(checked_at, int) and (now - checked_at) < max(30, ttl_s):
        return scan_doc

    owner, repo, num = parsed
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{num}"
        r = requests.get(url, headers=_gh_headers(GITHUB_TOKEN), timeout=15)
        if r.status_code == 404:
            scan_doc.update(
                {
                    "pr_number": num,
                    "pr_state": "missing",
                    "pr_merged": False,
                    "pr_checked_at": now,
                }
            )
        else:
            r.raise_for_status()
            data = r.json() if isinstance(r.json(), dict) else {}
            merged_at = data.get("merged_at")
            state = data.get("state")
            scan_doc.update(
                {
                    "pr_number": num,
                    "pr_state": state,
                    "pr_merged": bool(merged_at),
                    "pr_merged_at": merged_at,
                    "pr_checked_at": now,
                }
            )
    except Exception:
        scan_doc.update({"pr_number": num, "pr_checked_at": now})

    try:
        scans_collection.update_one({"scan_id": scan_doc.get("scan_id")}, {"$set": scan_doc})
    except Exception:
        pass
    return scan_doc


def register_scan_routes(app, scans_collection, scan_issues_collection, scan_fix_attempts_collection):
    def _range_to_since(range_key: str) -> Optional[datetime]:
        key = (range_key or "").strip().lower()
        now = datetime.utcnow()
        if key in ("24h", "1d", "day"):
            return now.replace(microsecond=0) - timedelta(hours=24)
        if key in ("7d", "week"):
            return now.replace(microsecond=0) - timedelta(days=7)
        if key in ("14d", "2w"):
            return now.replace(microsecond=0) - timedelta(days=14)
        if key in ("30d", "month"):
            return now.replace(microsecond=0) - timedelta(days=30)
        return None

    @app.get("/scans/scan-wise")
    def scan_wise(range: str = "7d", limit: int = 100):
        # Commit-wise analytics: each scan ~= one workflow run / commit window.
        since = _range_to_since(range)
        q: Dict[str, Any] = {}
        if since is not None:
            q["created_at"] = {"$gte": since}

        docs = list(
            scans_collection.find(q, {"_id": 0})
            .sort("created_at", -1)
            .limit(max(1, min(limit, 500)))
        )

        scans_out = []
        for d in docs:
            if isinstance(d, dict):
                scans_out.append(_refresh_pr_status_if_needed(scans_collection, d))

        applied = 0
        skipped = 0
        errors = 0
        prs_created = 0
        prs_merged = 0

        for d in scans_out:
            c = (d.get("apply_counters") or {}) if isinstance(d.get("apply_counters"), dict) else {}
            applied += int(c.get("applied") or 0)
            skipped += int(c.get("skipped") or 0)
            errors += int(c.get("errors") or 0)
            if d.get("pr"):
                prs_created += 1
            if d.get("pr_merged") is True:
                prs_merged += 1

        total_attempted = applied + skipped + errors
        success_rate = (applied / total_attempted) if total_attempted > 0 else None

        return {
            "ok": True,
            "range": range,
            "since": since,
            "stats": {
                "scan_count": len(scans_out),
                "applied_total": applied,
                "skipped_total": skipped,
                "errors_total": errors,
                "prs_created": prs_created,
                "prs_merged": prs_merged,
                "success_rate": success_rate,
            },
            "scans": scans_out,
        }

    @app.get("/scans/stats")
    def scan_stats(limit: int = 200):
        docs = list(
            scans_collection.find({}, {"_id": 0})
            .sort("created_at", -1)
            .limit(max(1, min(limit, 500)))
        )

        refreshed = []
        for d in docs:
            if isinstance(d, dict):
                refreshed.append(_refresh_pr_status_if_needed(scans_collection, d))

        applied = 0
        skipped = 0
        errors = 0
        prs_created = 0
        prs_merged = 0
        last_scan_at = None

        for d in refreshed:
            if not isinstance(d, dict):
                continue
            c = (d.get("apply_counters") or {}) if isinstance(d.get("apply_counters"), dict) else {}
            applied += int(c.get("applied") or 0)
            skipped += int(c.get("skipped") or 0)
            errors += int(c.get("errors") or 0)
            if d.get("pr"):
                prs_created += 1
            if d.get("pr_merged") is True:
                prs_merged += 1
            if not last_scan_at and d.get("created_at"):
                last_scan_at = d.get("created_at")

        return {
            "ok": True,
            "stats": {
                "scan_count": len(refreshed),
                "issues_resolved": applied,
                "applied_total": applied,
                "skipped_total": skipped,
                "errors_total": errors,
                "prs_created": prs_created,
                "prs_merged": prs_merged,
                "last_scan_at": last_scan_at,
            },
        }

    @app.get("/scans")
    def list_scans(limit: int = 20):
        docs = list(
            scans_collection.find({}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 200)))
        )
        out = []
        for d in docs:
            if isinstance(d, dict):
                out.append(_refresh_pr_status_if_needed(scans_collection, d))
            else:
                out.append(d)
        return {"scans": out, "count": len(out)}

    @app.get("/scans/latest")
    def latest_scan():
        doc = scans_collection.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
        if not doc:
            return {"ok": False, "error": "No scans found"}
        return {"ok": True, "scan": doc}

    # scan_id looks like "owner/repo:sha8:workflow_run_id" — contains "/" before ":".
    # Starlette's default {scan_id} only matches ONE path segment; use :path so the
    # full id is captured (e.g. GET /scans/Org/foo:abc123:999 without encoding %2F).
    @app.get("/scans/{scan_id:path}")
    def get_scan(scan_id: str):
        scan = scans_collection.find_one({"scan_id": scan_id}, {"_id": 0})
        if not scan:
            return {"ok": False, "error": "Scan not found", "scan_id": scan_id}
        if isinstance(scan, dict):
            scan = _refresh_pr_status_if_needed(scans_collection, scan)

        issues = list(scan_issues_collection.find({"scan_id": scan_id}, {"_id": 0}))
        fixes = list(scan_fix_attempts_collection.find({"scan_id": scan_id}, {"_id": 0}))
        return {"ok": True, "scan": scan, "issues": issues, "fix_attempts": fixes}

