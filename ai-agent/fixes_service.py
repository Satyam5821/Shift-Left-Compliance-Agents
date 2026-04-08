import json
from datetime import datetime
from typing import Any, Dict, Optional

from github_context import build_context_snippet, component_to_relpath
from llm_fix import generate_fix_text


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
            normalized.append(out)
        parsed["code_changes"] = normalized
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


def generate_fix_for_issue(issue: Dict[str, Any], prompts_collection) -> Dict[str, Any]:
    rule_key = issue.get("rule")
    prompt_template = get_prompt_template_for_issue(prompts_collection, rule_key)

    file_relpath = component_to_relpath(issue.get("component"))
    code_context = build_context_snippet(file_relpath, issue.get("line"))

    fix_text = generate_fix_text(
        issue=issue,
        prompt_template=prompt_template,
        rule_key=str(rule_key),
        code_context=code_context,
        file_relpath=file_relpath,
    )

    fix_json = ensure_fix_json(issue, fix_text)

    # Deterministic post-process for common Java package rename: suggest folder move.
    try:
        msg = str(issue.get("message", "")).lower()
        if "package" in msg and "rename" in msg and isinstance(fix_json, dict):
            changes = fix_json.get("code_changes") or []
            if isinstance(changes, list) and file_relpath and "/Services/" in file_relpath:
                has_move = any(isinstance(c, dict) and c.get("op") == "move" for c in changes)
                if not has_move:
                    changes.append(
                        {
                            "op": "move",
                            "from": file_relpath.replace("/Services/", "/Services/").rsplit("/", 1)[0],
                            "to": file_relpath.replace("/Services/", "/services/").rsplit("/", 1)[0],
                            "notes": "Rename package folder to match lowercase package name.",
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
    }

