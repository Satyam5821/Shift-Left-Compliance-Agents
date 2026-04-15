import hmac
import json
import time
from datetime import datetime
from hashlib import sha256
from typing import Any, Dict, Optional, List

from fastapi import Header, HTTPException, Request

from ..clients.github_app import (
    GitHubRef,
    create_branch,
    create_pull_request,
    find_open_pull_request,
    get_file_content,
    get_installation_token,
)
from ..clients.sonar import fetch_sonar_issues
from ..core.config import GITHUB_WEBHOOK_SECRET, SHIFTLEFT_FIX_LIMIT, SHIFTLEFT_WEBHOOK_MODE
from ..services.fixes_service import generate_fix_for_issue
from ..services.github_apply import apply_code_changes_via_github_api


def _verify_sig(body: bytes, sig_header: Optional[str]) -> None:
    if not GITHUB_WEBHOOK_SECRET:
        # If no secret configured, do not allow webhook in production accidentally
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    if not sig_header or not isinstance(sig_header, str) or not sig_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing signature")

    expected = hmac.new(GITHUB_WEBHOOK_SECRET.encode("utf-8"), body, sha256).hexdigest()
    got = sig_header.split("=", 1)[1].strip()
    if not hmac.compare_digest(expected, got):
        raise HTTPException(status_code=401, detail="Bad signature")


def _extract_workflow_run(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    wr = payload.get("workflow_run")
    if isinstance(wr, dict):
        return wr
    return None


def _normalize_path(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("/")


def _is_cached_fix_valid(repo: GitHubRef, token: str, base_ref: str, fix_json: Dict[str, Any]) -> bool:
    """
    Cheap validation to prevent applying stale/unsafe cached fixes.
    Validates only:
    - replace/delete must have old_code present in current file at base_ref
    - insert_* must have old_code anchor present (if provided)
    - move requires source exists at base_ref
    If something is missing, treat as invalid → regenerate.
    """
    changes = fix_json.get("code_changes")
    if not isinstance(changes, list):
        return False

    for ch in changes:
        if not isinstance(ch, dict):
            return False
        op = ch.get("op")

        if op == "move":
            src = _normalize_path(str(ch.get("from") or ""))
            if not src:
                return False
            src_text, _ = get_file_content(repo, token, src, ref=base_ref)
            if src_text is None:
                return False
            continue

        path = _normalize_path(str(ch.get("file") or ""))
        if not path:
            return False

        text, _ = get_file_content(repo, token, path, ref=base_ref)
        if text is None:
            return False

        old_code = ch.get("old_code") if isinstance(ch.get("old_code"), str) and ch.get("old_code") else ""

        if op in ("replace", "delete"):
            if old_code and old_code not in text:
                return False
        elif op in ("insert_before", "insert_after"):
            # If there's an anchor, it must exist; otherwise line-based insert is considered unsafe
            if not old_code:
                return False
            if old_code not in text:
                return False
        else:
            # Unknown op -> invalidate cache
            return False

    return True


def register_webhook_routes(app, fixes_collection, prompts_collection, scans_collection=None, scan_issues_collection=None, scan_fix_attempts_collection=None):
    @app.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
        x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    ):
        body = await request.body()
        _verify_sig(body, x_hub_signature_256)

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        # We recommend webhook event = workflow_run (Sonar workflow completion)
        if x_github_event != "workflow_run":
            return {"ok": True, "ignored": True, "reason": f"event {x_github_event} not handled"}

        workflow_run = _extract_workflow_run(payload)
        if not workflow_run:
            raise HTTPException(status_code=400, detail="Missing workflow_run payload")

        if workflow_run.get("conclusion") != "success":
            return {"ok": True, "ignored": True, "reason": "workflow_run not successful"}

        # Only run auto-fix PR after successful push-to-main analysis.
        # If we run on PR analyses, we can create PR-on-PR loops and also fail when Sonar PR binding is missing.
        if workflow_run.get("event") != "push":
            return {
                "ok": True,
                "ignored": True,
                "reason": f"workflow_run event is {workflow_run.get('event')}, only 'push' is handled",
            }

        if workflow_run.get("head_branch") != "main":
            return {
                "ok": True,
                "ignored": True,
                "reason": f"workflow_run head_branch is {workflow_run.get('head_branch')}, only 'main' is handled",
            }

        repo_obj = (payload.get("repository") or {}) if isinstance(payload.get("repository"), dict) else {}
        full_name = repo_obj.get("full_name") or ""
        if "/" not in full_name:
            raise HTTPException(status_code=400, detail="Missing repository.full_name")
        owner, repo_name = full_name.split("/", 1)
        repo = GitHubRef(owner=owner, repo=repo_name)

        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            raise HTTPException(status_code=400, detail="Missing installation.id")

        token = get_installation_token(installation_id)

        base_branch = "main"
        # Use a unique branch name per run to avoid PR/branch collisions
        sha8 = (workflow_run.get("head_sha", "") or "")[:8] or "latest"
        run_id = str(workflow_run.get("id") or int(time.time()))
        head_branch = f"shiftleft/fixes-{sha8}-{run_id}"
        create_branch(repo, token, new_branch=head_branch, base_branch=base_branch)

        sonar_issues = fetch_sonar_issues()
        fixes_payload: Dict[str, Any] = {"results": []}

        mode = SHIFTLEFT_WEBHOOK_MODE or "validate"

        scan_id = f"{owner}/{repo_name}:{sha8}:{run_id}"
        created_at = time.time()

        # Generate fixes (cache-first, but validate or refresh depending on mode)
        for issue in (sonar_issues or [])[:SHIFTLEFT_FIX_LIMIT]:
            issue_key = issue.get("key")
            cached = fixes_collection.find_one({"issue_key": issue_key}, {"_id": 0}) if issue_key else None
            if mode != "refresh" and cached and cached.get("fix_json") and isinstance(cached.get("fix_json"), dict):
                fix_json = cached.get("fix_json")
                if mode == "validate":
                    if _is_cached_fix_valid(repo, token, base_branch, fix_json):
                        fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "cache"})
                        continue
                else:
                    # unknown mode -> treat as cache-first
                    fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "cache"})
                    continue

            gen = generate_fix_for_issue(issue, prompts_collection)
            fix_json = gen.get("fix_json")
            fix_record = {
                "issue_key": issue_key,
                "issue_rule": issue.get("rule"),
                "fix": gen.get("fix_string"),
                "fix_raw": gen.get("fix_text"),
                "fix_json": fix_json,
            }
            if issue_key:
                fixes_collection.update_one({"issue_key": issue_key}, {"$set": fix_record}, upsert=True)
            fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "generated"})

        # Persist scan snapshot (best effort)
        try:
            if scans_collection is not None:
                counts: Dict[str, int] = {}
                for it in (sonar_issues or []):
                    sev = str(it.get("severity") or "UNKNOWN")
                    counts[sev] = counts.get(sev, 0) + 1

                scans_collection.update_one(
                    {"scan_id": scan_id},
                    {
                        "$set": {
                            "scan_id": scan_id,
                            "repo": f"{owner}/{repo_name}",
                            "base_branch": base_branch,
                            "head_sha": workflow_run.get("head_sha"),
                            "workflow_run_id": workflow_run.get("id"),
                            "webhook_mode": mode,
                            "fix_limit": SHIFTLEFT_FIX_LIMIT,
                            "issue_counts": counts,
                            "total_issues": len(sonar_issues or []),
                            "created_at": datetime.utcnow(),
                        }
                    },
                    upsert=True,
                )

                if scan_issues_collection is not None:
                    # Replace scan issues for this scan_id
                    scan_issues_collection.delete_many({"scan_id": scan_id})
                    if sonar_issues:
                        scan_issues_collection.insert_many(
                            [
                                {
                                    "scan_id": scan_id,
                                    "issue_key": i.get("key"),
                                    "rule": i.get("rule"),
                                    "severity": i.get("severity"),
                                    "message": i.get("message"),
                                    "file": i.get("component"),
                                    "line": i.get("line"),
                                }
                                for i in sonar_issues
                            ],
                            ordered=False,
                        )
        except Exception:
            pass

        # Flatten all changes
        all_changes = []
        for item in fixes_payload["results"]:
            fj = item.get("fix_json") or {}
            if isinstance(fj, dict) and isinstance(fj.get("code_changes"), list):
                all_changes.extend(list(fj.get("code_changes") or []))

        counters, report = apply_code_changes_via_github_api(
            repo=repo,
            token=token,
            base_ref=base_branch,
            branch=head_branch,
            code_changes=all_changes,
        )

        if counters.applied == 0 and counters.errors == 0:
            # Nothing to change; don't open a PR.
            try:
                if scans_collection is not None:
                    scans_collection.update_one(
                        {"scan_id": scan_id},
                        {"$set": {"apply_counters": counters.__dict__, "pr": None, "updated_at": datetime.utcnow()}},
                        upsert=True,
                    )
            except Exception:
                pass
            return {
                "ok": True,
                "branch": head_branch,
                "pr": None,
                "counters": counters.__dict__,
                "note": "No applicable code changes; PR not created.",
            }

        pr_title = "chore(shiftleft): auto fixes"
        pr_body = (
            "## Shift-Left automated fixes\n\n"
            + f"- Applied: {counters.applied}\n"
            + f"- Skipped: {counters.skipped}\n"
            + f"- Errors: {counters.errors}\n\n"
            + "## Report\n"
            + "```json\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + "\n```\n"
        )

        # If PR already exists (or GitHub returns 422), return existing PR instead of 500.
        existing = find_open_pull_request(repo, token, head=head_branch, base=base_branch)
        if existing and existing.get("html_url"):
            pr_url = existing.get("html_url")
            try:
                if scans_collection is not None:
                    scans_collection.update_one(
                        {"scan_id": scan_id},
                        {"$set": {"apply_counters": counters.__dict__, "pr": pr_url, "updated_at": datetime.utcnow()}},
                        upsert=True,
                    )
                if scan_fix_attempts_collection is not None:
                    scan_fix_attempts_collection.delete_many({"scan_id": scan_id})
                    scan_fix_attempts_collection.insert_many(
                        [
                            {
                                "scan_id": scan_id,
                                "issue_key": (it.get("issue") or {}).get("key"),
                                "source": it.get("source"),
                                "fix_json": it.get("fix_json"),
                            }
                            for it in (fixes_payload.get("results") or [])
                        ],
                        ordered=False,
                    )
            except Exception:
                pass
            return {"ok": True, "branch": head_branch, "pr": existing.get("html_url"), "counters": counters.__dict__}

        try:
            pr = create_pull_request(
                repo=repo,
                token=token,
                title=pr_title,
                body=pr_body,
                head=head_branch,
                base=base_branch,
            )
            pr_url = pr.get("html_url")
        except Exception:
            # Try to recover from "Validation Failed" (422) by looking up an existing PR.
            existing2 = find_open_pull_request(repo, token, head=head_branch, base=base_branch)
            if existing2 and existing2.get("html_url"):
                pr_url = existing2.get("html_url")
            else:
                raise

        # Save scan apply info + fix attempts (best effort)
        try:
            if scans_collection is not None:
                scans_collection.update_one(
                    {"scan_id": scan_id},
                    {"$set": {"apply_counters": counters.__dict__, "pr": pr_url, "updated_at": datetime.utcnow()}},
                    upsert=True,
                )
            if scan_fix_attempts_collection is not None:
                scan_fix_attempts_collection.delete_many({"scan_id": scan_id})
                scan_fix_attempts_collection.insert_many(
                    [
                        {
                            "scan_id": scan_id,
                            "issue_key": (it.get("issue") or {}).get("key"),
                            "source": it.get("source"),
                            "fix_json": it.get("fix_json"),
                        }
                        for it in (fixes_payload.get("results") or [])
                    ],
                    ordered=False,
                )
        except Exception:
            pass

        return {"ok": True, "branch": head_branch, "pr": pr_url, "counters": counters.__dict__}

