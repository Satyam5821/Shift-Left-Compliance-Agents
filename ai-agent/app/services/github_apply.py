from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import re

from ..clients.github_app import (
    GitHubRef,
    delete_file,
    get_file_content,
    put_file_content,
)


@dataclass
class ApplyCounters:
    applied: int = 0
    skipped: int = 0
    errors: int = 0


def _normalize_relpath(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("/")


def _canon_line(s: str) -> str:
    """Normalize a line for tolerant matching: expand tabs, normalize quotes, and trim whitespace ends."""
    line = s.expandtabs(4).strip()
    return (
        line.replace("\u00A0", " ")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )


_JAVA_MEMBER_DECL_RE = re.compile(
    r"(?m)^\s*(?:(?:public|protected|private)\s+)(?:static\s+)?(?:final\s+)?(?:class|interface|enum|record|[A-Za-z_$][\w$<>\[\]]*)\b"
)

_JAVA_CONST_NAME_RE = re.compile(
    r"(?m)^\s*(?:(public|protected|private)\s+)?static\s+final\s+[A-Za-z_$][\w$<>\[\]]*\s+([A-Z][A-Z0-9_]*)\b"
)

_JAVA_METHOD_SIG_LINE_RE = re.compile(
    r"(?m)^\s*(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?[A-Za-z_$][\w$<>\[\]]*\s+[A-Za-z_$][\w$]*\s*\([^;]*\)\s*\{\s*$"
)

_JAVA_CLASS_DECL_RE = re.compile(
    r"(?m)^\s*(?:public|protected|private)?\s*(?:abstract\s+|final\s+)?(?:class|interface|enum|record)\s+[A-Za-z_$][\w$]*\b"
)


def _brace_depth_at(text: str, pos: int) -> int:
    """
    Heuristic brace depth at byte position `pos`.
    Depth increments on '{' and decrements on '}'.
    This does not attempt to fully parse Java strings/comments, but is good enough
    to prevent obviously invalid insertions like class members inside methods.
    """
    depth = 0
    for ch in text[: max(0, min(len(text), pos))]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    return depth


def _would_insert_member_inside_method(text: str, insert_pos: int, new_code: str) -> bool:
    # Only guard Java-like member declarations.
    if not new_code or not _JAVA_MEMBER_DECL_RE.search(new_code):
        return False
    # In a typical Java file:
    #   depth 0: outside any type
    #   depth 1: inside class/interface body
    #   depth 2+: inside method / block
    return _brace_depth_at(text, insert_pos) >= 2


def _find_java_class_body_insert_pos(text: str) -> int:
    """
    Best-effort insertion point for class members.

    Returns the byte offset just after the class declaration line so new fields
    are inserted at class scope instead of inside a method.
    """
    m = _JAVA_CLASS_DECL_RE.search(text or "")
    if not m:
        return -1
    line_end = text.find("\n", m.end())
    if line_end < 0:
        return len(text)
    return line_end + 1


def _extract_java_constant_names(code: str) -> List[str]:
    if not code:
        return []
    return [m.group(2) for m in _JAVA_CONST_NAME_RE.finditer(code)]


def _references_any(text: str, names: List[str]) -> bool:
    if not text or not names:
        return False
    for n in names:
        if re.search(rf"(?<![\w$]){re.escape(n)}(?![\w$])", text):
            return True
    return False


def _java_quick_sanity(text: str) -> Optional[str]:
    """
    Very lightweight Java sanity checks to prevent obviously broken patches.
    Not a parser. Intended to catch the exact class of failures seen in PRs:
    duplicated method signatures / duplicated member insertions.
    """
    if not isinstance(text, str) or not text:
        return None

    # 1) Duplicated consecutive method signature lines (common when an insert patch
    # accidentally includes the method signature and is applied multiple times).
    lines = text.splitlines()
    prev = None
    for ln in lines:
        if prev is not None and ln == prev and _JAVA_METHOD_SIG_LINE_RE.match(ln):
            return "java sanity check failed: duplicated consecutive method signature line"
        prev = ln

    # 2) Ensure braces never go negative in our simple brace scan.
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "java sanity check failed: brace underflow (extra closing brace)"

    # 3) Duplicate constant names (static final X NAME) anywhere in the class.
    # This catches the exact build-breaker seen with ERROR_READING_FILE_MESSAGE.
    try:
        names = _extract_java_constant_names(text)
        if names:
            seen: set = set()
            for n in names:
                if n in seen:
                    return f"java sanity check failed: duplicate constant name {n}"
                seen.add(n)
    except Exception:
        pass

    return None


def _find_span_tolerant(text: str, old_code: str) -> Tuple[int, int, str]:
    """
    Locate `old_code` inside `text` and return a byte span [start, end) in the
    original `text`, plus a short reason string.

    Matching strategy:
      1. Exact substring match (fast, preferred).
      2. Line-oriented match with whitespace tolerance: tabs expanded, leading/
         trailing whitespace ignored. Internal content must still match.

    Returns (-1, -1, reason) on miss.
    """
    if not old_code:
        return -1, -1, "empty old_code"

    # 1) Exact
    idx = text.find(old_code)
    if idx >= 0:
        return idx, idx + len(old_code), "exact"

    # 2) Tolerant (line-based)
    text_lines_ke = text.splitlines(keepends=True)
    offsets: List[int] = []
    acc = 0
    for ln in text_lines_ke:
        offsets.append(acc)
        acc += len(ln)
    offsets.append(acc)  # sentinel "end of file"

    needle_lines = old_code.splitlines()
    while needle_lines and not needle_lines[0].strip():
        needle_lines.pop(0)
    while needle_lines and not needle_lines[-1].strip():
        needle_lines.pop()
    if not needle_lines:
        return -1, -1, "old_code has no content after trim"

    canon_text = [_canon_line(ln) for ln in text.splitlines()]
    canon_needle = [_canon_line(ln) for ln in needle_lines]

    n = len(canon_needle)
    m = len(canon_text)
    if n == 0 or n > m:
        return -1, -1, "old_code larger than file"

    # Prefer the first match; if multiple exist, consider it ambiguous and refuse
    # only when we have a very short (<=1 line) needle.
    matches: List[int] = []
    for i in range(m - n + 1):
        if canon_text[i : i + n] == canon_needle:
            matches.append(i)
            if len(matches) >= 2 and n <= 1:
                # Single-line anchor with multiple matches is too risky
                return -1, -1, "ambiguous single-line anchor (multiple matches)"

    if not matches:
        return -1, -1, "no tolerant match"

    i = matches[0]
    start = offsets[i]
    end = offsets[i + n]
    return start, end, "tolerant"


def _apply_replace_text(
    text: str, line: Optional[int], old_code: Optional[str], new_code: str
) -> Tuple[bool, str, str]:
    if old_code:
        start, end, how = _find_span_tolerant(text, old_code)
        if start < 0 and isinstance(line, int) and line > 0:
            fallback_lines = text.splitlines(keepends=True)
            needle_lines = old_code.splitlines()
            while needle_lines and not needle_lines[0].strip():
                needle_lines.pop(0)
            while needle_lines and not needle_lines[-1].strip():
                needle_lines.pop()
            if needle_lines:
                line_count = len(needle_lines)
                if line <= len(fallback_lines) and line + line_count - 1 <= len(fallback_lines):
                    file_slice = fallback_lines[line - 1 : line - 1 + line_count]
                    if [ _canon_line(ln) for ln in file_slice ] == [ _canon_line(ln) for ln in needle_lines ]:
                        if file_slice and file_slice[-1].endswith("\n") and not new_code.endswith("\n"):
                            new_code = new_code + "\n"
                        insert_pos = sum(len(l) for l in fallback_lines[: line - 1])
                        if _would_insert_member_inside_method(text, insert_pos, new_code):
                            return False, text, "unsafe insert/replace of class member inside method (safe-skip)"
                        fallback_lines[line - 1 : line - 1 + line_count] = [new_code]
                        return True, "".join(fallback_lines), "replaced by line fallback"
        if start < 0:
            return False, text, f"old_code not found (safe-skip: {how})"
        if _would_insert_member_inside_method(text, start, new_code):
            return False, text, "unsafe insert/replace of class member inside method (safe-skip)"
        return True, text[:start] + new_code + text[end:], f"replaced by {how} match"

    if isinstance(line, int) and line > 0:
        lines = text.splitlines(keepends=True)
        if line > len(lines):
            return False, text, f"line out of range (line={line}, total={len(lines)})"
        ending = "\n" if lines[line - 1].endswith("\n") else ""
        lines[line - 1] = new_code + ending
        return True, "".join(lines), "replaced by line index (no old_code provided)"

    return False, text, "replace requires old_code or line (safe-skip)"


def _apply_delete_text(
    text: str, line: Optional[int], old_code: Optional[str]
) -> Tuple[bool, str, str]:
    if old_code:
        start, end, how = _find_span_tolerant(text, old_code)
        if start < 0 and isinstance(line, int) and line > 0:
            fallback_lines = text.splitlines(keepends=True)
            needle_lines = old_code.splitlines()
            while needle_lines and not needle_lines[0].strip():
                needle_lines.pop(0)
            while needle_lines and not needle_lines[-1].strip():
                needle_lines.pop()
            if needle_lines:
                line_count = len(needle_lines)
                if line <= len(fallback_lines) and line + line_count - 1 <= len(fallback_lines):
                    file_slice = fallback_lines[line - 1 : line - 1 + line_count]
                    if [ _canon_line(ln) for ln in file_slice ] == [ _canon_line(ln) for ln in needle_lines ]:
                        del fallback_lines[line - 1 : line - 1 + line_count]
                        return True, "".join(fallback_lines), "deleted by line fallback"
        if start < 0:
            return False, text, f"old_code not found (safe-skip: {how})"
        return True, text[:start] + text[end:], f"deleted by {how} match"

    if isinstance(line, int) and line > 0:
        lines = text.splitlines(keepends=True)
        if line > len(lines):
            return False, text, f"line out of range (line={line}, total={len(lines)})"
        del lines[line - 1]
        return True, "".join(lines), "deleted by line index (no old_code provided)"

    return False, text, "delete requires old_code or line (safe-skip)"


def _apply_insert_text(
    text: str,
    mode: str,
    line: Optional[int],
    anchor: Optional[str],
    new_code: str,
) -> Tuple[bool, str, str]:
    # Java-specific safety/idempotency: if this insert introduces Java constants that
    # are already defined in the file, skip the insert to avoid compilation errors
    # like "variable X is already defined".
    try:
        if isinstance(text, str) and isinstance(new_code, str):
            names = _extract_java_constant_names(new_code)
            if names:
                for n in names:
                    if re.search(rf"(?m)^\s*(?:(?:public|protected|private)\s+)?static\s+final\s+.*\b{re.escape(n)}\b", text):
                        return False, text, f"java constant already defined: {n} (safe-skip)"
    except Exception:
        # Fall back to generic behavior if detection fails.
        pass

    # Idempotency guard: if the exact chunk (trimmed) already exists in the file,
    # do not insert it again. This prevents duplicate logger fields/imports when
    # multiple issues generate the same insert_before patch.
    try:
        candidate = (new_code or "").strip()
        if candidate:
            s, e, how0 = _find_span_tolerant(text, candidate)
            if s >= 0:
                return False, text, f"chunk already present (safe-skip: {how0})"
    except Exception:
        # If the guard fails for any reason, fall back to normal insertion.
        pass

    def _insert_chunk_at(text: str, pos: int, chunk: str) -> Tuple[bool, str, str]:
        if mode == "insert_before":
            if chunk and not chunk.endswith("\n"):
                chunk = chunk + "\n"
            if _would_insert_member_inside_method(text, pos, chunk):
                return False, text, "unsafe insert of class member inside method (safe-skip)"
            return True, text[:pos] + chunk + text[pos:], f"inserted before anchor ({how})"
        if mode == "insert_after":
            if chunk and not chunk.startswith("\n"):
                chunk = "\n" + chunk
            if _would_insert_member_inside_method(text, pos, chunk):
                return False, text, "unsafe insert of class member inside method (safe-skip)"
            return True, text[:pos] + chunk + text[pos:], f"inserted after anchor ({how})"
        return False, text, f"unknown insert mode: {mode}"

    if anchor:
        start, end, how = _find_span_tolerant(text, anchor)
        if start < 0 and isinstance(line, int) and line > 0:
            fallback_lines = text.splitlines(keepends=True)
            needle_lines = anchor.splitlines()
            while needle_lines and not needle_lines[0].strip():
                needle_lines.pop(0)
            while needle_lines and not needle_lines[-1].strip():
                needle_lines.pop()
            if needle_lines:
                line_count = len(needle_lines)
                if line <= len(fallback_lines) and line + line_count - 1 <= len(fallback_lines):
                    file_slice = fallback_lines[line - 1 : line - 1 + line_count]
                    if [_canon_line(ln) for ln in file_slice] == [_canon_line(ln) for ln in needle_lines]:
                        insert_at = line - 1 if mode == "insert_before" else line
                        chunk = new_code
                        if chunk and not chunk.endswith("\n"):
                            chunk += "\n"
                        if _would_insert_member_inside_method(text, sum(len(l) for l in fallback_lines[:insert_at]), chunk):
                            return False, text, "unsafe insert of class member inside method (safe-skip)"
                        fallback_lines.insert(insert_at, chunk)
                        return True, "".join(fallback_lines), f"inserted by line fallback ({mode})"

        # If the anchor is wrong but the change is clearly a Java class member,
        # fall back to a class-scope insertion so logger fields / helper members
        # do not get dropped just because the LLM picked a bad anchor line.
        if start < 0 and mode == "insert_before" and _JAVA_MEMBER_DECL_RE.search(new_code):
            class_pos = _find_java_class_body_insert_pos(text)
            if class_pos >= 0 and not _would_insert_member_inside_method(text, class_pos, new_code):
                chunk = new_code
                if chunk and not chunk.endswith("\n"):
                    chunk += "\n"
                return True, text[:class_pos] + chunk + text[class_pos:], "inserted by class-scope fallback"

        if start < 0:
            return False, text, f"anchor(old_code) not found (safe-skip: {how})"
        return _insert_chunk_at(text, start if mode == "insert_before" else end, new_code)

    if isinstance(line, int) and line > 0:
        lines = text.splitlines(keepends=True)
        if line > len(lines) + 1:
            return False, text, f"line out of range (line={line}, total={len(lines)})"
        insert_at = line - 1
        if mode == "insert_after":
            insert_at = line
        chunk = new_code
        if chunk and not chunk.endswith("\n"):
            chunk += "\n"
        lines.insert(insert_at, chunk)
        return True, "".join(lines), "inserted by line index (no anchor provided)"

    return False, text, "insert requires old_code(anchor) or line (safe-skip)"


def apply_code_changes_via_github_api(
    repo: GitHubRef,
    token: str,
    base_ref: str,
    branch: str,
    code_changes: List[Dict[str, Any]],
    commit_message_prefix: str = "chore(shiftleft): apply fixes",
) -> Tuple[ApplyCounters, List[Dict[str, Any]]]:
    """
    Applies code changes to `branch` (branch must already exist).
    Returns counters and a report list for PR body.
    """
    counters = ApplyCounters()
    report: List[Dict[str, Any]] = []
    blocked_symbols_by_file: Dict[str, List[str]] = {}

    for ch in code_changes:
        if not isinstance(ch, dict):
            counters.skipped += 1
            report.append({"ok": False, "reason": "change not a dict"})
            continue

        op = ch.get("op")
        if op == "move":
            # Move via API: create new path with same content then delete old
            src = _normalize_relpath(str(ch.get("from") or ""))
            dst = _normalize_relpath(str(ch.get("to") or ""))
            if not src or not dst:
                counters.errors += 1
                report.append({"ok": False, "op": "move", "reason": "missing from/to"})
                continue

            src_text, src_sha = get_file_content(repo, token, src, ref=branch)
            if src_text is None or not src_sha:
                counters.skipped += 1
                report.append({"ok": False, "op": "move", "from": src, "to": dst, "reason": "source missing"})
                continue

            # create/overwrite destination
            _, dst_sha = get_file_content(repo, token, dst, ref=branch)
            put_file_content(
                repo,
                token,
                dst,
                branch=branch,
                message=f"{commit_message_prefix}: move {src} -> {dst}",
                text=src_text,
                sha=dst_sha,
            )
            delete_file(
                repo,
                token,
                src,
                branch=branch,
                message=f"{commit_message_prefix}: delete moved {src}",
                sha=src_sha,
            )
            counters.applied += 1
            report.append({"ok": True, "op": "move", "from": src, "to": dst})
            continue

        path = _normalize_relpath(str(ch.get("file") or ""))
        if not path:
            counters.errors += 1
            report.append({"ok": False, "op": op, "reason": "missing file"})
            continue

        text, sha = get_file_content(repo, token, path, ref=branch)
        if text is None or not sha:
            counters.skipped += 1
            report.append({"ok": False, "op": op, "file": path, "reason": "file missing"})
            continue

        line = ch.get("line")
        line_i = int(line) if isinstance(line, int) else None
        old_code = ch.get("old_code") if isinstance(ch.get("old_code"), str) and ch.get("old_code") else None

        ok = False
        new_text = text
        msg = "unknown"

        if op == "replace":
            new_code = ch.get("new_code")
            if not isinstance(new_code, str):
                counters.errors += 1
                report.append({"ok": False, "op": op, "file": path, "reason": "missing new_code"})
                continue
            blocked = blocked_symbols_by_file.get(path) or []
            if blocked and _references_any(new_code, blocked):
                counters.skipped += 1
                report.append(
                    {
                        "ok": False,
                        "op": op,
                        "file": path,
                        "reason": "depends on skipped Java constant insertion (safe-skip)",
                    }
                )
                continue
            # If new_code is empty, treat as delete when old_code is present.
            if new_code.strip() == "" and old_code:
                ok, new_text, msg = _apply_delete_text(text, line_i, old_code)
            else:
                ok, new_text, msg = _apply_replace_text(text, line_i, old_code, new_code)
        elif op == "delete":
            ok, new_text, msg = _apply_delete_text(text, line_i, old_code)
        elif op in ("insert_before", "insert_after"):
            new_code = ch.get("new_code")
            if not isinstance(new_code, str):
                counters.errors += 1
                report.append({"ok": False, "op": op, "file": path, "reason": "missing new_code"})
                continue
            blocked = blocked_symbols_by_file.get(path) or []
            if blocked and _references_any(new_code, blocked):
                counters.skipped += 1
                report.append(
                    {
                        "ok": False,
                        "op": op,
                        "file": path,
                        "reason": "depends on skipped Java constant insertion (safe-skip)",
                    }
                )
                continue
            ok, new_text, msg = _apply_insert_text(text, op, line_i, old_code, new_code)
        else:
            counters.skipped += 1
            report.append({"ok": False, "op": op, "file": path, "reason": "unknown op"})
            continue

        if not ok:
            # If we skip an unsafe Java member insertion, also block later edits that
            # would start referencing the missing symbols (prevents cannot-find-symbol builds).
            if isinstance(ch.get("new_code"), str) and "safe-skip" in msg:
                # If we skipped a chunk that looks like it was introducing constants,
                # block subsequent edits that would reference those now-missing symbols.
                names = _extract_java_constant_names(ch["new_code"])
                if names:
                    blocked_symbols_by_file[path] = sorted(
                        set((blocked_symbols_by_file.get(path) or []) + names)
                    )
            if "safe-skip" in msg:
                counters.skipped += 1
                report.append({"ok": False, "op": op, "file": path, "reason": msg})
            else:
                counters.errors += 1
                report.append({"ok": False, "op": op, "file": path, "reason": msg})
            continue

        # Final safety: refuse to write obviously broken Java to the branch.
        if path.endswith(".java"):
            sanity_err = _java_quick_sanity(new_text)
            if sanity_err:
                counters.skipped += 1
                report.append({"ok": False, "op": op, "file": path, "reason": f"{sanity_err} (safe-skip)"})
                continue

        put_file_content(
            repo,
            token,
            path,
            branch=branch,
            message=f"{commit_message_prefix}: {op} {path}",
            text=new_text,
            sha=sha,
        )
        counters.applied += 1
        report.append({"ok": True, "op": op, "file": path, "reason": msg})

    return counters, report


def apply_code_changes_via_github_api_atomic(
    repo: GitHubRef,
    token: str,
    base_ref: str,
    branch: str,
    code_changes: List[Dict[str, Any]],
    commit_message_prefix: str = "chore(shiftleft): apply fixes",
) -> Tuple[ApplyCounters, List[Dict[str, Any]]]:
    """
    Atomic apply:
    - Evaluate all operations against an in-memory view of the repo at `branch`
    - If any operation cannot be applied safely, apply NOTHING
    - Otherwise, write all modified files (and moves) via GitHub Contents API

    This prevents partial fixes like:
      - replace introduces CONST_NAME but insert CONST_NAME was skipped
      - replace calls helper method but insert of helper method was skipped
    """
    counters = ApplyCounters()
    report: List[Dict[str, Any]] = []

    if not isinstance(code_changes, list) or not code_changes:
        return counters, report

    # Load required file contents once from the current branch
    originals: Dict[str, Tuple[str, str]] = {}  # path -> (text, sha)

    def _load(path: str) -> Tuple[Optional[str], Optional[str]]:
        if path in originals:
            t, s = originals[path]
            return t, s
        t, s = get_file_content(repo, token, path, ref=branch)
        if isinstance(t, str) and isinstance(s, str) and s:
            originals[path] = (t, s)
        return t, s

    # In-memory working tree for file contents (only for touched files)
    working: Dict[str, str] = {}
    sha_by_path: Dict[str, str] = {}

    staged_moves: List[Tuple[str, str]] = []  # (src, dst)

    # Preload + stage
    for ch in code_changes:
        if not isinstance(ch, dict):
            counters.errors += 1
            report.append({"ok": False, "reason": "change not a dict"})
            continue

        op = ch.get("op")
        if op == "move":
            src = _normalize_relpath(str(ch.get("from") or ""))
            dst = _normalize_relpath(str(ch.get("to") or ""))
            if not src or not dst:
                counters.errors += 1
                report.append({"ok": False, "op": "move", "reason": "missing from/to"})
                continue
            src_text, src_sha = _load(src)
            if src_text is None or not src_sha:
                counters.skipped += 1
                report.append({"ok": False, "op": "move", "from": src, "to": dst, "reason": "source missing"})
                continue
            staged_moves.append((src, dst))
            # ensure content is in working under src so later ops can refer to it if needed
            working[src] = src_text
            sha_by_path[src] = src_sha
            continue

        path = _normalize_relpath(str(ch.get("file") or ""))
        if not path:
            counters.errors += 1
            report.append({"ok": False, "op": op, "reason": "missing file"})
            continue
        text, sha = _load(path)
        if text is None or not sha:
            counters.skipped += 1
            report.append({"ok": False, "op": op, "file": path, "reason": "file missing"})
            continue
        working[path] = text
        sha_by_path[path] = sha

    if counters.errors or counters.skipped:
        # Atomic: if anything failed to stage, do nothing.
        return counters, report

    # Apply operations in-memory
    for ch in code_changes:
        op = ch.get("op")
        if op == "move":
            src = _normalize_relpath(str(ch.get("from") or ""))
            dst = _normalize_relpath(str(ch.get("to") or ""))
            src_text = working.get(src)
            if src_text is None:
                counters.skipped += 1
                report.append({"ok": False, "op": "move", "from": src, "to": dst, "reason": "source not staged"})
                continue
            # Move in working view: dst gets src content; src remains for now (deleted at write stage)
            working[dst] = src_text
            continue

        path = _normalize_relpath(str(ch.get("file") or ""))
        text = working.get(path)
        if text is None:
            counters.skipped += 1
            report.append({"ok": False, "op": op, "file": path, "reason": "file not staged"})
            continue

        line = ch.get("line")
        line_i = int(line) if isinstance(line, int) else None
        old_code = ch.get("old_code") if isinstance(ch.get("old_code"), str) and ch.get("old_code") else None

        ok = False
        new_text = text
        msg = "unknown"

        if op == "replace":
            new_code = ch.get("new_code")
            if not isinstance(new_code, str):
                counters.errors += 1
                report.append({"ok": False, "op": op, "file": path, "reason": "missing new_code"})
                continue
            ok, new_text, msg = _apply_replace_text(text, line_i, old_code, new_code)
        elif op == "delete":
            ok, new_text, msg = _apply_delete_text(text, line_i, old_code)
        elif op in ("insert_before", "insert_after"):
            new_code = ch.get("new_code")
            if not isinstance(new_code, str):
                counters.errors += 1
                report.append({"ok": False, "op": op, "file": path, "reason": "missing new_code"})
                continue
            ok, new_text, msg = _apply_insert_text(text, op, line_i, old_code, new_code)
        else:
            counters.errors += 1
            report.append({"ok": False, "op": op, "file": path, "reason": "unknown op"})
            continue

        if not ok:
            counters.skipped += 1
            report.append({"ok": False, "op": op, "file": path, "reason": msg})
            continue

        # Java sanity check after each successful change
        if path.endswith(".java"):
            sanity = _java_quick_sanity(new_text)
            if sanity:
                counters.skipped += 1
                report.append({"ok": False, "op": op, "file": path, "reason": sanity})
                # Atomic: mark failure; don't keep modified content
                continue

        working[path] = new_text
        counters.applied += 1
        report.append({"ok": True, "op": op, "file": path, "reason": msg})

    # Atomic: if any op was skipped/errored, apply nothing
    if counters.errors or counters.skipped:
        # reset applied counter because we didn't write anything
        counters.applied = 0
        return counters, report

    # Write modified files / moved files
    try:
        # First write destinations (including move destinations)
        for path, new_text in working.items():
            # Only write files that existed originally OR are move destinations
            orig = originals.get(path)
            sha = sha_by_path.get(path) if path in sha_by_path else None
            if orig is not None:
                old_text, old_sha = orig
                if new_text == old_text:
                    continue
                put_file_content(
                    repo,
                    token,
                    path,
                    branch=branch,
                    message=f"{commit_message_prefix}: update {path}",
                    text=new_text,
                    sha=old_sha,
                )
            else:
                # likely a move destination; overwrite/create
                _, existing_sha = get_file_content(repo, token, path, ref=branch)
                put_file_content(
                    repo,
                    token,
                    path,
                    branch=branch,
                    message=f"{commit_message_prefix}: create {path}",
                    text=new_text,
                    sha=existing_sha,
                )

        # Then delete move sources
        for src, dst in staged_moves:
            # Only delete if src != dst and src existed
            if src == dst:
                continue
            src_sha = sha_by_path.get(src) or (originals.get(src) or ("", ""))[1]
            if src_sha:
                delete_file(
                    repo,
                    token,
                    src,
                    branch=branch,
                    message=f"{commit_message_prefix}: delete moved {src}",
                    sha=src_sha,
                )
    except Exception as e:
        counters.errors += 1
        report.append({"ok": False, "reason": f"write failed: {str(e)}"})
        return counters, report

    return counters, report

