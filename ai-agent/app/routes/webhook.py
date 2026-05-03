import hmac
import json
import re
import time
from datetime import datetime
import difflib
import logging
from hashlib import sha256
from typing import Any, Dict, Optional, List

from fastapi import Header, HTTPException, Request

from ..clients.github_app import (
    GitHubRef,
    comment_on_issue,
    close_pull_request,
    create_branch,
    create_pull_request,
    find_open_pull_request,
    get_file_content,
    get_installation_token,
)
from ..clients.sonar import fetch_sonar_issues, resolve_sonar_component_key
from ..core.config import GITHUB_WEBHOOK_SECRET, SHIFTLEFT_FIX_LIMIT, SHIFTLEFT_WEBHOOK_MODE
from ..services.fixes_service import generate_fix_for_issue
from ..services.github_apply import (
    apply_code_changes_via_github_api,
    apply_code_changes_via_github_api_atomic,
    _find_span_tolerant,
)


logger = logging.getLogger("shiftleft.webhook")


def _upsert_github_installation_record(installations_collection, payload: Dict[str, Any]) -> None:
    """
    Persist GitHub App installation metadata (multi-tenant onboarding).
    Does not store tokens; installation tokens are minted on demand.
    """
    if installations_collection is None:
        return
    inst = payload.get("installation") if isinstance(payload.get("installation"), dict) else {}
    inst_id = inst.get("id")
    if not isinstance(inst_id, int):
        return
    acct = inst.get("account") if isinstance(inst.get("account"), dict) else {}
    login = acct.get("login")
    acct_type = acct.get("type")
    repos = payload.get("repositories")
    repo_names: List[str] = []
    if isinstance(repos, list):
        for r in repos:
            if isinstance(r, dict) and isinstance(r.get("full_name"), str):
                repo_names.append(r["full_name"])
    doc = {
        "installation_id": inst_id,
        "account_login": login,
        "account_type": acct_type,
        "repository_selection": inst.get("repository_selection"),
        "repositories": sorted(set(repo_names)),
        "updated_at": datetime.utcnow(),
        "active": True,
    }
    installations_collection.update_one({"installation_id": inst_id}, {"$set": doc}, upsert=True)


def _handle_installation_event(
    installations_collection,
    x_github_event: Optional[str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if installations_collection is None:
        return {"ok": True, "handled": False, "reason": "installations collection not configured"}

    if x_github_event == "installation":
        action = str(payload.get("action") or "")
        inst = payload.get("installation") if isinstance(payload.get("installation"), dict) else {}
        inst_id = inst.get("id")
        if not isinstance(inst_id, int):
            raise HTTPException(status_code=400, detail="Missing installation.id")

        if action == "deleted":
            installations_collection.update_one(
                {"installation_id": inst_id},
                {"$set": {"active": False, "updated_at": datetime.utcnow()}},
                upsert=True,
            )
            return {"ok": True, "handled": True, "event": "installation", "action": action}

        # created / suspend / unsuspend / (others)
        _upsert_github_installation_record(installations_collection, payload)
        return {"ok": True, "handled": True, "event": "installation", "action": action or "unknown"}

    if x_github_event == "installation_repositories":
        action = str(payload.get("action") or "")
        inst = payload.get("installation") if isinstance(payload.get("installation"), dict) else {}
        inst_id = inst.get("id")
        if not isinstance(inst_id, int):
            raise HTTPException(status_code=400, detail="Missing installation.id")

        existing = installations_collection.find_one({"installation_id": inst_id}, {"_id": 0, "repositories": 1}) or {}
        cur = existing.get("repositories") if isinstance(existing.get("repositories"), list) else []
        cur_set = {str(x) for x in cur if isinstance(x, str)}

        added = payload.get("repositories_added") if isinstance(payload.get("repositories_added"), list) else []
        removed = payload.get("repositories_removed") if isinstance(payload.get("repositories_removed"), list) else []

        for r in added:
            if isinstance(r, dict) and isinstance(r.get("full_name"), str):
                cur_set.add(r["full_name"])
        for r in removed:
            if isinstance(r, dict) and isinstance(r.get("full_name"), str):
                cur_set.discard(r["full_name"])

        installations_collection.update_one(
            {"installation_id": inst_id},
            {
                "$set": {
                    "installation_id": inst_id,
                    "repositories": sorted(cur_set),
                    "updated_at": datetime.utcnow(),
                    "active": True,
                }
            },
            upsert=True,
        )
        return {"ok": True, "handled": True, "event": "installation_repositories", "action": action}

    return {"ok": True, "handled": False}


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
    # If there are no actionable changes, treat cache as invalid so we can regenerate.
    # This prevents "PR with identical commit" when the cached fix was safety-sanitized.
    if len(changes) == 0:
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
            if old_code:
                start, _end, _how = _find_span_tolerant(text, old_code)
                if start < 0:
                    return False
        elif op in ("insert_before", "insert_after"):
            # If there's an anchor, it must exist; otherwise line-based insert is considered unsafe
            if not old_code:
                return False
            start, _end, _how = _find_span_tolerant(text, old_code)
            if start < 0:
                return False
        else:
            # Unknown op -> invalidate cache
            return False

    return True


def _find_line_index(lines: List[str], needle: str) -> Optional[int]:
    if not needle:
        return None
    for idx, line in enumerate(lines):
        if needle in line:
            return idx
    return None


def _snippet(lines: List[str], center_idx: int, radius: int = 8) -> List[str]:
    start = max(0, center_idx - radius)
    end = min(len(lines), center_idx + radius + 1)
    return lines[start:end]


def _render_unified_diff(before: str, after: str, path: str, max_lines: int = 120) -> str:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    diff = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    if len(diff) > max_lines:
        diff = diff[:max_lines] + ["@@ ... diff truncated ..."]
    return "\n".join(diff)


def _build_detailed_pr_body(
    repo: GitHubRef,
    token: str,
    base_ref: str,
    branch: str,
    scan_id: str,
    workflow_run: Dict[str, Any],
    counters: Any,
    fixes_payload: Dict[str, Any],
    apply_report: List[Dict[str, Any]],
    max_chars: int = 60000,
) -> str:
    # Header summary
    out: List[str] = []
    out.append("## Shift-Left automated fixes (detailed report)")
    out.append("")
    out.append(f"- **scan_id**: `{scan_id}`")
    out.append(f"- **repo**: `{repo.owner}/{repo.repo}`")
    out.append(f"- **base**: `{base_ref}`")
    out.append(f"- **fix branch**: `{branch}`")
    out.append(f"- **workflow_run_id**: `{workflow_run.get('id')}`")
    out.append(f"- **head_sha**: `{workflow_run.get('head_sha')}`")
    out.append("")
    out.append(f"- **Applied**: {getattr(counters, 'applied', 0)}")
    out.append(f"- **Skipped**: {getattr(counters, 'skipped', 0)}")
    out.append(f"- **Errors**: {getattr(counters, 'errors', 0)}")
    out.append("")

    # Per-issue details
    out.append("## Issues and AI fixes")
    out.append("")

    results = fixes_payload.get("results") or []
    for item in results:
        issue = item.get("issue") or {}
        fix_json = item.get("fix_json") or {}
        if not isinstance(fix_json, dict):
            fix_json = {}

        issue_key = issue.get("key")
        rule = issue.get("rule")
        sev = issue.get("severity")
        comp = issue.get("component") or issue.get("file")
        line = issue.get("line")
        msg = issue.get("message")

        out.append(f"### {issue_key or 'issue'}")
        out.append("")
        out.append(f"- **rule**: `{rule}`")
        out.append(f"- **severity**: `{sev}`")
        out.append(f"- **file**: `{comp}`")
        out.append(f"- **line**: `{line}`")
        out.append(f"- **message**: {msg}")
        out.append(f"- **source**: `{item.get('source')}`")
        out.append("")

        out.append("**AI solution**")
        out.append("")
        sol = fix_json.get("solution") or ""
        if isinstance(sol, str) and sol.strip():
            out.append(sol.strip())
        else:
            out.append("_No solution text provided._")
        out.append("")

        changes = fix_json.get("code_changes") if isinstance(fix_json.get("code_changes"), list) else []
        if not changes:
            out.append("_No code changes._")
            out.append("")
            continue

        out.append("**Code changes (with diffs)**")
        out.append("")

        for ch in changes:
            if not isinstance(ch, dict):
                continue
            op = ch.get("op")
            if op == "move":
                out.append(f"- **move**: `{ch.get('from')}` → `{ch.get('to')}`")
                continue

            path = _normalize_path(str(ch.get("file") or ""))
            if not path:
                continue

            before_text, _ = get_file_content(repo, token, path, ref=base_ref)
            after_text, _ = get_file_content(repo, token, path, ref=branch)
            if before_text is None or after_text is None:
                out.append(f"- **{op}** `{path}` (diff unavailable)")
                continue

            old_code = ch.get("old_code") if isinstance(ch.get("old_code"), str) else ""
            line_no = ch.get("line") if isinstance(ch.get("line"), int) else None

            before_lines = before_text.splitlines()
            after_lines = after_text.splitlines()

            center_before = None
            if old_code:
                center_before = _find_line_index(before_lines, old_code)
            if center_before is None and isinstance(line_no, int) and line_no > 0:
                center_before = max(0, min(len(before_lines) - 1, line_no - 1))
            if center_before is None:
                center_before = 0

            # For after, try same line index to keep context stable
            center_after = max(0, min(len(after_lines) - 1, center_before))

            before_snip = "\n".join(_snippet(before_lines, center_before, radius=8))
            after_snip = "\n".join(_snippet(after_lines, center_after, radius=8))
            diff = _render_unified_diff(before_snip, after_snip, path=path, max_lines=60)

            out.append(f"- **{op}** `{path}`" + (f" (line {line_no})" if line_no else ""))
            out.append("")
            out.append("```diff")
            out.append(diff)
            out.append("```")
            out.append("")

        # Safety cap
        if len("\n".join(out)) > max_chars:
            out.append("## Note")
            out.append("Report truncated due to size limits.")
            break

    # Always include raw apply report at bottom (compact)
    out.append("## Apply report (raw)")
    out.append("")
    out.append("```json")
    out.append(json.dumps(apply_report, ensure_ascii=False, indent=2)[:10000])
    out.append("```")
    out.append("")

    body = "\n".join(out)
    if len(body) > max_chars:
        body = body[: max_chars - 2000] + "\n\n## Note\nReport truncated due to size limits.\n"
    return body


def register_webhook_routes(
    app,
    fixes_collection,
    prompts_collection,
    scans_collection=None,
    scan_issues_collection=None,
    scan_fix_attempts_collection=None,
    github_app_installations_collection=None,
):
    @app.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
        x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    ):
        logger.info("Webhook received event=%s", x_github_event)
        body = await request.body()
        _verify_sig(body, x_hub_signature_256)

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            logger.warning("Invalid JSON payload")
            raise HTTPException(status_code=400, detail="Invalid JSON")

        if x_github_event in ("installation", "installation_repositories"):
            return _handle_installation_event(github_app_installations_collection, x_github_event, payload)

        if x_github_event == "ping":
            return {"ok": True, "ignored": True, "reason": "ping"}

        # We recommend webhook event = workflow_run (Sonar workflow completion)
        if x_github_event != "workflow_run":
            logger.info("Ignoring event=%s (only workflow_run handled)", x_github_event)
            return {"ok": True, "ignored": True, "reason": f"event {x_github_event} not handled"}

        workflow_run = _extract_workflow_run(payload)
        if not workflow_run:
            raise HTTPException(status_code=400, detail="Missing workflow_run payload")

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
        try:
            _upsert_github_installation_record(github_app_installations_collection, payload)
        except Exception:
            pass

        # Prod readiness: CI-failure fallback.
        # If a Shift-Left fixes PR branch fails its PR workflow, automatically split fixes
        # into separate PRs (1 issue per PR) so good fixes can still merge.
        conclusion = workflow_run.get("conclusion")
        wr_event = workflow_run.get("event")
        wr_branch = str(workflow_run.get("head_branch") or "")
        if conclusion not in ("success", None) and wr_event == "pull_request":
            if wr_branch.startswith("shiftleft/fixes-") and "split-" not in wr_branch:
                try:
                    pr = find_open_pull_request(repo, token, head=wr_branch, base="main")
                    if pr and pr.get("number"):
                        pr_num = int(pr["number"])
                        logger.info("CI failed for shiftleft PR=%s branch=%s; splitting fixes", pr_num, wr_branch)
                        comment_on_issue(
                            repo,
                            token,
                            pr_num,
                            (
                                "CI failed for this Shift-Left fixes PR.\n\n"
                                "Prod-ready fallback: closing this PR and re-opening smaller PRs (one issue per PR) "
                                "so passing fixes can still be merged.\n"
                            ),
                        )
                        close_pull_request(repo, token, pr_num)

                    # Re-fetch current issues and open 1 PR per issue (bounded by SHIFTLEFT_FIX_LIMIT)
                    _ck = resolve_sonar_component_key(repo=full_name)
                    sonar_issues = fetch_sonar_issues(_ck) or []
                    for i, issue in enumerate(sonar_issues[:SHIFTLEFT_FIX_LIMIT]):
                        issue_key = str(issue.get("key") or f"issue{i}")
                        sha8 = (workflow_run.get("head_sha", "") or "")[:8] or "latest"
                        run_id = str(workflow_run.get("id") or int(time.time()))
                        # Ensure unique, stable-ish branch name with issue key suffix
                        suffix = re.sub(r"[^A-Za-z0-9]+", "", issue_key)[-12:] or "issue"
                        head_branch = f"shiftleft/fixes-split-{sha8}-{run_id}-{suffix}"
                        scan_id = f"{owner}/{repo_name}:{sha8}:{run_id}:{issue_key}"

                        create_branch(repo, token, new_branch=head_branch, base_branch="main")

                        gen = generate_fix_for_issue(
                            issue,
                            prompts_collection,
                            repo=repo,
                            token=token,
                            ref="main",
                        )
                        fix_json = gen.get("fix_json") or {}
                        changes = fix_json.get("code_changes") if isinstance(fix_json, dict) else None
                        if not isinstance(changes, list) or not changes:
                            continue

                        counters, report = apply_code_changes_via_github_api(
                            repo=repo,
                            token=token,
                            base_ref="main",
                            branch=head_branch,
                            code_changes=changes,
                            commit_message_prefix="chore(shiftleft): apply fixes (split)",
                        )
                        if getattr(counters, "applied", 0) == 0 and getattr(counters, "errors", 0) == 0:
                            continue

                        pr_title = f"chore(shiftleft): auto fix {issue.get('rule')}"
                        fixes_payload = {"results": [{"issue": issue, "fix_json": fix_json, "source": "generated"}]}
                        pr_body = _build_detailed_pr_body(
                            repo=repo,
                            token=token,
                            base_ref="main",
                            branch=head_branch,
                            scan_id=scan_id,
                            workflow_run=workflow_run,
                            counters=counters,
                            fixes_payload=fixes_payload,
                            apply_report=report,
                        )
                        create_pull_request(
                            repo=repo,
                            token=token,
                            title=pr_title,
                            body=pr_body,
                            head=head_branch,
                            base="main",
                        )
                except Exception:
                    logger.exception("CI-failure split fallback failed")

            # Always return ok for failure notifications; we don't want webhook retries.
            return {"ok": True, "handled": True, "mode": "split_on_ci_failure"}

        if workflow_run.get("conclusion") != "success":
            logger.info("Ignoring workflow_run conclusion=%s", workflow_run.get("conclusion"))
            return {"ok": True, "ignored": True, "reason": "workflow_run not successful"}

        # Only run auto-fix PR after successful push-to-main analysis.
        # If we run on PR analyses, we can create PR-on-PR loops and also fail when Sonar PR binding is missing.
        if workflow_run.get("event") != "push":
            logger.info("Ignoring workflow_run event=%s (only push handled)", workflow_run.get("event"))
            return {
                "ok": True,
                "ignored": True,
                "reason": f"workflow_run event is {workflow_run.get('event')}, only 'push' is handled",
            }

        if workflow_run.get("head_branch") != "main":
            logger.info("Ignoring workflow_run head_branch=%s (only main handled)", workflow_run.get("head_branch"))
            return {
                "ok": True,
                "ignored": True,
                "reason": f"workflow_run head_branch is {workflow_run.get('head_branch')}, only 'main' is handled",
            }

        base_branch = "main"
        # Use a unique branch name per run to avoid PR/branch collisions
        sha8 = (workflow_run.get("head_sha", "") or "")[:8] or "latest"
        run_id = str(workflow_run.get("id") or int(time.time()))
        head_branch = f"shiftleft/fixes-{sha8}-{run_id}"
        scan_id = f"{owner}/{repo_name}:{sha8}:{run_id}"
        logger.info(
            "Start scan_id=%s repo=%s/%s base=%s head_branch=%s head_sha=%s",
            scan_id,
            owner,
            repo_name,
            base_branch,
            head_branch,
            workflow_run.get("head_sha"),
        )
        create_branch(repo, token, new_branch=head_branch, base_branch=base_branch)

        _sonar_key = resolve_sonar_component_key(repo=full_name)
        sonar_issues = fetch_sonar_issues(_sonar_key)
        logger.info("scan_id=%s sonar_issues=%s (limit=%s)", scan_id, len(sonar_issues or []), SHIFTLEFT_FIX_LIMIT)
        fixes_payload: Dict[str, Any] = {"results": []}

        mode = SHIFTLEFT_WEBHOOK_MODE or "validate"
        logger.info("scan_id=%s webhook_mode=%s", scan_id, mode)

        created_at = time.time()

        # Generate fixes (cache-first, but validate or refresh depending on mode)
        for issue in (sonar_issues or [])[:SHIFTLEFT_FIX_LIMIT]:
            issue_key = issue.get("key")
            cached = fixes_collection.find_one({"issue_key": issue_key}, {"_id": 0}) if issue_key else None
            if mode != "refresh" and cached and cached.get("fix_json") and isinstance(cached.get("fix_json"), dict):
                fix_json = cached.get("fix_json")
                if mode == "validate":
                    if _is_cached_fix_valid(repo, token, base_branch, fix_json):
                        logger.info("scan_id=%s issue=%s using cache (validated)", scan_id, issue_key)
                        fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "cache"})
                        continue
                    logger.info(
                        "scan_id=%s issue=%s cache invalid -> regenerate (empty/unsafe/stale)",
                        scan_id,
                        issue_key,
                    )
                else:
                    # unknown mode -> treat as cache-first
                    logger.info("scan_id=%s issue=%s using cache (mode=%s)", scan_id, issue_key, mode)
                    fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "cache"})
                    continue

            logger.info("scan_id=%s issue=%s generating fix", scan_id, issue_key)
            gen = generate_fix_for_issue(
                issue,
                prompts_collection,
                repo=repo,
                token=token,
                ref=base_branch,
            )
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
                            "installation_id": installation_id,
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

        # Apply fixes atomically per issue (prod hardening):
        # - Prevent partial fixes (replace applied but required insert skipped)
        # - Each issue's code_changes either fully apply or fully skip
        total_counters = type("C", (), {"applied": 0, "skipped": 0, "errors": 0})()
        report: List[Dict[str, Any]] = []

        for item in fixes_payload["results"]:
            fj = item.get("fix_json") or {}
            changes = fj.get("code_changes") if isinstance(fj, dict) else None
            if not isinstance(changes, list) or not changes:
                continue

            # De-conflict within a single issue only (keeps anchors stable)
            try:
                by_key = {}
                for ch in changes:
                    if not isinstance(ch, dict):
                        continue
                    file = ch.get("file") or ch.get("from")
                    line = ch.get("line")
                    key = (file, line, ch.get("op"))
                    by_key.setdefault(key, []).append(ch)
                deduped = []
                for _k, arr in by_key.items():
                    # pick the first; issue handlers are deterministic so duplicates are noise
                    deduped.append(arr[0])
                changes = deduped
            except Exception:
                pass

            icounters, ireport = apply_code_changes_via_github_api_atomic(
                repo=repo,
                token=token,
                base_ref=base_branch,
                branch=head_branch,
                code_changes=changes,
            )
            total_counters.applied += getattr(icounters, "applied", 0)
            total_counters.skipped += getattr(icounters, "skipped", 0)
            total_counters.errors += getattr(icounters, "errors", 0)
            report.extend(ireport or [])

        counters = total_counters
        logger.info(
            "scan_id=%s apply done applied=%s skipped=%s errors=%s",
            scan_id,
            getattr(counters, "applied", 0),
            getattr(counters, "skipped", 0),
            getattr(counters, "errors", 0),
        )

        if counters.applied == 0 and counters.errors == 0:
            # Nothing to change; don't open a PR.
            if getattr(counters, "skipped", 0) > 0:
                # Surface a compact explanation in logs so users can quickly see why
                # patches didn't apply (common causes: old_code mismatch, safety guards).
                try:
                    preview = []
                    for it in (report or [])[:8]:
                        if not isinstance(it, dict):
                            continue
                        if it.get("ok") is False:
                            preview.append(
                                {
                                    "op": it.get("op"),
                                    "file": it.get("file") or it.get("from"),
                                    "reason": it.get("reason"),
                                }
                            )
                    if preview:
                        logger.info("scan_id=%s skipped_preview=%s", scan_id, preview)
                except Exception:
                    pass
            logger.info("scan_id=%s nothing to apply, PR not created", scan_id)
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
        pr_body = _build_detailed_pr_body(
            repo=repo,
            token=token,
            base_ref=base_branch,
            branch=head_branch,
            scan_id=scan_id,
            workflow_run=workflow_run,
            counters=counters,
            fixes_payload=fixes_payload,
            apply_report=report,
        )

        # If PR already exists (or GitHub returns 422), return existing PR instead of 500.
        existing = find_open_pull_request(repo, token, head=head_branch, base=base_branch)
        if existing and existing.get("html_url"):
            pr_url = existing.get("html_url")
            logger.info("scan_id=%s PR already exists url=%s", scan_id, pr_url)
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
            logger.info("scan_id=%s PR created url=%s", scan_id, pr_url)
        except Exception as e:
            logger.exception("scan_id=%s PR creation failed: %s", scan_id, str(e))
            # Try to recover from "Validation Failed" (422) by looking up an existing PR.
            existing2 = find_open_pull_request(repo, token, head=head_branch, base=base_branch)
            if existing2 and existing2.get("html_url"):
                pr_url = existing2.get("html_url")
                logger.info("scan_id=%s recovered existing PR url=%s", scan_id, pr_url)
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

