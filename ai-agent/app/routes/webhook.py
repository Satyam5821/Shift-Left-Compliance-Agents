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
    get_branch_sha,
    get_installation_token,
    list_open_pull_requests,
    list_check_runs_for_ref,
)
from ..clients.sonar import fetch_sonar_issues, fetch_sonar_hotspots, resolve_sonar_component_key
from ..core.config import GITHUB_WEBHOOK_SECRET, SHIFTLEFT_FIX_LIMIT, SHIFTLEFT_WEBHOOK_MODE
from ..services.fixes_service import generate_fix_for_issue
from ..services.sonar_secrets import decrypt_sonar_token
from ..services.github_apply import (
    apply_code_changes_via_github_api,
    apply_code_changes_via_github_api_atomic,
    _find_span_tolerant,
)


logger = logging.getLogger("shiftleft.webhook")


def _emit_scan_event(
    scan_events_collection,
    scan_id: str,
    stage: str,
    message: str,
    status: str = "running",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a timeline event for the current scan."""
    if scan_events_collection is None or not scan_id:
        return
    try:
        sequence = int(scan_events_collection.count_documents({"scan_id": scan_id})) + 1
    except Exception:
        sequence = int(time.time())
    doc = {
        "scan_id": scan_id,
        "sequence": sequence,
        "stage": stage,
        "message": message,
        "status": status,
        "details": details or {},
        "ts": time.time(),
        "created_at": datetime.utcnow(),
    }
    try:
        scan_events_collection.insert_one(doc)
    except Exception:
        pass


def _inject_missing_imports_in_webhook(
    fix_json: Dict[str, Any],
    issue: Dict[str, Any],
    repo: GitHubRef,
    token: str,
    ref: str,
) -> None:
    """
    Post-process a generated fix to auto-inject missing imports/logger fields.
    This prevents "cannot find symbol" errors from LLM-generated code.
    
    Reads the target file from GitHub, calls _detect_and_add_missing_imports,
    and modifies fix_json in-place to include auto-generated import changes.
    """
    try:
        from ..services.fixes_service import _detect_and_add_missing_imports
    except ImportError:
        return
    
    # Get target file path from issue or first code change
    file_path = issue.get("component") or issue.get("file") or ""
    if not file_path or not file_path.endswith(".java"):
        return
    
    # Normalize path (remove SonarQube project key prefix if present)
    if ":" in file_path:
        file_path = file_path.split(":", 1)[1]
    file_path = file_path.lstrip("/")
    
    try:
        # Read file from GitHub
        file_text, _ = get_file_content(repo, token, file_path, ref=ref)
        if not file_text:
            return
        
        file_lines = file_text.splitlines(keepends=True)
        
        # Call auto-import detection
        # This modifies fix_json["code_changes"] in-place by adding import/logger field changes
        _detect_and_add_missing_imports(fix_json, file_lines, file_path)
    except Exception:
        # Silently fail if import detection doesn't work
        pass


def _open_shiftleft_issue_keys(repo: GitHubRef, token: str, base_branch: str = "main") -> set[str]:
    """
    Collect Sonar issue keys already present in open Shift-Left PR bodies.
    Prevents creating duplicate PRs for the same issue before merge.
    """
    try:
        prs = list_open_pull_requests(repo=repo, token=token, base=base_branch) or []
    except Exception:
        return set()

    keys: set[str] = set()
    for pr in prs:
        head = (pr.get("head") or {}) if isinstance(pr.get("head"), dict) else {}
        head_ref = str(head.get("ref") or "")
        if not head_ref.startswith("shiftleft/fixes-"):
            continue

        body = str(pr.get("body") or "")
        # Sonar issue keys in this system look like: AZ38TQG_Z0HDVRtvKZ98
        for match in re.findall(r"\bAZ[\w\-]+\b", body):
            keys.add(match)
    return keys


def _validate_and_autofix_build_for_pr(
    repo: GitHubRef,
    token: str,
    branch: str,
    base_branch: str,
    scan_id: str,
    scan_events_collection=None,
    fixes_payload: Optional[Dict[str, Any]] = None,
    prompts_collection=None,
) -> None:
    """
    Build validation + auto-fix for Java projects (Maven).
    Runs BEFORE PR creation to prevent broken commits from being submitted.
    
    Workflow:
    1. Clone repo to temp directory
    2. Checkout branch (with applied fixes)
    3. Run 'mvn clean compile' 
    4. If build fails, attempt low-risk auto-fixes (imports, logger field)
    5. Re-validate build
    6. Push any auto-fix changes back to the branch
    
    Silently fails if validation can't run (e.g., non-Java project).
    """
    try:
        fixes_payload = fixes_payload or {"results": []}
        import subprocess
        import tempfile
        import shutil
        from pathlib import Path
        from ..services.fixes_service import validate_build, generate_fix_for_build_error
        
        # Clone repo to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            clone_url = f"https://x-access-token:{token}@github.com/{repo.owner}/{repo.repo}.git"
            
            try:
                subprocess.run(
                    ["git", "clone", "--recursive", "--depth=1", clone_url, str(tmpdir_path)],
                    timeout=30,
                    check=True,
                    capture_output=True,
                )
            except subprocess.TimeoutExpired:
                logger.warning("scan_id=%s build validation: clone timeout", scan_id)
                _emit_scan_event(scan_events_collection, scan_id, "build", "Repo clone timed out while validating build", "failed")
                return
            except subprocess.CalledProcessError as e:
                logger.warning("scan_id=%s build validation: clone failed %s", scan_id, str(e))
                _emit_scan_event(scan_events_collection, scan_id, "build", "Repo clone failed while validating build", "failed", {"error": str(e)})
                return

            # Fetch + checkout the branch. Retry a few times to avoid race with GitHub creating branch.
            fetch_attempts = 3
            fetched = False
            for attempt in range(1, fetch_attempts + 1):
                try:
                    subprocess.run(
                        ["git", "-C", str(tmpdir_path), "fetch", "origin", branch],
                        timeout=30,
                        check=True,
                        capture_output=True,
                    )
                    # Try to create local branch tracking remote branch and checkout
                    subprocess.run(
                        ["git", "-C", str(tmpdir_path), "checkout", "-B", branch, f"origin/{branch}"],
                        timeout=30,
                        check=True,
                        capture_output=True,
                    )
                    fetched = True
                    break
                except subprocess.CalledProcessError as e:
                    logger.info("scan_id=%s git fetch/checkout attempt %d failed: %s", scan_id, attempt, str(e))
                    if attempt < fetch_attempts:
                        import time

                        time.sleep(2 * attempt)
                    else:
                        logger.warning("scan_id=%s build validation: fetch/checkout failed after %d attempts", scan_id, fetch_attempts)
                        _emit_scan_event(scan_events_collection, scan_id, "build", "Repo fetch/checkout failed while validating build", "failed", {"error": str(e)})
                        return
            
            # Validate build
            build_result = validate_build(str(tmpdir_path), build_tool="maven")
            if build_result.get("status") == "success":
                logger.info("scan_id=%s build validation: PASSED", scan_id)
                _emit_scan_event(scan_events_collection, scan_id, "build", "Build validation passed", "done")
                return
            
            # Build failed; attempt auto-fixes (max 3 attempts)
            logger.info("scan_id=%s build validation: FAILED; attempting auto-fixes", scan_id)
            _emit_scan_event(scan_events_collection, scan_id, "build", "Build validation failed; attempting auto-fixes", "running", {"errors": build_result.get("errors") or []})
            errors = build_result.get("errors") or []
            max_attempts = 3
            attempt = 0
            
            while attempt < max_attempts and build_result.get("status") != "success":
                attempt += 1
                applied_count = 0
                
                for error in errors:
                    error_file = error.get("file") or ""
                    # Normalize path relative to repo root
                    if error_file.startswith(str(tmpdir_path)):
                        rel_path = error_file[len(str(tmpdir_path)):].lstrip("/\\")
                    else:
                        rel_path = error_file
                    
                    # Generate low-risk fix for this error
                    fix_desc = generate_fix_for_build_error(error, rel_path)
                    if not fix_desc:
                        continue
                    
                    # Apply the fix locally
                    op = fix_desc.get("op")
                    target_file = tmpdir_path / rel_path
                    
                    try:
                        if not target_file.exists():
                            continue
                        
                        if op == "insert_import":
                            import_path = fix_desc.get("import")
                            if import_path:
                                from ..services.github_apply import _apply_insert_text
                                text = target_file.read_text(encoding="utf-8")
                                ok, new_text, _ = _apply_insert_text(
                                    text,
                                    mode="insert_before",
                                    line=None,
                                    anchor=None,
                                    new_code=f"import {import_path};\n",
                                )
                                if ok:
                                    target_file.write_text(new_text, encoding="utf-8")
                                    applied_count += 1
                        
                        elif op == "syntax_fix" and fix_desc.get("error_type") == "missing_semicolon":
                            line_no = fix_desc.get("line")
                            if isinstance(line_no, int):
                                from ..services.github_apply import _apply_replace_text
                                text = target_file.read_text(encoding="utf-8")
                                lines = text.splitlines(keepends=True)
                                if 1 <= line_no <= len(lines):
                                    raw = lines[line_no - 1].rstrip("\n")
                                    if not raw.strip().endswith(";"):
                                        ok, new_text, _ = _apply_replace_text(text, line_no, raw, raw + ";")
                                        if ok:
                                            target_file.write_text(new_text, encoding="utf-8")
                                            applied_count += 1
                    except Exception:
                        pass
                
                if applied_count == 0:
                    logger.info("scan_id=%s build validation attempt %d: no fixes applied; stopping", scan_id, attempt)
                    _emit_scan_event(scan_events_collection, scan_id, "build", f"Auto-fix attempt {attempt} produced no safe changes", "running")
                    break
                
                # Re-validate build after applying fixes
                build_result = validate_build(str(tmpdir_path), build_tool="maven")
                logger.info("scan_id=%s build validation attempt %d: %s (applied %d fixes)", scan_id, attempt, build_result.get("status"), applied_count)
                _emit_scan_event(
                    scan_events_collection,
                    scan_id,
                    "build",
                    f"Auto-fix attempt {attempt} finished with status {build_result.get('status')}",
                    "running" if build_result.get("status") != "success" else "done",
                    {"attempt": attempt, "applied": applied_count, "status": build_result.get("status"), "errors": build_result.get("errors") or []},
                )
            
            # If build now passes, commit and push the auto-fixes
            if build_result.get("status") == "success":
                logger.info("scan_id=%s build validation: SUCCESS after auto-fixes", scan_id)
                _emit_scan_event(scan_events_collection, scan_id, "build", "Build passed after auto-fixes", "done")
                try:
                    # Commit any local changes
                    subprocess.run(
                        ["git", "-C", str(tmpdir_path), "add", "-A"],
                        timeout=10,
                        check=True,
                        capture_output=True,
                    )
                    result = subprocess.run(
                        ["git", "-C", str(tmpdir_path), "status", "--porcelain"],
                        timeout=10,
                        capture_output=True,
                        text=True,
                    )
                    if result.stdout.strip():  # There are changes
                        subprocess.run(
                            ["git", "-C", str(tmpdir_path), "commit", "-m", f"chore(shiftleft): auto-fix build errors ({scan_id[:8]})"],
                            timeout=10,
                            check=True,
                            capture_output=True,
                        )
                        subprocess.run(
                            ["git", "-C", str(tmpdir_path), "push", "origin", branch],
                            timeout=30,
                            check=True,
                            capture_output=True,
                        )
                        logger.info("scan_id=%s auto-fix changes pushed to branch", scan_id)
                        _emit_scan_event(scan_events_collection, scan_id, "push", "Auto-fix changes pushed to branch", "done")
                except subprocess.TimeoutExpired:
                    logger.warning("scan_id=%s auto-fix push: timeout", scan_id)
                    _emit_scan_event(scan_events_collection, scan_id, "push", "Auto-fix push timed out", "failed")
                except subprocess.CalledProcessError as e:
                    logger.warning("scan_id=%s auto-fix push failed: %s", scan_id, str(e))
                    _emit_scan_event(scan_events_collection, scan_id, "push", "Auto-fix push failed", "failed", {"error": str(e)})
            else:
                logger.warning("scan_id=%s build validation: still failing after auto-fix attempts", scan_id)
                _emit_scan_event(scan_events_collection, scan_id, "build", "Build still failing after auto-fix attempts", "failed", {"errors": build_result.get("errors") or []})

            # If still failing, attempt to regenerate LLM fixes for issues that were applied
            # This gives the AI agent another chance to produce a compilable fix.
            if build_result.get("status") != "success" and prompts_collection and fixes_payload and isinstance(fixes_payload.get("results"), list):
                regen_limit = 2
                for regen in range(regen_limit):
                    regen_applied = 0
                    for item in (fixes_payload.get("results") or []):
                        try:
                            issue = item.get("issue") or {}
                            if not issue:
                                continue
                            # Ask LLM to regenerate a safer fix (uses existing prompt templates)
                            gen = generate_fix_for_issue(issue, prompts_collection, repo=repo, token=token, ref=branch)
                            new_fix = gen.get("fix_json") if isinstance(gen, dict) else None
                            if not new_fix or not isinstance(new_fix.get("code_changes"), list):
                                continue

                            # Apply new_fix changes locally
                            for ch in (new_fix.get("code_changes") or []):
                                if not isinstance(ch, dict):
                                    continue
                                op = ch.get("op")
                                fpath = tmpdir_path / _normalize_path(str(ch.get("file") or ch.get("from") or ""))
                                if not fpath.exists():
                                    continue
                                try:
                                    if op in ("replace", "delete") and isinstance(ch.get("old_code"), str):
                                        from ..services.github_apply import _apply_replace_text

                                        text = fpath.read_text(encoding="utf-8")
                                        ok, new_text, _ = _apply_replace_text(text, ch.get("line"), ch.get("old_code"), ch.get("new_code") or "")
                                        if ok:
                                            fpath.write_text(new_text, encoding="utf-8")
                                            regen_applied += 1
                                    elif op in ("insert_before", "insert_after") and isinstance(ch.get("new_code"), str):
                                        from ..services.github_apply import _apply_insert_text

                                        text = fpath.read_text(encoding="utf-8")
                                        ok, new_text, _ = _apply_insert_text(text, mode=("insert_before" if op=="insert_before" else "insert_after"), line=None, anchor=ch.get("old_code"), new_code=ch.get("new_code"))
                                        if ok:
                                            fpath.write_text(new_text, encoding="utf-8")
                                            regen_applied += 1
                                except Exception:
                                    continue
                        except Exception:
                            continue

                    if regen_applied == 0:
                        break

                    # Re-run build validation
                    build_result = validate_build(str(tmpdir_path), build_tool="maven")
                    _emit_scan_event(scan_events_collection, scan_id, "build", f"Regeneration attempt finished with status {build_result.get('status')}", "running" if build_result.get("status") != "success" else "done", {"attempt": regen + 1, "status": build_result.get("status")})
                    if build_result.get("status") == "success":
                        # Commit & push
                        try:
                            subprocess.run(["git", "-C", str(tmpdir_path), "add", "-A"], timeout=10, check=True, capture_output=True)
                            result = subprocess.run(["git", "-C", str(tmpdir_path), "status", "--porcelain"], timeout=10, capture_output=True, text=True)
                            if result.stdout.strip():
                                subprocess.run(["git", "-C", str(tmpdir_path), "commit", "-m", f"chore(shiftleft): regen auto-fix build errors ({scan_id[:8]})"], timeout=10, check=True, capture_output=True)
                                subprocess.run(["git", "-C", str(tmpdir_path), "push", "origin", branch], timeout=30, check=True, capture_output=True)
                                _emit_scan_event(scan_events_collection, scan_id, "push", "Regen auto-fix changes pushed to branch", "done")
                        except Exception as e:
                            logger.warning("scan_id=%s regen auto-fix push failed: %s", scan_id, str(e))
                        break
    
    except ImportError:
        logger.debug("scan_id=%s build validation: fixes_service not available", scan_id)
    except Exception as e:
        logger.warning("scan_id=%s build validation: unexpected error: %s", scan_id, str(e))


def _resolve_sonar_token_for_repo(
    full_name: str,
    installation_id: int,
    workspaces_collection=None,
    sonar_connections_collection=None,
) -> Optional[str]:
    """
    Webhook is not user-authenticated, so resolve which user's Sonar token to use
    by looking up a workspace that includes this repo under the same installation.
    """
    if workspaces_collection is None or sonar_connections_collection is None:
        return None
    try:
        ws = workspaces_collection.find_one(
            {"installationId": installation_id, "repos": full_name},
            {"_id": 0, "user_id": 1, "sonar_token_enc": 1},
        )
        if not isinstance(ws, dict) or not ws.get("user_id"):
            return None
        if ws.get("sonar_token_enc"):
            tok = decrypt_sonar_token(str(ws.get("sonar_token_enc") or ""))
            if tok:
                return tok
        conn = sonar_connections_collection.find_one({"user_id": ws["user_id"]}, {"_id": 0, "token_enc": 1})
        if not isinstance(conn, dict) or not conn.get("token_enc"):
            return None
        return decrypt_sonar_token(str(conn.get("token_enc") or "")) or None
    except Exception:
        return None


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


def _sonar_check_status_for_ref(repo: GitHubRef, token: str, ref: str) -> Dict[str, Any]:
    """
    Determine Sonar check-run status for the latest commit on a ref.
    Returns one of: not_found, pending, failed, passed.
    """
    try:
        commit_sha = get_branch_sha(repo=repo, token=token, branch=ref)
    except Exception as e:
        return {"state": "unavailable", "reason": f"branch_sha_unavailable: {e}"}

    try:
        data = list_check_runs_for_ref(repo=repo, token=token, ref=commit_sha) or {}
    except Exception as e:
        msg = str(e)
        if "403" in msg or "Forbidden" in msg:
            return {"state": "unavailable", "reason": "checks_api_forbidden", "commit_sha": commit_sha}
        return {"state": "unavailable", "reason": f"checks_api_error: {e}", "commit_sha": commit_sha}

    check_runs = data.get("check_runs") or []
    sonar_runs = [
        cr
        for cr in check_runs
        if "sonar" in str((cr or {}).get("name") or "").lower()
    ]

    if not sonar_runs:
        return {"state": "not_found", "runs": []}

    completed = [cr for cr in sonar_runs if str(cr.get("status") or "") == "completed"]
    failed = [cr for cr in completed if str(cr.get("conclusion") or "") == "failure"]
    if failed:
        return {"state": "failed", "runs": failed}

    if len(completed) < len(sonar_runs):
        return {"state": "pending", "runs": sonar_runs}

    passed = [
        cr
        for cr in completed
        if str(cr.get("conclusion") or "") in ("success", "neutral", "skipped")
    ]
    if passed:
        return {"state": "passed", "runs": passed}

    return {"state": "pending", "runs": sonar_runs}


def _proactive_qg_poll_and_recover(
    repo: GitHubRef,
    token: str,
    installation_id: int,
    full_name: str,
    pr_number: Optional[int],
    head_branch: str,
    scan_id: str,
    fixes_collection,
    prompts_collection,
    scans_collection,
    scan_events_collection,
    scan_issues_collection,
    scan_fix_attempts_collection,
    github_app_installations_collection,
    workspaces_collection,
    sonar_connections_collection,
    quality_gate_retries_collection,
) -> Dict[str, Any]:
    """
    Poll check-runs for the PR head branch and proactively trigger QG recovery
    without waiting for check_run webhooks.
    """
    if not pr_number or not head_branch:
        return {"ok": True, "ignored": True, "reason": "Missing PR number or branch"}

    poll_interval_seconds = 15
    max_wait_seconds = 600
    max_local_recovery_attempts = 3
    start_ts = time.time()
    local_attempts = 0

    _emit_scan_event(
        scan_events_collection,
        scan_id,
        "qg",
        f"Starting proactive QG polling for PR #{pr_number}",
        "running",
    )

    while time.time() - start_ts <= max_wait_seconds:
        try:
            status = _sonar_check_status_for_ref(repo=repo, token=token, ref=head_branch)
            state = status.get("state")
        except Exception as e:
            logger.warning("scan_id=%s proactive QG poll error: %s", scan_id, str(e))
            time.sleep(poll_interval_seconds)
            continue

        if state in ("not_found", "pending"):
            time.sleep(poll_interval_seconds)
            continue

        if state == "unavailable":
            reason = status.get("reason") or "checks_unavailable"
            logger.warning("scan_id=%s proactive QG polling unavailable: %s", scan_id, reason)
            _emit_scan_event(scan_events_collection, scan_id, "qg", f"Proactive QG polling unavailable: {reason}", "running", {"pr": pr_number, "reason": reason})
            return {"ok": True, "handled": True, "status": "unavailable", "pr": pr_number, "reason": reason}

        if state == "passed":
            logger.info("scan_id=%s proactive QG polling: PASSED for PR #%s", scan_id, pr_number)
            _emit_scan_event(scan_events_collection, scan_id, "qg", "Quality Gate passed", "done", {"pr": pr_number})
            return {"ok": True, "handled": True, "status": "passed", "pr": pr_number}

        if state == "failed":
            if local_attempts >= max_local_recovery_attempts:
                logger.info("scan_id=%s proactive QG polling: max local retries reached for PR #%s", scan_id, pr_number)
                _emit_scan_event(
                    scan_events_collection,
                    scan_id,
                    "qg",
                    f"Quality Gate still failing after {max_local_recovery_attempts} proactive retry attempts",
                    "failed",
                    {"pr": pr_number},
                )
                return {"ok": True, "handled": True, "status": "failed", "pr": pr_number, "retries": local_attempts}

            local_attempts += 1
            logger.info(
                "scan_id=%s proactive QG polling: failure detected, recovery attempt %d/%d for PR #%s",
                scan_id,
                local_attempts,
                max_local_recovery_attempts,
                pr_number,
            )
            _emit_scan_event(
                scan_events_collection,
                scan_id,
                "qg",
                f"Quality Gate failed; proactive recovery attempt {local_attempts}/{max_local_recovery_attempts}",
                "running",
                {"pr": pr_number},
            )

            synthetic_payload = {
                "check_run": {
                    "name": "SonarCloud Code Analysis",
                    "conclusion": "failure",
                    "pull_requests": [{"number": pr_number, "head": {"ref": head_branch}}],
                },
                "repository": {"full_name": full_name},
                "installation": {"id": installation_id},
            }

            recovery = _handle_check_run_event(
                synthetic_payload,
                fixes_collection,
                prompts_collection,
                scans_collection,
                scan_events_collection,
                scan_issues_collection,
                scan_fix_attempts_collection,
                github_app_installations_collection,
                workspaces_collection,
                sonar_connections_collection,
                quality_gate_retries_collection,
            )

            if not recovery.get("ok"):
                logger.warning("scan_id=%s proactive QG recovery returned not ok: %s", scan_id, recovery)
                _emit_scan_event(scan_events_collection, scan_id, "qg", "Proactive QG recovery failed", "failed", {"result": recovery})
                return {"ok": False, "handled": True, "status": "recovery_error", "result": recovery}

            if recovery.get("handled"):
                time.sleep(poll_interval_seconds)
                continue

            return {"ok": True, "handled": True, "status": "failed_no_fix", "result": recovery}

    _emit_scan_event(
        scan_events_collection,
        scan_id,
        "qg",
        "Proactive QG polling timed out before a final status was available",
        "running",
        {"wait_seconds": max_wait_seconds, "pr": pr_number},
    )
    return {"ok": True, "handled": True, "status": "timeout", "pr": pr_number}


def _handle_check_run_event(
    payload: Dict[str, Any],
    fixes_collection,
    prompts_collection,
    scans_collection,
    scan_events_collection,
    scan_issues_collection,
    scan_fix_attempts_collection,
    github_app_installations_collection,
    workspaces_collection,
    sonar_connections_collection,
    quality_gate_retries_collection,
) -> Dict[str, Any]:
    """
    Handle check_run events to detect and recover from Quality Gate failures.
    Max retries: 3 per PR to avoid infinite loops.
    """
    try:
        check_run = payload.get("check_run") or {}
        repo_obj = (payload.get("repository") or {}) if isinstance(payload.get("repository"), dict) else {}
        full_name = repo_obj.get("full_name") or ""
        
        if not full_name or "/" not in full_name:
            return {"ok": False, "reason": "Missing repository info"}
        
        check_run_name = check_run.get("name") or ""
        check_run_conclusion = check_run.get("conclusion") or ""
        
        # Only handle SonarCloud Quality Gate check failures
        if "SonarCloud" not in check_run_name or check_run_conclusion != "failure":
            return {"ok": True, "ignored": True, "reason": "Not a SonarCloud QG failure"}
        
        # Extract PR and branch info
        pull_requests = check_run.get("pull_requests") or []
        if not pull_requests:
            return {"ok": True, "ignored": True, "reason": "No PR associated"}
        
        pr = pull_requests[0]
        pr_number = pr.get("number")
        head_branch = pr.get("head", {}).get("ref")
        
        # Only handle Shift-Left fix PRs
        if not head_branch or not head_branch.startswith("shiftleft/fixes-"):
            return {"ok": True, "ignored": True, "reason": "Not a Shift-Left PR"}
        
        # Check retry limit
        MAX_QG_RETRIES = 3
        retry_key = f"{full_name}:pr:{pr_number}"
        retry_doc = quality_gate_retries_collection.find_one({"key": retry_key}) if quality_gate_retries_collection else None
        retry_count = (retry_doc.get("count") or 0) if retry_doc else 0
        attempted_issue_keys = set((retry_doc or {}).get("attempted_issue_keys") or [])
        
        if retry_count >= MAX_QG_RETRIES:
            logger.info("QG recovery: max retries (%d) reached for %s", MAX_QG_RETRIES, retry_key)
            return {"ok": True, "ignored": True, "reason": f"Max retries ({MAX_QG_RETRIES}) reached"}
        
        # Get tokens
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            return {"ok": False, "reason": "Missing installation info"}
        
        token = get_installation_token(installation_id)
        owner, repo_name = full_name.split("/", 1)
        repo = GitHubRef(owner=owner, repo=repo_name)
        
        sonar_token_override = _resolve_sonar_token_for_repo(
            full_name=full_name,
            installation_id=installation_id,
            workspaces_collection=workspaces_collection,
            sonar_connections_collection=sonar_connections_collection,
        )
        
        # Fetch failing issues and hotspots for this PR scope.
        sonar_key = resolve_sonar_component_key(repo=full_name)
        pr_scope = str(pr_number) if pr_number is not None else None
        sonar_issues = fetch_sonar_issues(sonar_key, token_override=sonar_token_override, pull_request=pr_scope) or []
        sonar_hotspots = fetch_sonar_hotspots(sonar_key, token_override=sonar_token_override, pull_request=pr_scope) or []
        sonar_issues = sonar_issues + sonar_hotspots  # Merge issues and hotspots
        
        if not sonar_issues:
            return {"ok": True, "ignored": True, "reason": "No issues to fix"}
        
        logger.info("QG recovery: %d PR-scoped issues found, retry=%d for %s", len(sonar_issues), retry_count, retry_key)

        # Fix one previously-untried issue per retry.
        target_issue = None
        for issue in sonar_issues:
            issue_key = str(issue.get("key") or "").strip()
            if issue_key and issue_key not in attempted_issue_keys:
                target_issue = issue
                break

        if not target_issue:
            return {
                "ok": True,
                "handled": False,
                "reason": "No new PR-scoped issues left to try",
                "attempted_issue_keys": sorted(attempted_issue_keys),
            }

        issue_key = str(target_issue.get("key") or "")
        attempted_issue_keys.add(issue_key)

        try:
            gen = generate_fix_for_issue(target_issue, prompts_collection, repo=repo, token=token, ref=head_branch)
            fix_json = gen.get("fix_json")

            if not fix_json or not fix_json.get("code_changes"):
                if quality_gate_retries_collection:
                    quality_gate_retries_collection.update_one(
                        {"key": retry_key},
                        {
                            "$set": {
                                "key": retry_key,
                                "pr": pr_number,
                                "count": retry_count + 1,
                                "attempted_issue_keys": sorted(attempted_issue_keys),
                                "last_issue_key": issue_key,
                                "last_result": "no_code_changes",
                                "last_updated": datetime.utcnow(),
                            }
                        },
                        upsert=True,
                    )
                return {"ok": True, "handled": False, "reason": "No code changes generated", "issue_key": issue_key}

            # Apply fix atomically
            counters, apply_report = apply_code_changes_via_github_api_atomic(
                repo=repo,
                token=token,
                base_ref=head_branch,
                branch=head_branch,
                code_changes=fix_json.get("code_changes") or [],
                commit_message_prefix=f"chore(shiftleft): fix QG issue {issue_key}",
            )

            applied_ok = getattr(counters, "applied", 0) > 0 and getattr(counters, "errors", 0) == 0
            if quality_gate_retries_collection:
                quality_gate_retries_collection.update_one(
                    {"key": retry_key},
                    {
                        "$set": {
                            "key": retry_key,
                            "pr": pr_number,
                            "count": retry_count + 1,
                            "attempted_issue_keys": sorted(attempted_issue_keys),
                            "last_issue_key": issue_key,
                            "last_result": "applied" if applied_ok else "apply_failed",
                            "last_apply_report": (apply_report or [])[:5],
                            "last_updated": datetime.utcnow(),
                        }
                    },
                    upsert=True,
                )

            if applied_ok:
                logger.info("QG recovery: applied fix for %s", issue_key)
                return {"ok": True, "handled": True, "retry": retry_count + 1, "issue_key": issue_key}

            return {"ok": True, "handled": False, "reason": "Apply failed", "issue_key": issue_key}
        except Exception as e:
            if quality_gate_retries_collection:
                quality_gate_retries_collection.update_one(
                    {"key": retry_key},
                    {
                        "$set": {
                            "key": retry_key,
                            "pr": pr_number,
                            "count": retry_count + 1,
                            "attempted_issue_keys": sorted(attempted_issue_keys),
                            "last_issue_key": issue_key,
                            "last_result": "exception",
                            "last_error": str(e),
                            "last_updated": datetime.utcnow(),
                        }
                    },
                    upsert=True,
                )
            logger.warning("QG recovery error for %s: %s", issue_key, str(e))
            return {"ok": False, "error": str(e), "issue_key": issue_key}
    except Exception as e:
        logger.error("QG recovery failed: %s", str(e))
        return {"ok": False, "error": str(e)}


def register_webhook_routes(
    app,
    fixes_collection,
    prompts_collection,
    scans_collection=None,
    scan_events_collection=None,
    scan_issues_collection=None,
    scan_fix_attempts_collection=None,
    github_app_installations_collection=None,
    workspaces_collection=None,
    sonar_connections_collection=None,
    quality_gate_retries_collection=None,
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

        # Handle Quality Gate failures from check_run events
        if x_github_event == "check_run":
            return _handle_check_run_event(
                payload,
                fixes_collection,
                prompts_collection,
                scans_collection,
                scan_events_collection,
                scan_issues_collection,
                scan_fix_attempts_collection,
                github_app_installations_collection,
                workspaces_collection,
                sonar_connections_collection,
                quality_gate_retries_collection,
            )

        # We recommend webhook event = workflow_run (Sonar workflow completion)
        if x_github_event != "workflow_run":
            logger.info("Ignoring event=%s (only workflow_run and check_run handled)", x_github_event)
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
        sonar_token_override = _resolve_sonar_token_for_repo(
            full_name=full_name,
            installation_id=installation_id,
            workspaces_collection=workspaces_collection,
            sonar_connections_collection=sonar_connections_collection,
        )
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

                    # Re-fetch current issues and hotspots, open 1 PR per issue (bounded by SHIFTLEFT_FIX_LIMIT)
                    _ck = resolve_sonar_component_key(repo=full_name)
                    sonar_issues = fetch_sonar_issues(_ck, token_override=sonar_token_override) or []
                    sonar_hotspots = fetch_sonar_hotspots(_ck, token_override=sonar_token_override) or []
                    sonar_issues = sonar_issues + sonar_hotspots  # Merge issues and hotspots
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
                        
                        # Post-process: auto-inject missing imports if needed
                        if isinstance(fix_json, dict):
                            try:
                                _inject_missing_imports_in_webhook(fix_json, issue, repo, token, "main")
                            except Exception as e:
                                logger.debug("split flow import injection error: %s", str(e))
                        
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
        _emit_scan_event(scan_events_collection, scan_id, "commit", "Workflow run received and scan started", "running", {"repo": full_name, "head_branch": head_branch, "head_sha": workflow_run.get("head_sha")})
        create_branch(repo, token, new_branch=head_branch, base_branch=base_branch)
        _emit_scan_event(scan_events_collection, scan_id, "branch", f"Created fix branch {head_branch}", "running")

        _sonar_key = resolve_sonar_component_key(repo=full_name)
        sonar_issues = fetch_sonar_issues(_sonar_key, token_override=sonar_token_override) or []
        sonar_hotspots = fetch_sonar_hotspots(_sonar_key, token_override=sonar_token_override) or []
        sonar_issues = sonar_issues + sonar_hotspots  # Merge issues and hotspots

        # De-duplicate against already-open Shift-Left PRs to avoid repeated PRs for same issue.
        existing_issue_keys = _open_shiftleft_issue_keys(repo=repo, token=token, base_branch=base_branch)
        if existing_issue_keys:
            before_count = len(sonar_issues or [])
            sonar_issues = [
                it
                for it in (sonar_issues or [])
                if str((it or {}).get("key") or "") not in existing_issue_keys
            ]
            skipped = before_count - len(sonar_issues)
            if skipped > 0:
                logger.info("scan_id=%s dedupe: skipped %d issue(s) already in open Shift-Left PRs", scan_id, skipped)
                _emit_scan_event(
                    scan_events_collection,
                    scan_id,
                    "dedupe",
                    f"Skipped {skipped} issue(s) already covered by open Shift-Left PR(s)",
                    "running",
                    {"skipped": skipped},
                )

        logger.info("scan_id=%s sonar_issues=%s (limit=%s)", scan_id, len(sonar_issues or []), SHIFTLEFT_FIX_LIMIT)
        _emit_scan_event(scan_events_collection, scan_id, "sonar", f"Fetched {len(sonar_issues or [])} Sonar issue(s)", "running", {"limit": SHIFTLEFT_FIX_LIMIT})
        fixes_payload: Dict[str, Any] = {"results": []}

        mode = SHIFTLEFT_WEBHOOK_MODE or "validate"
        logger.info("scan_id=%s webhook_mode=%s", scan_id, mode)

        created_at = time.time()

        # Generate fixes (cache-first, but validate or refresh depending on mode)
        for issue in (sonar_issues or [])[:SHIFTLEFT_FIX_LIMIT]:
            issue_key = issue.get("key")
            _emit_scan_event(scan_events_collection, scan_id, "issue", f"Processing issue {issue_key or 'unknown'}", "running", {"rule": issue.get("rule"), "severity": issue.get("severity"), "file": issue.get("component")})
            cached = fixes_collection.find_one({"issue_key": issue_key}, {"_id": 0}) if issue_key else None
            if mode != "refresh" and cached and cached.get("fix_json") and isinstance(cached.get("fix_json"), dict):
                fix_json = cached.get("fix_json")
                if mode == "validate":
                    if _is_cached_fix_valid(repo, token, base_branch, fix_json):
                        logger.info("scan_id=%s issue=%s using cache (validated)", scan_id, issue_key)
                        _emit_scan_event(scan_events_collection, scan_id, "fix", f"Using cached fix for {issue_key or 'issue'}", "running", {"source": "cache"})
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
                    _emit_scan_event(scan_events_collection, scan_id, "fix", f"Using cached fix for {issue_key or 'issue'}", "running", {"source": "cache", "mode": mode})
                    fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "cache"})
                    continue

            logger.info("scan_id=%s issue=%s generating fix", scan_id, issue_key)
            _emit_scan_event(scan_events_collection, scan_id, "fix", f"Generating fix for {issue_key or 'issue'}", "running")
            gen = generate_fix_for_issue(
                issue,
                prompts_collection,
                repo=repo,
                token=token,
                ref=base_branch,
            )
            fix_json = gen.get("fix_json")
            
            # Post-process: auto-inject missing imports if needed (prevents "cannot find symbol" errors)
            if isinstance(fix_json, dict):
                try:
                    _inject_missing_imports_in_webhook(fix_json, issue, repo, token, base_branch)
                except Exception as e:
                    logger.debug("scan_id=%s issue=%s import injection error (non-blocking): %s", scan_id, issue_key, str(e))
                try:
                    from ..services.fixes_service import _sanitize_user_input_logging
                    _sanitize_user_input_logging(fix_json, [], issue.get("file") or "")
                except Exception:
                    logger.debug("scan_id=%s issue=%s sanitizer error (non-blocking)", scan_id, issue_key)
            
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
            _emit_scan_event(scan_events_collection, scan_id, "fix", f"Generated fix for {issue_key or 'issue'}", "running", {"source": "generated"})

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
        _emit_scan_event(
            scan_events_collection,
            scan_id,
            "apply",
            f"Applied {getattr(counters, 'applied', 0)} change(s), skipped {getattr(counters, 'skipped', 0)}, errors {getattr(counters, 'errors', 0)}",
            "running" if getattr(counters, "applied", 0) > 0 else "failed",
            {"applied": getattr(counters, "applied", 0), "skipped": getattr(counters, "skipped", 0), "errors": getattr(counters, "errors", 0)},
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
            _emit_scan_event(scan_events_collection, scan_id, "complete", "Nothing applicable to apply; PR not created", "failed")
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

        # CRITICAL: Validate build before PR creation to prevent broken commits
        # If build fails, attempt low-risk auto-fixes (imports, logger field, etc.)
        try:
            _emit_scan_event(scan_events_collection, scan_id, "build", "Starting build validation before PR creation", "running")
            _validate_and_autofix_build_for_pr(
                repo=repo,
                token=token,
                branch=head_branch,
                base_branch=base_branch,
                scan_id=scan_id,
                scan_events_collection=scan_events_collection,
                fixes_payload=fixes_payload,
                prompts_collection=prompts_collection,
            )
        except Exception as e:
            logger.warning("scan_id=%s build validation error (non-blocking): %s", scan_id, str(e))
            # Continue with PR creation even if validation fails; GitHub CI will catch it
            _emit_scan_event(scan_events_collection, scan_id, "build", "Build validation error (non-blocking)", "running", {"error": str(e)})

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
            _emit_scan_event(scan_events_collection, scan_id, "pr", f"PR already exists: {pr_url}", "done", {"url": pr_url})
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
            pr_number = pr.get("number")
            logger.info("scan_id=%s PR created url=%s", scan_id, pr_url)
            _emit_scan_event(scan_events_collection, scan_id, "pr", f"PR created: {pr_url}", "done", {"url": pr_url})
        except Exception as e:
            logger.exception("scan_id=%s PR creation failed: %s", scan_id, str(e))
            _emit_scan_event(scan_events_collection, scan_id, "pr", "PR creation failed", "failed", {"error": str(e)})
            # Try to recover from "Validation Failed" (422) by looking up an existing PR.
            existing2 = find_open_pull_request(repo, token, head=head_branch, base=base_branch)
            if existing2 and existing2.get("html_url"):
                pr_url = existing2.get("html_url")
                pr_number = existing2.get("number")
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

        # Proactive Quality Gate recovery loop (webhook-independent fallback)
        try:
            _proactive_qg_poll_and_recover(
                repo=repo,
                token=token,
                installation_id=installation_id,
                full_name=full_name,
                pr_number=int(pr_number) if pr_number is not None else None,
                head_branch=head_branch,
                scan_id=scan_id,
                fixes_collection=fixes_collection,
                prompts_collection=prompts_collection,
                scans_collection=scans_collection,
                scan_events_collection=scan_events_collection,
                scan_issues_collection=scan_issues_collection,
                scan_fix_attempts_collection=scan_fix_attempts_collection,
                github_app_installations_collection=github_app_installations_collection,
                workspaces_collection=workspaces_collection,
                sonar_connections_collection=sonar_connections_collection,
                quality_gate_retries_collection=quality_gate_retries_collection,
            )
        except Exception as e:
            logger.warning("scan_id=%s proactive QG loop error (non-blocking): %s", scan_id, str(e))
            _emit_scan_event(scan_events_collection, scan_id, "qg", "Proactive QG loop error (non-blocking)", "running", {"error": str(e)})

        return {"ok": True, "branch": head_branch, "pr": pr_url, "counters": counters.__dict__}

