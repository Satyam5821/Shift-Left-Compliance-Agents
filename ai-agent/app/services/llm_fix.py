import json
import logging
from typing import Any, Dict, Optional, Tuple

import requests

from ..core.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_MAX_TOKENS,
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
        logger = logging.getLogger("shiftleft.llm")
        max_tokens = int(OPENROUTER_MAX_TOKENS or 200)
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
                    "max_tokens": max_tokens,
                }
            ),
            timeout=30,
        )

        data = r.json()
        # Better handling for payment/credit errors (HTTP 402)
        if r.status_code == 402 or (isinstance(data, dict) and data.get("error") and isinstance(data.get("error"), dict) and data.get("error").get("code") == 402):
            logger.warning("OpenRouter API returned 402 (insufficient credits). Requested max_tokens=%d. Error=%s", max_tokens, data.get("error"))
            return None

        if isinstance(data, dict) and data.get("error"):
            logger.warning("OpenRouter API Error: %s", data.get("error"))
            return None

        choices = (data or {}).get("choices") or []
        if choices and choices[0].get("message") and choices[0]["message"].get("content"):
            return choices[0]["message"]["content"]
        return None
    except Exception as e:
        logging.getLogger("shiftleft.llm").exception("OpenRouter Exception: %s", str(e))
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
            + "1. CRITICAL FOR S6350 (OS command injection): NEVER use ProcessBuilder with 'sh' or '-c' and user input.\n"
            + "   Instead, use ONE of these approaches:\n"
            + "   a) WHITELIST ONLY (preferred): Check if user input is in a hardcoded whitelist, else throw exception:\n"
            + "      Set<String> allowed = new HashSet<>(Arrays.asList(\"date\", \"whoami\"));\n"
            + "      if (!allowed.contains(cmd)) throw new IllegalArgumentException(\"Command not allowed\");\n"
            + "      Process p = new ProcessBuilder(cmd).start();  // No shell, no concatenation\n"
            + "   b) DISABLE: Return a safe hardcoded response instead of executing:\n"
            + "      return \"Command execution disabled for safety\";\n"
            + "   c) REMOVE SHELL: Use ProcessBuilder(List<String>) with explicit args, NEVER 'sh -c':\n"
            + "      Process p = new ProcessBuilder(\"date\").start();  // Predefined command, no user input\n"
            + "2. When fixing OS command issues by removing parameter usage, you can:\n"
            + "   - Completely remove the parameter if method signature change is safe.\n"
            + "   - Or use it in a safe way: log it, or skip execution and return a message.\n"
            + "3. For input validation: after validation, use the validated input DIRECTLY, not with string concatenation.\n"
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
        + "1. IMPORTANT: Do NOT add imports for java.lang classes (Exception, String, Integer, etc.). They are IMPLICITLY available.\n"
        + "   NEVER add: import java.lang.IllegalArgumentException; import java.lang.ProcessBuilder; import java.lang.String;\n"
        + "   These will cause Sonar warnings: 'Remove this unnecessary import: java.lang classes are always implicitly imported.'\n"
        + "2. Only add imports for classes from OTHER packages:\n"
        + "   - java.io.IOException, java.io.BufferedReader (java.io package, NOT java.lang)\n"
        + "   - java.util.List, java.util.ArrayList, java.util.Set, java.util.HashSet (java.util package)\n"
        + "   - java.util.Arrays (for Arrays.asList)\n"
        + "   - org.slf4j.Logger, org.slf4j.LoggerFactory (for logging)\n"
        + "   - org.springframework.* (for Spring annotations)\n"
        + "3. Check the CODE CONTEXT to see what imports already exist - do not duplicate.\n"
        + "4. Add missing imports at the top of the file after existing imports, using: 'import fully.qualified.ClassName;'\n"
        + "5. If you're unsure whether an import is needed, check: is it from java.lang? If yes, SKIP IT. If no, include it.\n"
        + "6. Always include import statements in your code_changes array as separate insert_before operations using exact anchors.\n"
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

    # Add working examples for the most common rules
    if rule_key == "java:S106":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "CONCRETE EXAMPLE FOR SYSTEM.OUT REPLACEMENT (S106):\n"
            + "Issue: 'Replace System.out' in method doThing(String msg)\n"
            + "CODE CONTEXT shows:\n"
            + "  public void doThing(String msg) {\n"
            + "      System.out.println(\"Processing: \" + msg);\n"
            + "      System.out.println(\"Done\");\n"
            + "  }\n"
            + "\n"
            + "CORRECT FIX (2 changes, conservative approach):\n"
            + "1. First op=insert_before to add logger field BEFORE the first method:\n"
            + '   old_code: "    public void doThing(String msg) {"\n'
            + '   new_code: "    private static final Logger logger = LoggerFactory.getLogger(YourClass.class);\n\n    public void doThing(String msg) {"\n'
            + "2. Then op=replace to fix first System.out call:\n"
            + '   old_code: "        System.out.println(\"Processing: \" + msg);"\n'
            + '   new_code: "        logger.info(\"Processing: {}\", msg);"\n'
            + "3. Then op=replace to fix second System.out call:\n"
            + '   old_code: "        System.out.println(\"Done\");"\n'
            + '   new_code: "        logger.info(\"Done\");"\n'
            + "\nDo NOT merge into single replace - keep separate to be safe.\n"
        )
    elif rule_key == "javasecurity:S6350":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "CONCRETE EXAMPLE FOR OS COMMAND INJECTION (S6350):\n"
            + "Issue: 'Make sure that this user-controlled command argument doesn\\'t lead to unwanted behavior'\n"
            + "CODE CONTEXT shows:\n"
            + "  public String runCommandUnsafely(String cmd) throws IOException {\n"
            + "    Process p = new ProcessBuilder(\"sh\", \"-c\", cmd).start();\n"
            + "    ...\n"
            + "  }\n"
            + "\n"
            + "CORRECT FIX (whitelist-based, NO shell):\n"
            + "1. op=replace to add whitelist validation and use ProcessBuilder WITHOUT shell:\n"
            + '   old_code: "    Process p = new ProcessBuilder(\"sh\", \"-c\", cmd).start();"\n'
            + '   new_code: (\n'
            + '              "    // Whitelist allowed commands\\n"\n'
            + '              "    Set<String> allowed = new HashSet<>(Arrays.asList(\\\"date\\\", \\\"whoami\\\"));\\n"\n'
            + '              "    if (!allowed.contains(cmd)) {\\n"\n'
            + '              "      throw new IllegalArgumentException(\\\"Command not allowed\\\");\\n"\n'
            + '              "    }\\n"\n'
            + '              "    Process p = new ProcessBuilder(cmd).start();"\n'
            + '            )\n'
            + "2. op=insert_before to add required imports (java.util, NOT java.lang):\n"
            + '   old_code: "import java.nio.charset.StandardCharsets;"\n'
            + '   new_code: "import java.nio.charset.StandardCharsets;\\nimport java.util.Arrays;\\nimport java.util.HashSet;\\nimport java.util.Set;"\n'
            + "\nCRITICAL: Do NOT use 'sh -c' with user input. Do NOT add java.lang imports (ProcessBuilder, etc. are implicit).\n"
        )
    elif rule_key == "java:S2677":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "CONCRETE EXAMPLE FOR UNUSED readLine (S2677):\n"
            + "Issue: 'Use or store the value returned from readLine instead of throwing it away'\n"
            + "CODE CONTEXT shows:\n"
            + "  try (BufferedReader br = new BufferedReader(new InputStreamReader(...))) {\n"
            + "      StringBuilder output = new StringBuilder();\n"
            + "      while (br.readLine() != null) {  // readLine value is DISCARDED\n"
            + "          output.append(\"\\\\n\");\n"
            + "      }\n"
            + "  }\n"
            + "\n"
            + "CORRECT FIX (use the readLine value in loop body):\n"
            + "op=replace to capture and use the readLine return value:\n"
            + '   old_code: "      StringBuilder output = new StringBuilder();\\n      while (br.readLine() != null) {\\n          output.append(\\\"\\\\\\\\n\\\");"\n'
            + '   new_code: "      StringBuilder output = new StringBuilder();\\n      String line;\\n      while ((line = br.readLine()) != null) {\\n          output.append(line).append(\\\"\\\\\\\\n\\\");"\n'
            + "\nCRITICAL: Capture readLine() into a variable and USE it (append to output, process it, etc.). Do NOT just check (line != null) without using line.\n"
        )
    elif rule_key == "java:S1481":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "CONCRETE EXAMPLE FOR UNUSED LOCAL VARIABLE (S1481):\n"
            + "Issue: \"Remove unused 'unused_var' local variable\"\n"
            + "CODE CONTEXT shows:\n"
            + "  public void calculate() {\n"
            + "      int unused_var = 42;\n"
            + "      int result = 10 + 20;\n"
            + "      return result;\n"
            + "  }\n"
            + "\n"
            + "CORRECT FIX:\n"
            + "op=delete to remove the unused declaration:\n"
            + '   old_code: "      int unused_var = 42;"\n'
        )
    elif rule_key == "java:S1192":
        prompt = (
            prompt.strip()
            + "\n\n"
            + "CONCRETE EXAMPLE FOR DUPLICATED STRING LITERAL (S1192):\n"
            + "Issue: \"Define a constant instead of duplicating string 'ERROR_MESSAGE' 4 times\"\n"
            + "CODE CONTEXT shows:\n"
            + "  public class Validator {\n"
            + "      public void validate1() {\n"
            + "          System.out.println(\"Invalid input\");\n"
            + "      }\n"
            + "      public void validate2() {\n"
            + "          System.out.println(\"Invalid input\");\n"
            + "      }\n"
            + "  }\n"
            + "\n"
            + "CORRECT FIX:\n"
            + "1. op=insert_before to add constant field:\n"
            + '   old_code: "  public class Validator {"\n'
            + '   new_code: "  public class Validator {\n      private static final String ERROR_MESSAGE = \"Invalid input\";"\n'
            + "2. op=replace each duplicate:\n"
            + '   old_code: "          System.out.println(\"Invalid input\");"\n'
            + '   new_code: "          System.out.println(ERROR_MESSAGE);"\n'
            + "(repeat for each occurrence)\n"
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

