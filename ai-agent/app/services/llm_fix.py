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

    # Rule-specific guidance
    if rule_key == "java:S106":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR System.out REPLACEMENT:\n"
            + "1. If no logger field exists in the class, generate an insert_before patch to add:\n"
            + '   private static final Logger logger = LoggerFactory.getLogger(ClassName.class);\n'
            + "   Insert this BEFORE the first method (use exact old_code from class declaration or imports).\n"
            + "2. Then generate a separate op=replace for EACH System.out/err call, replacing ONLY the print statement itself.\n"
            + "3. Do NOT include the logger field in the replace operations—only replace the System.out part.\n"
        )
    elif rule_key == "java:S1192":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR DUPLICATED STRING LITERALS:\n"
            + "1. If the issue message says an already-defined constant exists, do NOT add a new constant.\n"
            + "2. Reuse the existing constant name from the issue message and replace only the duplicate string literal.\n"
            + "3. Use op=replace for the duplicate literal occurrence, not a replace of an entire method or block.\n"
            + "4. old_code must include the full quoted string literal exactly as it appears in the file.\n"
            + "5. Do not duplicate constant declarations or add constants inside methods.\n"
        )
    elif rule_key == "java:S112":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR GENERIC EXCEPTIONS:\n"
            + "1. Replace 'throws Exception' with specific exception types like 'IOException', 'InterruptedException', etc.\n"
            + "2. Replace 'catch (Exception e)' with specific exception types like 'catch (NumberFormatException e)'.\n"
            + "3. IMPORTANT: If you introduce new exception types (IOException, InterruptedException, etc.), you MUST add the corresponding import statements.\n"
            + "4. Add imports at the top of the file after existing imports, e.g., 'import java.io.IOException;'.\n"
            + "5. Do not assume imports are already present - check the CODE CONTEXT and add missing ones.\n"
        )
    elif rule_key.startswith("javasecurity:"):
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR SECURITY HOTSPOTS:\n"
            + "1. When fixing OS command injection (S2076) or similar security issues by replacing user input with safe defaults, consider parameter usage:\n"
            + "   - If replacing user-controlled input with hardcoded safe values, the original parameter may become unused.\n"
            + "   - Either remove the unused parameter entirely (if safe), or use it harmlessly to avoid new Sonar issues.\n"
            + "   - Safe ways to use an unused parameter: log it, validate it, or use in a no-op expression like `if (false) { System.out.println(param); }`\n"
            + "   - Prefer removing the parameter if the method signature can be safely changed.\n"
            + "2. For input validation fixes, ensure validation logic doesn't create new unused variable issues.\n"
            + "3. When sanitizing input, make sure the sanitized result is actually used in the operation.\n"
        )
    elif rule_key == "java:S1172":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR UNUSED METHOD PARAMETERS:\n"
            + "1. Do not remove a method parameter if the method is still called by other code.\n"
            + "2. Preserve the parameter and use it in a harmless expression so Sonar no longer reports it as unused.\n"
            + "3. Avoid introducing new unused local variables while fixing this rule.\n"
            + "4. If the parameter is only needed to satisfy Sonar, use a safe no-op reference such as `if (false) { System.out.println(cmd); }`.\n"
        )
    elif rule_key == "java:S2677":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR UNUSED readLine RETURN VALUES:\n"
            + "1. If the issue is about a BufferedReader.readLine() result, either use the returned line inside the loop body or simplify to `while (br.readLine() != null)`.\n"
            + "2. Do not declare a temporary variable like `String line;` if the value is never consumed.\n"
            + "3. Prefer a single op=replace that fixes the loop condition, rather than introducing additional unused variables.\n"
        )
    elif rule_key == "java:S1481":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "SPECIAL FOR UNUSED LOCAL VARIABLE REMOVAL:\n"
            + "1. Remove the unused local variable declaration using op=delete when possible.\n"
            + "2. The old_code should be the exact declaration line, including any trailing comment.\n"
            + "3. Do not change surrounding control flow, method signatures, or add new code.\n"
            + "4. If a delete is not safe, return code_changes: [] rather than generating a risky refactor.\n"
        )

    # Universal import guidance for ALL Java fixes
    prompt = (
        prompt.strip()
        + "\n\n"
        + "UNIVERSAL IMPORT REQUIREMENTS (APPLIES TO ALL JAVA FIXES):\n"
        + "1. If your fix introduces ANY new Java classes, exceptions, or types (IOException, List, Map, Logger, etc.), you MUST add the corresponding import statements.\n"
        + "2. Check the CODE CONTEXT to see what imports are already present - do not duplicate existing imports.\n"
        + "3. Add missing imports at the top of the file after existing imports, using the format 'import fully.qualified.ClassName;'.\n"
        + "4. Common imports you may need to add:\n"
        + "   - java.io.IOException (for file operations)\n"
        + "   - java.lang.InterruptedException (for Thread.sleep, etc.)\n"
        + "   - java.util.List, java.util.ArrayList, java.util.Map, java.util.HashMap (for collections)\n"
        + "   - java.util.Optional (for optional values)\n"
        + "   - java.util.stream.Collectors, java.util.stream.Stream (for stream operations)\n"
        + "   - org.slf4j.Logger, org.slf4j.LoggerFactory (for logging)\n"
        + "   - org.springframework.* (for Spring annotations and classes)\n"
        + "5. If you're unsure whether an import is needed, include it anyway - the automatic import detection will handle duplicates.\n"
        + "6. Always include import statements in your code_changes array as separate insert_before operations.\n"
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

