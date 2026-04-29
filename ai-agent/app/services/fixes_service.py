import json
import re
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


def _parse_sonar_constant_name(message: str) -> Optional[str]:
    if not message or not isinstance(message, str):
        return None
    m = re.search(r"Use already-defined constant ['\"]([^'\"]+)['\"]", message)
    if m:
        return m.group(1)
    return None


def _parse_sonar_unused_variable_name(message: str) -> Optional[str]:
    if not message or not isinstance(message, str):
        return None
    m = re.search(r'Remove this unused ["\']([^"\']+)["\'] local variable', message)
    if m:
        return m.group(1)
    m2 = re.search(r"Remove this unused ([A-Za-z_][\w]*) local variable", message)
    if m2:
        return m2.group(1)
    return None


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
        # Allow valid JSON to be extracted from text that includes extra commentary.
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except Exception:
                pass
        return None


def ensure_fix_json(issue_obj: Dict[str, Any], raw_text: str):
    """
    Always return a dict with keys: problem, solution, code_changes.
    No extra LLM call is made here (token-safe).
    """
    parsed = extract_json_from_text(raw_text) if isinstance(raw_text, str) else None
    if isinstance(parsed, dict):
        def _strip_context_line_prefixes(s: str) -> str:
            """
            The context snippet includes lines like:
              '>> L143:     Math.pow(...)'
            Some models accidentally copy these prefixes into old_code/anchors.
            Strip them so our tolerant matcher can actually find the code in-file.
            """
            if not isinstance(s, str) or not s:
                return s
            out_lines = []
            for ln in s.splitlines():
                # Remove optional leading markers + "L123:" prefix.
                ln2 = re.sub(r"^\s*(?:>>\s*)?L\d+:\s?", "", ln)
                out_lines.append(ln2)
            return "\n".join(out_lines)

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

                # Strip accidental "L123:" prefixes copied from context snippet.
                if isinstance(out.get("old_code"), str):
                    out["old_code"] = _strip_context_line_prefixes(out["old_code"])
                if isinstance(out.get("new_code"), str):
                    out["new_code"] = _strip_context_line_prefixes(out["new_code"])

                # If model returns "replace" with empty new_code, treat as "delete".
                # This makes common "remove unused variable" fixes apply safely.
                if out["op"] == "replace":
                    new_code = out.get("new_code")
                    old_code = out.get("old_code")
                    if isinstance(new_code, str) and new_code.strip() == "" and isinstance(old_code, str) and old_code.strip():
                        out["op"] = "delete"
                        out.pop("new_code", None)

                # Reject unsafe multi-line patches that try to replace method definitions, annotations, or catch blocks
                old_code = out.get("old_code")
                if isinstance(old_code, str) and out["op"] in ("replace", "delete"):
                    old_lines = old_code.split("\n")
                    if len(old_lines) > 5:
                        # Check if patch spans method boundaries (signatures, annotations, catch blocks)
                        old_lower = old_code.lower()
                        unsafe_markers = [
                            "@payloadroot",
                            "@responsepayload",
                            "public ",
                            "private ",
                            "protected ",
                            "catch ",
                            "} catch",
                            "} else",
                        ]
                        if any(m in old_lower for m in unsafe_markers):
                            logger.warning(
                                "Sanitized unsafe multi-line patch for issue=%s: spans method boundary (old_code has %d lines)",
                                issue_obj.get("key"),
                                len(old_lines),
                            )
                            continue  # Skip this unsafe change

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

Quality Gate constraints:
- Do NOT introduce duplicated blocks of code. If the same logic is needed in 2+ places, extract a helper method and call it.
- Prefer small refactors that REDUCE duplication (e.g., shared helper for repeated try/catch + setter sequences).
- NEVER insert class members (fields, static final constants, methods, classes) inside a method body or inside try/catch blocks.
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

    # Deterministic post-process for common Java fixes when the model returns
    # off-topic JSON or low-quality code_changes.
    try:
        if isinstance(fix_json, dict) and file_relpath:
            changes = fix_json.get("code_changes") or []
            if isinstance(changes, list) and repo and token and ref:
                file_lines = read_github_file_lines(file_relpath, repo=repo, token=token, ref=ref) or []
                line_no = issue.get("line")
                file_blob = "".join(file_lines) if file_lines else ""

                def _looks_offtopic_java_security_blob(s: str) -> bool:
                    blob = (s or "").lower()
                    markers = [
                        "documentbuilderfactory",
                        "external-general-entities",
                        "external-parameter-entities",
                        "secure-processing",
                        "load-external-dtd",
                        "xxe",
                    ]
                    return any(m in blob for m in markers)

                # For some rules we want to strictly constrain the patch shape.
                # If the model proposes something off-topic (e.g., XML/XXE mitigation for a %n rule),
                # ignore it and use deterministic patching instead.
                if str(rule_key) in ("java:S3457", "java:S6213", "java:S1192"):
                    suspicious = False
                    if not changes:
                        suspicious = True
                    else:
                        for c in changes:
                            if not isinstance(c, dict):
                                suspicious = True
                                break
                            if _looks_offtopic_java_security_blob(json.dumps(c, ensure_ascii=False)):
                                suspicious = True
                                break
                    if suspicious:
                        changes = []

                # java:S1192: if DEFAULT_TARGET_NAMESPACE exists, replace duplicated
                # target-namespace literals with that constant (single-line safe replaces).
                if str(rule_key) == "java:S1192" and file_lines:
                    # Sonar often tells us exactly which constant to use, e.g.:
                    # "Use already-defined constant 'LOCATION_URBAN' instead of duplicating its value here."
                    # Prefer a deterministic line-based replace using that constant name.
                    try:
                        msg0 = str(issue.get("message") or "")
                        m = re.search(r"already-defined constant '([A-Z][A-Z0-9_]*)'", msg0)
                        const_name = m.group(1) if m else None
                        if const_name:
                            # Find constant definition and literal value in file.
                            const_def_re = re.compile(
                                rf"(?m)^\s*(?:(?:public|protected|private)\s+)?static\s+final\s+String\s+{re.escape(const_name)}\s*=\s*\"([^\"]*)\""
                            )
                            m2 = const_def_re.search(file_blob)
                            literal_value = m2.group(1) if m2 else None

                            if literal_value and isinstance(line_no, int) and 1 <= line_no <= len(file_lines):
                                raw_line = file_lines[line_no - 1].rstrip("\n")
                                # If the line already uses the constant, nothing to do.
                                if const_name not in raw_line:
                                    quoted = f"\"{literal_value}\""
                                    if quoted in raw_line:
                                        new_line = raw_line.replace(quoted, const_name)
                                        if new_line != raw_line:
                                            changes.append(
                                                {
                                                    "op": "replace",
                                                    "file": file_relpath,
                                                    "line": line_no,
                                                    "old_code": raw_line.strip(),
                                                    "new_code": new_line.strip(),
                                                    "notes": f"Use existing constant {const_name} instead of duplicating its literal value.",
                                                }
                                            )
                    except Exception:
                        pass

                    has_default_ns = any(
                        'DEFAULT_TARGET_NAMESPACE' in (ln or "") and "static final" in (ln or "")
                        for ln in file_lines
                    )
                    literal = "http://spring.io/guides/gs-producing-web-service"
                    if has_default_ns:
                        # Replace only setTargetNamespace("<literal>") occurrences.
                        for idx, ln in enumerate(file_lines, start=1):
                            raw = (ln or "").rstrip("\n")
                            if literal not in raw:
                                continue
                            if "setTargetNamespace" not in raw:
                                continue
                            # Keep formatting stable and avoid multi-line edits.
                            new_raw = raw.replace(f"\"{literal}\"", "DEFAULT_TARGET_NAMESPACE")
                            if new_raw != raw:
                                changes.append(
                                    {
                                        "op": "replace",
                                        "file": file_relpath,
                                        "line": idx,
                                        "old_code": raw.strip(),
                                        "new_code": new_raw.strip(),
                                        "notes": "Use DEFAULT_TARGET_NAMESPACE instead of duplicating its literal value.",
                                    }
                                )

                # java:S1192: if Sonar says to reuse an already-defined constant, build
                # a deterministic single-line replace instead of inserting a new field.
                if str(rule_key) == "java:S1192" and file_lines:
                    constant_name = _parse_sonar_constant_name(str(issue.get("message", "")))
                    if constant_name and any(
                        constant_name in (ln or "") and "static final" in (ln or "")
                        for ln in file_lines
                    ):
                        candidate_line = None
                        candidate_raw = None
                        if isinstance(line_no, int):
                            start = max(1, line_no - 3)
                            end = min(len(file_lines), line_no + 3)
                        else:
                            start = 1
                            end = len(file_lines)
                        for idx in range(start, end + 1):
                            raw = file_lines[idx - 1].rstrip("\n")
                            if constant_name in raw:
                                continue
                            if '"' not in raw:
                                continue
                            if "setMessage" not in raw and "Message(" not in raw:
                                continue
                            candidate_line = idx
                            candidate_raw = raw
                            break
                        if candidate_line and candidate_raw:
                            quote_match = re.search(r'"([^\"]*)"', candidate_raw)
                            if quote_match:
                                literal = quote_match.group(0)
                                new_raw = candidate_raw.replace(literal, constant_name, 1)
                                if new_raw != candidate_raw:
                                    changes = [
                                        {
                                            "op": "replace",
                                            "file": file_relpath,
                                            "line": candidate_line,
                                            "old_code": candidate_raw.strip(),
                                            "new_code": new_raw.strip(),
                                            "notes": f"Reuse existing constant {constant_name} instead of duplicating its literal.",
                                        }
                                    ]

                # java:S1481: remove unused local variable declarations deterministically.
                if str(rule_key) == "java:S1481" and file_lines:
                    variable_name = _parse_sonar_unused_variable_name(str(issue.get("message", "")))
                    if variable_name:
                        candidate_line = None
                        candidate_raw = None
                        if isinstance(line_no, int):
                            start = max(1, line_no - 3)
                            end = min(len(file_lines), line_no + 3)
                        else:
                            start = 1
                            end = len(file_lines)
                        for idx in range(start, end + 1):
                            raw = file_lines[idx - 1].rstrip("\n")
                            if variable_name not in raw:
                                continue
                            if "=" not in raw and ";" not in raw:
                                continue
                            candidate_line = idx
                            candidate_raw = raw
                            break
                        if candidate_line and candidate_raw:
                            changes = [
                                {
                                    "op": "delete",
                                    "file": file_relpath,
                                    "line": candidate_line,
                                    "old_code": candidate_raw.strip(),
                                    "notes": f"Remove unused local variable {variable_name}.",
                                }
                            ]

                # java:S106 (System.out/System.err -> logger):
                # Guard against unsafe insert_before patches that accidentally include method
                # signatures or duplicate logger declarations.
                # java:S1192 deterministic fallback for reuse-existing constant issues.
                if str(rule_key) == "java:S1192" and file_lines and not changes:
                    msg = str(issue.get("message", ""))
                    literal_match = re.search(r'"([^\"]+)"', msg)
                    if literal_match:
                        literal = literal_match.group(1)
                        const_name = None
                        const_pattern = re.compile(
                            rf"\s*private\s+static\s+final\s+String\s+([A-Z0-9_]+)\s*=\s*\"{re.escape(literal)}\"\s*;"
                        )
                        for ln in file_lines:
                            m = const_pattern.match(ln)
                            if m:
                                const_name = m.group(1)
                                break

                        if const_name:
                            candidate_line = None
                            candidate_raw = None
                            if isinstance(line_no, int):
                                start = max(1, line_no - 3)
                                end = min(len(file_lines), line_no + 3)
                            else:
                                start = 1
                                end = len(file_lines)
                            for idx in range(start, end + 1):
                                raw = file_lines[idx - 1].rstrip("\n")
                                if f'"{literal}"' not in raw:
                                    continue
                                if const_name in raw:
                                    continue
                                candidate_line = idx
                                candidate_raw = raw
                                break

                            if candidate_line and candidate_raw:
                                new_raw = candidate_raw.replace(f'"{literal}"', const_name, 1)
                                if new_raw != candidate_raw:
                                    changes = [
                                        {
                                            "op": "replace",
                                            "file": file_relpath,
                                            "line": candidate_line,
                                            "old_code": candidate_raw.strip(),
                                            "new_code": new_raw.strip(),
                                            "notes": f"Reuse existing constant {const_name} instead of duplicating its literal.",
                                        }
                                    ]

                if str(rule_key) == "java:S106" and file_lines:
                    has_logger_already = (
                        ("LoggerFactory.getLogger(" in file_blob)
                        or ("private static final Logger logger" in file_blob)
                        or ("static final Logger logger" in file_blob)
                    )

                    sanitized: list = []
                    seen_insert_chunk: set = set()

                    for c in changes:
                        if not isinstance(c, dict):
                            continue
                        op = c.get("op")
                        new_code = c.get("new_code") if isinstance(c.get("new_code"), str) else ""
                        old_code = c.get("old_code") if isinstance(c.get("old_code"), str) else ""

                        # If the repo file already has a logger, never insert another one.
                        if op in ("insert_before", "insert_after") and has_logger_already:
                            continue

                        # Prevent inserts that contain method/class declarations (these have
                        # caused broken Java like duplicated method signatures).
                        if op in ("insert_before", "insert_after") and new_code:
                            suspicious_markers = [
                                "\npublic ",
                                "\nprivate ",
                                "\nprotected ",
                                " class ",
                                " interface ",
                                " enum ",
                                "(",
                            ]
                            # Allow the logger field itself (it contains parentheses in getLogger).
                            is_logger_field = (
                                "LoggerFactory.getLogger" in new_code and "Logger" in new_code
                            )
                            if (not is_logger_field) and any(m in new_code for m in suspicious_markers):
                                logger.warning(
                                    "Sanitized unsafe java:S106 insert patch for issue=%s: new_code looks like it inserts members/methods",
                                    issue.get("key"),
                                )
                                continue

                            key = new_code.strip()
                            if key in seen_insert_chunk:
                                continue
                            seen_insert_chunk.add(key)

                        # If a replace introduces a logger.* call but we skipped logger insertion,
                        # keep it anyway only if logger already exists.
                        if op == "replace" and "logger." in (c.get("new_code") or "") and (not has_logger_already):
                            # We don't auto-drop replaces because they might target an existing logger
                            # with a different name; but in our generated prompts we standardize to logger.
                            pass

                        # Keep everything else.
                        sanitized.append(c)

                    changes = sanitized

                # java:S3457: use %n instead of \n inside format strings
                if str(rule_key) == "java:S3457" and isinstance(line_no, int) and 1 <= line_no <= len(file_lines):
                    # Look around the reported line for String.format / printf with "\n"
                    start = max(1, line_no - 3)
                    end = min(len(file_lines), line_no + 3)
                    for ln in range(start, end + 1):
                        raw = file_lines[ln - 1].rstrip("\n")
                        if "\\n" not in raw:
                            continue
                        if "String.format(" not in raw and ".printf(" not in raw:
                            continue
                        new_line = raw.replace("\\n", "%n")
                        if new_line != raw:
                            changes.append(
                                {
                                    "op": "replace",
                                    "file": file_relpath,
                                    "line": ln,
                                    "old_code": raw.strip(),
                                    "new_code": new_line.strip(),
                                    "notes": "Use %n for platform-specific line separator in format strings.",
                                }
                            )
                            break

                # java:S6213: rename restricted identifier variable names (e.g., yield/record/var)
                if str(rule_key) == "java:S6213" and isinstance(line_no, int) and len(file_lines) > 0:
                    start = max(1, line_no - 6)
                    end = min(len(file_lines), line_no + 6)
                    restricted = ["yield", "record", "var"]
                    for name in restricted:
                        # Find a declaration line first
                        decl_ln = None
                        decl_text = None
                        for ln in range(start, end + 1):
                            raw = file_lines[ln - 1].rstrip("\n")
                            if f" {name} " in raw or raw.strip().startswith(f"{name} "):
                                # avoid matching in strings; keep it simple
                                if f" {name} =" in raw or raw.strip().startswith(f"{name}=") or f" {name}=" in raw:
                                    decl_ln = ln
                                    decl_text = raw
                                    break
                        if decl_ln and decl_text:
                            new_name = f"{name}Value"
                            # Replace occurrences in a small window (safe, line-based replace)
                            for ln in range(start, end + 1):
                                raw = file_lines[ln - 1].rstrip("\n")
                                if name not in raw:
                                    continue
                                # Replace only whole-word-ish occurrences
                                new_raw = re.sub(rf"\\b{name}\\b", new_name, raw)
                                if new_raw != raw:
                                    changes.append(
                                        {
                                            "op": "replace",
                                            "file": file_relpath,
                                            "line": ln,
                                            "old_code": raw.strip(),
                                            "new_code": new_raw.strip(),
                                            "notes": f"Rename variable `{name}` to avoid restricted identifier name.",
                                        }
                                    )
                            break

                if changes:
                    fix_json["code_changes"] = changes
    except Exception:
        pass

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

