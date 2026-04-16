import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from ..clients.github_app import GitHubRef
from ..clients.github_context import (
    build_context_snippet,
    component_to_relpath,
    read_github_file_lines,
)
from .llm_fix import generate_fix_text


logger = logging.getLogger("shiftleft.fixes")


def normalize_repo_relpath(path: Optional[str]) -> str:
    """
    Normalize Sonar/GitHub paths to a repo-relative path.
    Examples:
      "owner_repo:src/main/java/A.java" -> "src/main/java/A.java"
      "src\\main\\java\\A.java"         -> "src/main/java/A.java"
    """
    if not path or not isinstance(path, str):
        return ""
    p = path.strip()
    if ":" in p and not p.startswith(("http://", "https://")):
        # Sonar "component" format: "<projectKey>:<relpath>"
        p = p.split(":", 1)[1]
    p = p.replace("\\", "/").lstrip("/")
    # Sometimes models include a repo/project prefix like:
    # "SomeProject/src/main/java/..." → normalize to "src/main/java/..."
    src_marker = "/src/"
    if src_marker in p:
        p = p.split(src_marker, 1)[1]
        p = f"src/{p}"
    elif p.startswith("src/"):
        pass
    return p


def extract_json_from_text(text: str):
    if not isinstance(text, str):
        return None

    s = text.strip()

    # Handle fenced blocks: ```json ... ``` or ``` ... ```
    if s.startswith("```"):
        parts = s.split("```")
        if len(parts) >= 3:
            inner = parts[1].strip()
            # Drop an optional language tag line
            if "\n" in inner:
                first_line, rest = inner.split("\n", 1)
                if first_line.strip().lower() in ("json", "javascript"):
                    s = rest.strip()
                else:
                    s = inner.strip()
            else:
                s = inner.strip()

    try:
        return json.loads(s)
    except Exception:
        return None


def ensure_fix_json(issue_obj: Dict[str, Any], raw_text: str):
    """
    Always return a dict with keys: problem, solution, code_changes.
    No extra LLM call is made here (token-safe).
    """
    parsed = extract_json_from_text(raw_text) if isinstance(raw_text, str) else None
    if isinstance(parsed, dict):
        # Some models still put a full JSON object inside "solution" as a string.
        # If so, prefer that nested object.
        try:
            sol = parsed.get("solution")
            if isinstance(sol, str):
                sol_str = sol.strip()
                # Attempt strict JSON parse first
                if sol_str.startswith("{") and '"code_changes"' in sol_str:
                    nested = extract_json_from_text(sol_str)
                    if isinstance(nested, dict) and isinstance(nested.get("code_changes"), list):
                        parsed = nested
                # If code_changes empty but solution contains JSON, unwrap it too
                if (
                    isinstance(parsed.get("code_changes"), list)
                    and len(parsed.get("code_changes")) == 0
                    and sol_str
                    and ("\"code_changes\"" in sol_str or "code_changes" in sol_str)
                ):
                    nested2 = extract_json_from_text(sol_str)
                    if isinstance(nested2, dict) and isinstance(nested2.get("code_changes"), list):
                        parsed = nested2
        except Exception:
            pass

        parsed.setdefault("problem", issue_obj.get("message") or "Sonar issue")
        parsed.setdefault("solution", "")
        parsed.setdefault("code_changes", [])
        if not isinstance(parsed.get("code_changes"), list):
            parsed["code_changes"] = []

        normalized = []
        for ch in parsed.get("code_changes", []):
            if not isinstance(ch, dict):
                continue
            op = ch.get("op") or ("move" if (ch.get("from") and ch.get("to")) else "replace")
            out = dict(ch)
            out["op"] = op

            # Normalize paths for deterministic scripting
            if out["op"] == "move":
                out["from"] = normalize_repo_relpath(out.get("from"))
                out["to"] = normalize_repo_relpath(out.get("to"))
                # move shouldn't carry file/line/code fields
                out.pop("file", None)
                out.pop("line", None)
                out.pop("old_code", None)
                out.pop("new_code", None)
            else:
                out["file"] = normalize_repo_relpath(out.get("file"))
                # Remove move-only keys if present
                out.pop("from", None)
                out.pop("to", None)

            normalized.append(out)
        parsed["code_changes"] = normalized

        # Reject clearly unsafe placeholder-based patches to avoid breaking builds.
        try:
            placeholder_markers = [
                "nested try block code",
                "nested catch block code",
                "old code here",
                "TODO",
            ]
            blob = json.dumps(parsed, ensure_ascii=False)
            if any(m.lower() in blob.lower() for m in placeholder_markers):
                # Keep the guidance text, but drop code changes so we don't apply unsafe patches.
                logger.warning(
                    "Sanitized placeholder-based code_changes for issue=%s message=%s",
                    issue_obj.get("key"),
                    issue_obj.get("message"),
                )
                parsed["code_changes"] = []
        except Exception:
            pass

        return parsed

    return {
        "problem": issue_obj.get("message") or "Sonar issue",
        "solution": raw_text if isinstance(raw_text, str) else str(raw_text),
        "code_changes": [],
    }


def get_prompt_template_for_issue(
    prompts_collection,
    rule_key: Optional[str],
) -> str:
    if rule_key:
        prompt_doc = prompts_collection.find_one({"rule_key": rule_key})
        if prompt_doc and prompt_doc.get("prompt_template"):
            return prompt_doc["prompt_template"]

    return """
You are a senior Java developer.

Fix this SonarQube issue:

Issue: {message}
Rule: {rule}
File: {file}
Line: {line}
"""


def generate_fix_for_issue(
    issue: Dict[str, Any],
    prompts_collection,
    repo: Optional[GitHubRef] = None,
    token: Optional[str] = None,
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    rule_key = issue.get("rule")
    prompt_template = get_prompt_template_for_issue(prompts_collection, rule_key)

    file_relpath = normalize_repo_relpath(component_to_relpath(issue.get("component")))
    code_context = build_context_snippet(
        file_relpath,
        issue.get("line"),
        repo=repo,
        token=token,
        ref=ref,
    )

    # Diagnostic: surface whether we actually have real file context for the LLM.
    logger.info(
        "generate_fix issue=%s rule=%s file=%s line=%s context_chars=%d",
        issue.get("key"),
        rule_key,
        file_relpath or "<empty>",
        issue.get("line"),
        len(code_context or ""),
    )

    fix_text, llm_meta = generate_fix_text(
        issue=issue,
        prompt_template=prompt_template,
        rule_key=str(rule_key),
        code_context=code_context,
        file_relpath=file_relpath,
    )

    logger.info(
        "generate_fix issue=%s provider=%s raw_len=%d raw_head=%r",
        issue.get("key"),
        (llm_meta or {}).get("provider"),
        len(fix_text or ""),
        (fix_text or "")[:400],
    )

    fix_json = ensure_fix_json(issue, fix_text)

    # Deterministic post-process for common Java package rename:
    # - Replace "package ...Services" -> "package ...services"
    # - Suggest folder move "Services" -> "services"
    try:
        msg = str(issue.get("message", "")).lower()
        if "package" in msg and "rename" in msg and isinstance(fix_json, dict):
            changes = fix_json.get("code_changes") or []
            if isinstance(changes, list) and file_relpath:
                # Ensure package statement replace
                has_pkg_replace = any(
                    isinstance(c, dict)
                    and c.get("op") == "replace"
                    and isinstance(c.get("old_code"), str)
                    and c.get("old_code", "").lstrip().startswith("package ")
                    for c in changes
                )
                if not has_pkg_replace:
                    file_lines = read_github_file_lines(
                        file_relpath, repo=repo, token=token, ref=ref
                    ) or []
                    pkg_line_no = None
                    pkg_line = None
                    for idx, line in enumerate(file_lines, start=1):
                        stripped = line.strip()
                        if stripped.startswith("package "):
                            pkg_line_no = idx
                            pkg_line = stripped
                            break
                    if pkg_line_no and pkg_line and ".Services" in pkg_line:
                        changes.append(
                            {
                                "op": "replace",
                                "file": file_relpath,
                                "line": pkg_line_no,
                                "old_code": pkg_line,
                                "new_code": pkg_line.replace(".Services", ".services"),
                                "notes": "Make package name lowercase to satisfy rule.",
                            }
                        )

                # Ensure folder move
                if "/Services/" in file_relpath:
                    has_move = any(isinstance(c, dict) and c.get("op") == "move" for c in changes)
                    if not has_move:
                        changes.append(
                            {
                                "op": "move",
                                "from": file_relpath.rsplit("/", 1)[0],
                                "to": file_relpath.replace("/Services/", "/services/").rsplit("/", 1)[
                                    0
                                ],
                                "notes": "Rename package folder to match lowercase package name.",
                            }
                        )

                fix_json["code_changes"] = changes
    except Exception:
        pass

    # Deterministic post-process for java:S106 style issues (System.err -> logger)
    # If the model returns no code_changes but we have a concrete System.err.println in context,
    # generate a safe single-line replace.
    try:
        msg = str(issue.get("message", "")).lower()
        if "system.err" in msg and isinstance(fix_json, dict):
            changes = fix_json.get("code_changes") or []
            if isinstance(changes, list) and len(changes) == 0 and file_relpath:
                file_lines = read_github_file_lines(
                    file_relpath, repo=repo, token=token, ref=ref
                ) or []
                line_no = issue.get("line")
                if isinstance(line_no, int) and line_no > 0 and line_no <= len(file_lines):
                    target = file_lines[line_no - 1].strip()
                    if target.startswith("System.err.println(") and target.endswith(");"):
                        changes.append(
                            {
                                "op": "replace",
                                "file": file_relpath,
                                "line": line_no,
                                "old_code": target,
                                "new_code": target.replace("System.err.println", "logger.warn"),
                                "notes": "Replace System.err.println with logger call (requires a logger to exist in the class).",
                            }
                        )
                        fix_json["code_changes"] = changes
    except Exception:
        pass

    fix_string = json.dumps(fix_json, ensure_ascii=False, indent=2)

    return {
        "fix_text": fix_text,
        "fix_json": fix_json,
        "fix_string": fix_string,
        "file_relpath": file_relpath,
        "generated_at": datetime.now(),
        "llm_meta": llm_meta,
    }

