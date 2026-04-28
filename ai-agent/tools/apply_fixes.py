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

    report_path = (
        Path(args.report).resolve()
        if args.report.strip()
        else (repo / ".shiftleft" / f"apply-report-{_now_slug()}.json")
    )
    _write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))

    print(f"Applied: {counters.applied} | Skipped: {counters.skipped} | Errors: {counters.errors}")
    print(f"Report: {report_path}")

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

