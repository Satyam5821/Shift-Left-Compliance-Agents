import json
from typing import Any, Dict, Optional, Tuple

import requests

from ..core.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)


def manual_fix(issue: Dict[str, Any]) -> str:
    message = issue.get("message", "")

    if "System.err" in message:
        return """Use a logger instead of System.err.

Example:
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

private static final Logger logger = LoggerFactory.getLogger(YourClass.class);

logger.error("Error message");
"""

    if "package name" in message:
        return """Rename package to lowercase.

Example:
com.example.soapservice.services
"""

    return "No fix available"


def openrouter_generate(prompt: str) -> Optional[str]:
    if not OPENROUTER_API_KEY:
        return None

    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "model": OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 700,
                }
            ),
            timeout=30,
        )

        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            print(f"OpenRouter API Error: {data.get('error')}")
            return None

        choices = (data or {}).get("choices") or []
        if choices and choices[0].get("message") and choices[0]["message"].get("content"):
            return choices[0]["message"]["content"]
        return None
    except Exception as e:
        print(f"OpenRouter Exception: {str(e)}")
        return None


def build_prompt(
    prompt_template: str,
    issue: Dict[str, Any],
    rule_key: str,
    code_context: str,
    file_relpath: str,
) -> str:
    prompt = (
        prompt_template.replace("{message}", str(issue.get("message", "")))
        .replace("{rule}", str(rule_key))
        .replace("{file}", str(issue.get("component", "")))
        .replace("{line}", str(issue.get("line", "")))
    )

    if code_context:
        prompt = (
            prompt.strip()
            + "\n\n"
            + f"CODE CONTEXT (from {file_relpath or issue.get('component','')}):\n"
            + code_context.strip()
            + "\n"
        )

    prompt = (
        prompt.strip()
        + "\n\n"
        + "IMPORTANT OUTPUT FORMAT:\n"
        + "Return ONLY valid JSON (no markdown, no ``` fences, no extra text).\n"
        + "Schema:\n"
        + "{\n"
        + '  "problem": "string",\n'
        + '  "solution": "string (keep short, editor friendly)",\n'
        + '  "code_changes": [\n'
        + '    {\n'
        + '      "op": "replace|insert_before|insert_after|delete|move",\n'
        + '      "file": "string (required for replace/insert/delete)",\n'
        + '      "line": 0,\n'
        + '      "old_code": "string (required for replace/delete unless line-based)",\n'
        + '      "new_code": "string (required for replace/insert)",\n'
        + '      "from": "string (required for move)",\n'
        + '      "to": "string (required for move)",\n'
        + '      "notes": "string (optional)"\n'
        + "    }\n"
        + "  ]\n"
        + "}\n"
        + "Rules:\n"
        + "- STRONGLY PREFER a SINGLE op=replace over separate insert+delete pairs;\n"
        + "  a replace atomically swaps the old block for the new one and is the safest edit.\n"
        + "- Copy old_code CHARACTER-FOR-CHARACTER from CODE CONTEXT, including all leading\n"
        + "  whitespace. The file may be indented with TABS — if a context line begins with a tab,\n"
        + "  your old_code MUST begin with the exact same tab(s). Do not convert tabs to spaces.\n"
        + "- old_code must be a UNIQUE substring in the file. If a short anchor like \"}\" or\n"
        + "  \"try {\" might appear multiple times, extend old_code to include surrounding lines\n"
        + "  (method signature, unique comment, unique variable name) so it matches exactly ONE location.\n"
        + "- For System.out/System.err replacements or logging fixes, preserve the full original\n"
        + "  statement text and indentation from CODE CONTEXT in old_code. Do not abbreviate,\n"
        + "  reformat, or simplify old_code before matching.\n"
        + "- For Java constant extraction, insert new static final fields at class scope near other\n"
        + "  constants, not inside a method. Do not introduce class members inside methods.\n"
        + "- If a constant with the same value already exists, reuse it instead of creating a duplicate.\n"
        + "- When making a single replacement, prefer a single op=replace with exact old_code and exact new_code.\n"
        + "  If you cannot safely produce an exact replacement, return code_changes: []\n"
        + "- For insert_before/insert_after, old_code must be a unique multi-line anchor from CODE CONTEXT.\n"
        + "- If package name changes, include op=move for folder rename (e.g., Services -> services).\n"
    )
    return prompt


def generate_fix_text(
    issue: Dict[str, Any],
    prompt_template: str,
    rule_key: str,
    code_context: str,
    file_relpath: str,
) -> Tuple[str, Dict[str, Any]]:
    prompt = build_prompt(prompt_template, issue, rule_key, code_context, file_relpath)
    meta: Dict[str, Any] = {"provider": None, "errors": []}  # errors: list[str]

    # Gemini disabled: OpenRouter only
    fallback = openrouter_generate(prompt)
    if fallback:
        meta["provider"] = "openrouter"
        return fallback, meta

    meta["provider"] = "manual_fix"
    meta["errors"].append("OpenRouter unavailable or rate-limited; using manual_fix fallback.")

    return manual_fix(issue), meta

