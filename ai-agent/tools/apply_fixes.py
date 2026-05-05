import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


@dataclass
class ApplyResult:
    applied: int = 0
    skipped: int = 0
    errors: int = 0


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize_relpath(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("/")


def _git(repo: Path, args: List[str]) -> None:
    subprocess.check_call(["git", "-C", str(repo), *args])


def _git_try(repo: Path, args: List[str]) -> Tuple[int, str]:
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return p.returncode, p.stdout


def _ensure_repo(repo: Path) -> None:
    if not repo.exists():
        raise SystemExit(f"Repo path does not exist: {repo}")
    if not (repo / ".git").exists():
        raise SystemExit(f"Not a git repo (missing .git): {repo}")


def _fetch_fixes(api_base: str, limit: int, refresh: bool) -> Dict[str, Any]:
    url = api_base.rstrip("/") + "/fixes"
    r = requests.get(url, params={"limit": limit, "refresh": str(refresh).lower()}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or "results" not in data:
        raise SystemExit("Unexpected /fixes response shape (expected dict with 'results').")
    return data


def _find_exact(haystack: str, needle: str) -> int:
    if not needle:
        return -1
    return haystack.find(needle)


def _apply_replace(file_path: Path, line: Optional[int], old_code: Optional[str], new_code: str) -> Tuple[bool, str]:
    if not file_path.exists():
        return False, f"file missing: {file_path}"

    text = _read_text(file_path)

    if old_code:
        idx = _find_exact(text, old_code)
        if idx < 0:
            return False, "old_code not found (safe-skip)"
        updated = text.replace(old_code, new_code, 1)
        _write_text(file_path, updated)
        return True, "replaced by exact old_code match"

    if isinstance(line, int) and line > 0:
        lines = text.splitlines(keepends=True)
        if line > len(lines):
            return False, f"line out of range (line={line}, total={len(lines)})"
        # Replace the whole line content (preserve newline)
        ending = "\n" if lines[line - 1].endswith("\n") else ""
        lines[line - 1] = new_code + ending
        _write_text(file_path, "".join(lines))
        return True, "replaced by line index (no old_code provided)"

    return False, "replace requires old_code or line (safe-skip)"


def _apply_delete(file_path: Path, line: Optional[int], old_code: Optional[str]) -> Tuple[bool, str]:
    if not file_path.exists():
        return False, f"file missing: {file_path}"

    text = _read_text(file_path)

    if old_code:
        idx = _find_exact(text, old_code)
        if idx < 0:
            return False, "old_code not found (safe-skip)"
        updated = text.replace(old_code, "", 1)
        _write_text(file_path, updated)
        return True, "deleted by exact old_code match"

    if isinstance(line, int) and line > 0:
        lines = text.splitlines(keepends=True)
        if line > len(lines):
            return False, f"line out of range (line={line}, total={len(lines)})"
        del lines[line - 1]
        _write_text(file_path, "".join(lines))
        return True, "deleted by line index (no old_code provided)"

    return False, "delete requires old_code or line (safe-skip)"


def _apply_insert(
    file_path: Path,
    mode: str,
    line: Optional[int],
    anchor: Optional[str],
    new_code: str,
) -> Tuple[bool, str]:
    if not file_path.exists():
        return False, f"file missing: {file_path}"

    text = _read_text(file_path)

    # Java-specific safety: avoid inserting duplicate constant names that already
    # exist in the file, which would break compilation.
    try:
        if file_path.suffix == ".java" and isinstance(new_code, str) and new_code:
            import re

            const_name_re = re.compile(
                r"(?m)^\s*(?:(public|protected|private)\s+)?static\s+final\s+[A-Za-z_$][\w$<>\[\]]*\s+([A-Z][A-Z0-9_]*)\b"
            )
            names = [m.group(2) for m in const_name_re.finditer(new_code)]
            if names:
                for n in names:
                    if re.search(
                        rf"(?m)^\s*(?:(public|protected|private)\s+)?static\s+final\s+.*\b{re.escape(n)}\b",
                        text,
                    ):
                        return False, f"java constant already defined: {n} (safe-skip)"
    except Exception:
        pass

    # Idempotency guard: if the exact chunk already exists, do not insert again.
    # This prevents duplicate member declarations (e.g., logger fields) when multiple
    # fixes generate the same insert_before/after operation for the same file.
    try:
        candidate = (new_code or "").strip()
        if candidate and candidate in text:
            return False, "chunk already present (safe-skip)"
    except Exception:
        pass

    if anchor:
        idx = _find_exact(text, anchor)
        if idx < 0:
            return False, "anchor(old_code) not found (safe-skip)"

        if mode == "insert_before":
            updated = text[:idx] + new_code + text[idx:]
            _write_text(file_path, updated)
            return True, "inserted before anchor"

        if mode == "insert_after":
            idx2 = idx + len(anchor)
            updated = text[:idx2] + new_code + text[idx2:]
            _write_text(file_path, updated)
            return True, "inserted after anchor"

        return False, f"unknown insert mode: {mode}"

    if isinstance(line, int) and line > 0:
        lines = text.splitlines(keepends=True)
        if line > len(lines) + 1:
            return False, f"line out of range (line={line}, total={len(lines)})"

        insert_at = line - 1
        if mode == "insert_after":
            insert_at = line

        chunk = new_code
        if chunk and not chunk.endswith("\n"):
            chunk += "\n"

        lines.insert(insert_at, chunk)
        _write_text(file_path, "".join(lines))
        return True, "inserted by line index (no anchor provided)"

    return False, "insert requires old_code(anchor) or line (safe-skip)"


def _apply_move(repo: Path, from_path: str, to_path: str) -> Tuple[bool, str]:
    src = repo / _normalize_relpath(from_path)
    dst = repo / _normalize_relpath(to_path)

    if not src.exists():
        return False, f"move source missing: {src}"

    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return True, f"moved {src} -> {dst}"


def _apply_change(repo: Path, ch: Dict[str, Any]) -> Tuple[bool, str]:
    op = ch.get("op")

    if op == "move":
        return _apply_move(repo, str(ch.get("from", "")), str(ch.get("to", "")))

    file_rel = _normalize_relpath(str(ch.get("file", "")))
    if not file_rel:
        return False, "missing file field"

    file_path = repo / file_rel
    line = ch.get("line")
    line_i = int(line) if isinstance(line, (int, float, str)) and str(line).strip().isdigit() else None

    old_code = ch.get("old_code")
    old_code_s = str(old_code) if isinstance(old_code, str) and old_code != "" else None

    if op == "replace":
        new_code = ch.get("new_code")
        if not isinstance(new_code, str):
            return False, "replace missing new_code"
        return _apply_replace(file_path, line_i, old_code_s, new_code)

    if op == "delete":
        return _apply_delete(file_path, line_i, old_code_s)

    if op in ("insert_before", "insert_after"):
        new_code = ch.get("new_code")
        if not isinstance(new_code, str):
            return False, f"{op} missing new_code"
        return _apply_insert(file_path, op, line_i, old_code_s, new_code)

    return False, f"unknown op: {op}"


def _inject_missing_imports_post_fix(repo: Path, fix_json: Dict[str, Any], issue: Dict[str, Any]) -> None:
    """
    Post-process a fix to auto-inject missing imports/logger fields.
    This prevents "cannot find symbol" errors when fixes reference undefined symbols.
    Works by calling _detect_and_add_missing_imports from fixes_service before changes are applied.
    """
    try:
        from app.services.fixes_service import _detect_and_add_missing_imports
    except ImportError:
        return  # fixes_service not available
    
    # Find the target file from the issue
    file_relpath = issue.get("file") or ""
    if not file_relpath or not file_relpath.endswith(".java"):
        return
    
    # Normalize the file path
    file_abs = repo / _normalize_relpath(str(file_relpath))
    if not file_abs.exists():
        return
    
    try:
        file_text = _read_text(file_abs)
        file_lines = file_text.splitlines(keepends=True)
        
        # Call the auto-import detection from fixes_service
        # This modifies fix_json["code_changes"] in-place by adding import/logger field changes
        _detect_and_add_missing_imports(fix_json, file_lines, str(file_relpath))
    except Exception:
        # Silently fail if import detection doesn't work
        pass


def apply_fixes_to_repo(
    repo: Path,
    fixes_payload: Dict[str, Any],
) -> Tuple[ApplyResult, Dict[str, Any]]:
    results: List[Dict[str, Any]] = fixes_payload.get("results") or []
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "applied": [],
        "skipped": [],
        "errors": [],
        "issues": [],
    }
    counters = ApplyResult()

    for item in results:
        issue = item.get("issue") or {}
        issue_key = issue.get("key")
        issue_msg = issue.get("message")
        fix_json = item.get("fix_json")
        if not isinstance(fix_json, dict):
            report["errors"].append(
                {"issue_key": issue_key, "error": "missing/invalid fix_json", "issue_message": issue_msg}
            )
            counters.errors += 1
            continue

        changes = fix_json.get("code_changes") or []
        if not isinstance(changes, list):
            report["errors"].append(
                {"issue_key": issue_key, "error": "fix_json.code_changes not a list", "issue_message": issue_msg}
            )
            counters.errors += 1
            continue

        report["issues"].append(
            {
                "issue_key": issue_key,
                "rule": issue.get("rule"),
                "file": issue.get("file"),
                "line": issue.get("line"),
                "message": issue_msg,
                "source": item.get("source"),
            }
        )

        # Auto-detect and inject missing imports/logger field for Java files
        # This prevents "cannot find symbol" errors when fixes introduce new class references
        try:
            _inject_missing_imports_post_fix(repo, fix_json, issue)
        except Exception as e:
            print(f"  ⚠️  Could not auto-detect imports for {issue_key}: {str(e)}")

        for ch in changes:
            if not isinstance(ch, dict):
                report["skipped"].append({"issue_key": issue_key, "reason": "change not a dict"})
                counters.skipped += 1
                continue

            ok, msg = _apply_change(repo, ch)
            entry = {
                "issue_key": issue_key,
                "op": ch.get("op"),
                "file": ch.get("file"),
                "line": ch.get("line"),
                "from": ch.get("from"),
                "to": ch.get("to"),
                "notes": ch.get("notes"),
                "result": msg,
            }
            if ok:
                report["applied"].append(entry)
                counters.applied += 1
            else:
                # treat “safe-skip” as skipped, everything else as error
                if "safe-skip" in msg:
                    report["skipped"].append(entry)
                    counters.skipped += 1
                else:
                    report["errors"].append(entry)
                    counters.errors += 1

    return counters, report


def _to_repo_relpath(repo: Path, file_path: str) -> str:
    """Convert absolute or analyzer-style path to repo-relative path."""
    if not file_path:
        return ""
    p = str(file_path)
    repo_str = str(repo)
    if p.startswith(repo_str):
        rel = p[len(repo_str):].lstrip("/\\")
        return rel.replace("\\", "/")
    if "/src/" in p:
        return p.split("/src/", 1)[1]
    if "src/" in p:
        return p.split("src/", 1)[1]
    return p.replace("\\", "/")


def _apply_programmatic_build_fix(repo: Path, fix: Dict[str, Any]) -> Tuple[bool, str]:
    """Translate build-fix descriptor into file edits and apply."""
    op = fix.get("op")
    file_rel = _normalize_relpath(str(fix.get("file", "")))
    file_path = repo / file_rel
    if not file_path.exists():
        return False, f"file missing: {file_rel}"
    try:
        if op == "insert_import":
            import_path = fix.get("import")
            if not import_path:
                return False, "missing import path"
            import_statement = f"import {import_path};"
            text = _read_text(file_path)
            lines = text.splitlines(keepends=True)
            package_line = None
            last_import = 0
            for i, ln in enumerate(lines, start=1):
                s = ln.strip()
                if s.startswith("package "):
                    package_line = i
                elif s.startswith("import "):
                    last_import = i
                elif s and not s.startswith("//") and not s.startswith("/*"):
                    break
            insert_line = last_import + 1 if last_import > 0 else (package_line + 1 if package_line else 1)
            old_code = lines[insert_line - 1].strip() if insert_line <= len(lines) else ""
            return _apply_insert(file_path, "insert_before", insert_line, old_code, import_statement)
        if op == "syntax_fix" and fix.get("error_type") == "missing_semicolon":
            line_no = fix.get("line")
            if not isinstance(line_no, int):
                return False, "invalid line for syntax fix"
            text = _read_text(file_path)
            lines = text.splitlines(keepends=True)
            if line_no > len(lines) or line_no < 1:
                return False, "line out of range"
            raw = lines[line_no - 1].rstrip("\n")
            if raw.strip().endswith(";"):
                return False, "semicolon already present"
            new_raw = raw + ";"
            return _apply_replace(file_path, line_no, raw, new_raw)
        return False, f"unsupported op: {op}"
    except Exception as e:
        return False, str(e)


def _create_diagnostic_pr_body(repo: Path, report: Dict[str, Any], branch_name: str) -> str:
    """Generate a detailed diagnostic PR description for build failures."""
    build_val = report.get("build_validation") or {}
    auto_fixes = report.get("auto_build_fixes") or []
    issues = report.get("issues") or []
    errors = build_val.get("errors") or []
    
    body = f"""## 🔍 AI-Generated Fixes - Diagnostic Report

**Status**: Build validation failed after {len(auto_fixes)} auto-fix attempts.

### Issues Attempted to Fix
{len(issues)} SonarQube issue(s) were targeted:

"""
    for issue in issues[:5]:
        body += f"- **{issue.get('rule', '?')}** ({issue.get('severity', '?')}): {issue.get('message', '')[:80]}\n"
        body += f"  File: `{issue.get('file', '?')}` (line {issue.get('line', '?')})\n"
    
    body += f"""
### Auto-Fix Attempts
Applied up to {len(auto_fixes)} auto-fix round(s):

"""
    for attempt in auto_fixes:
        attempt_num = attempt.get("attempt", "?")
        applied = attempt.get("applied", [])
        success_count = sum(1 for a in applied if a.get("ok"))
        body += f"**Attempt {attempt_num}**: {success_count}/{len(applied)} fixes applied\n"
        for item in applied[:3]:
            status = "✓" if item.get("ok") else "✗"
            fix_op = item.get("fix", {}).get("op", "?")
            body += f"  {status} {fix_op}: {item.get('msg', '')}\n"
    
    body += f"""
### Remaining Build Errors
Build still failing after auto-fixes. Errors found:

```
"""
    for error in errors[:10]:
        body += f"{error.get('file', '?')}:{error.get('line', '?')}: {error.get('type', '?')}\n"
        body += f"  {error.get('message', '?')}\n"
    body += """```

### Recommended Actions
1. **Review the builds logs** attached to CI
2. **Manual fixes needed**: The remaining errors may require manual intervention
3. **Enable more aggressive auto-fixes**: Consider expanding the auto-fix pool in `fixes_service.py`
4. **LLM-assisted fixes**: Re-run with `--refresh` to ask the LLM for fallback fixes

### Debug Info
- Branch: `""" + branch_name + """`
- Applied (initial AI fixes): """ + str(len(report.get("applied", []))) + """
- Build validation attempts: """ + str(len(auto_fixes)) + """
- Artifacts: See apply-report JSON in `.shiftleft/apply-report-*.json`
"""
    return body


def _create_diagnostic_pr(repo: Path, report: Dict[str, Any], branch_name: str, base_branch: str = "main") -> Tuple[bool, str]:
    """Create a diagnostic PR when auto-fixes fail."""
    try:
        pr_body = _create_diagnostic_pr_body(repo, report, branch_name)
        
        # Commit with diagnostic info if there are any changes
        code, out = _git_try(repo, ["status", "--porcelain"])
        if out.strip():
            _git(repo, ["add", "-A"])
            _git(repo, ["commit", "-m", f"chore(shiftleft): diagnostic - build failures ({_now_slug()})"])
            _git(repo, ["push", "-u", "origin", branch_name])
            return True, f"Diagnostic branch pushed: {branch_name}"
        else:
            return False, "No changes to diagnostic commit"
    except Exception as e:
        return False, f"Failed to create diagnostic PR: {str(e)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Shift-Left fixes and optionally prepare a PR branch.")
    parser.add_argument("--api-base", required=True, help="Backend base URL, e.g. https://...onrender.com")
    parser.add_argument("--repo", required=True, help="Path to local git checkout of target repo")
    parser.add_argument("--limit", type=int, default=5, help="How many fixes to fetch (default 5)")
    parser.add_argument("--refresh", action="store_true", help="Force regeneration (bypass cache)")
    parser.add_argument("--base-branch", default="main", help="Base branch name (default main)")
    parser.add_argument(
        "--branch",
        default="",
        help="Branch name to create/checkout before applying (default shiftleft/fixes-<timestamp>)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit changes after applying (does not push).",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Write report JSON to this path (default: <repo>/.shiftleft/apply-report-<ts>.json)",
    )

    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    _ensure_repo(repo)

    branch = args.branch.strip() or f"shiftleft/fixes-{_now_slug()}"

    # Prepare clean working tree
    code, out = _git_try(repo, ["status", "--porcelain"])
    if code != 0:
        print(out, file=sys.stderr)
        return 2
    if out.strip():
        print("Working tree not clean. Commit/stash changes before applying fixes.", file=sys.stderr)
        return 2

    _git(repo, ["fetch", "--all", "--prune"])
    _git(repo, ["checkout", args.base_branch])
    _git(repo, ["pull", "--ff-only"])
    _git(repo, ["checkout", "-B", branch])

    fixes_payload = _fetch_fixes(args.api_base, args.limit, args.refresh)
    counters, report = apply_fixes_to_repo(repo, fixes_payload)

    # Validate build after fixes are applied; auto-apply low-risk fixes if build fails
    print("Validating build after applying fixes...")
    try:
        from app.services.fixes_service import validate_build, generate_fix_for_build_error
        build_result = validate_build(str(repo), build_tool="maven")
        report["build_validation"] = build_result

        # If build failed, attempt low-risk auto-fixes up to N attempts.
        max_attempts = 3
        attempt = 0
        report.setdefault("auto_build_fixes", [])
        
        while attempt < max_attempts and build_result.get("status") != "success":
            attempt += 1
            applied_this_round = []
            errors = build_result.get("errors") or []
            if not errors:
                break
            print(f"\nAttempt {attempt}/{max_attempts}: generating low-risk fixes for {len(errors)} build errors...")
            
            for err in errors:
                err_file = err.get("file") or ""
                rel = _to_repo_relpath(repo, err_file)
                generated = generate_fix_for_build_error(err, rel)
                if not generated:
                    continue
                # Translate analyzer fix to repo edit and apply
                ok, msg = _apply_programmatic_build_fix(repo, generated)
                applied_this_round.append({"error": err, "fix": generated, "ok": ok, "msg": msg})
                status_sym = "✓" if ok else "✗"
                print(f"  {status_sym} {generated.get('op', '?')} for {rel}: {msg}")
            
            report["auto_build_fixes"].append({"attempt": attempt, "applied": applied_this_round})
            
            if not applied_this_round:
                print("  No low-risk fixes could be applied. Stopping auto-fix attempts.")
                break
            
            # Re-run build validation after applying fixes
            print(f"  Re-validating build after fixes...")
            build_result = validate_build(str(repo), build_tool="maven")
            report["build_validation"] = build_result

        if build_result["status"] == "success":
            print("\n✅ Build validation PASSED")
        else:
            print(f"\n⚠️  Build validation FAILED: {build_result['status']}")
            if build_result.get("errors"):
                print(f"Build errors found: {len(build_result['errors'])}")
                for error in build_result["errors"][:5]:  # Show first 5 errors
                    print(f"  - {error.get('file', '?')}:{error.get('line', '?')}")
                    print(f"    {error.get('message', 'Unknown error')}")
    except ImportError:
        print("⚠️  Could not import build validation (fixes_service not available)")
    except Exception as e:
        print(f"⚠️  Build validation error: {str(e)}")

    report_path = (
        Path(args.report).resolve()
        if args.report.strip()
        else (repo / ".shiftleft" / f"apply-report-{_now_slug()}.json")
    )
    _write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))

    print(f"Applied: {counters.applied} | Skipped: {counters.skipped} | Errors: {counters.errors}")
    print(f"Report: {report_path}")

    # If build validation failed after auto-fix attempts, create a diagnostic PR.
    build_val = report.get("build_validation")
    if build_val and build_val.get("status") != "success":
        print("\n⚠️ Build validation failed after auto-fix attempts.")
        status = build_val.get("status")
        print(f"Build status: {status}")
        if build_val.get("errors"):
            print(f"Build errors remaining: {len(build_val.get('errors'))}")
        
        # Attempt to create a diagnostic PR for inspection
        print("\n📋 Creating diagnostic PR branch with detailed failure information...")
        diag_branch = branch.replace("shiftleft/fixes-", "shiftleft/diagnostic-")
        try:
            _git(repo, ["checkout", "-b", diag_branch])
            ok, msg = _create_diagnostic_pr(repo, report, diag_branch, args.base_branch)
            if ok:
                print(f"✓ Diagnostic branch created: {diag_branch}")
                print(f"  Push with: git push -u origin {diag_branch}")
                print(f"  Then open a PR for manual review and troubleshooting.")
            else:
                print(f"✗ Could not create diagnostic PR: {msg}")
        except Exception as e:
            print(f"✗ Diagnostic PR creation failed: {str(e)}")
        
        return 5

    # If nothing changed, do not commit
    code2, out2 = _git_try(repo, ["status", "--porcelain"])
    if code2 != 0:
        print(out2, file=sys.stderr)
        return 3

    if not out2.strip():
        print("No file changes detected after applying fixes (nothing to commit).")
        return 4

    if args.commit:
        _git(repo, ["add", "-A"])
        _git(repo, ["commit", "-m", f"chore(shiftleft): apply fixes ({_now_slug()})"])
        print("Committed changes. Next: push branch and open PR.")
        return 0

    print("Changes applied but not committed. Re-run with --commit or commit manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

