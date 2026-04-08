from app_factory import create_app


app = create_app()

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from dotenv import load_dotenv
import urllib3
import json
from datetime import datetime
from pymongo import MongoClient
import certifi
from google import genai
import time
from typing import Optional, Tuple, List, Dict, Any

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load env
load_dotenv()

app = FastAPI()

# 🔐 CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
SONAR_TOKEN = os.getenv("SONAR_TOKEN")
PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

# Optional: local checkout root of the repo being fixed.
# Example: E:\TRIPLE I\Shift-Left-Compliance-Agents
CODEBASE_ROOT = os.getenv("CODEBASE_ROOT") or os.getenv("REPO_ROOT")

# Optional: GitHub repo source for reading files when the scanned codebase
# is not available locally.
# Example:
#   GITHUB_REPO_OWNER=your-org
#   GITHUB_REPO_NAME=your-repo
#   GITHUB_REF=main
#   GITHUB_TOKEN=ghp_...   (recommended for private repos / rate limits)
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME")
GITHUB_REF = os.getenv("GITHUB_REF", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Create Gemini client
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# 🗄️ MongoDB (FIXED SSL)
mongo_client = MongoClient(
    MONGO_URI,
    tlsCAFile=certifi.where()
)

db = mongo_client[DB_NAME]

issues_collection = db["issues"]
fixes_collection = db["fixes"]
prompts_collection = db["prompts"]

# 🏠 HOME
@app.get("/")
def home():
    return {"message": "Backend is running 🚀"}


# 🔁 FALLBACK FIX (VERY IMPORTANT)
def manual_fix(issue):
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


def get_prompt_for_rule(rule_key):
    """Get prompt template from database"""
    prompt_doc = prompts_collection.find_one({"rule_key": rule_key})
    return prompt_doc.get("prompt_template") if prompt_doc else None


def save_prompt_to_db(rule_key, description, prompt_template, category="General"):
    """Save a prompt to database"""
    prompts_collection.update_one(
        {"rule_key": rule_key},
        {"$set": {
            "rule_key": rule_key,
            "description": description,
            "prompt_template": prompt_template,
            "category": category,
            "language": "java",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }},
        upsert=True
    )


# 🤖 AI FIX (Gemini API with Database Prompts)
def generate_fix(issue, code_context: str = "", file_relpath: str = ""):
    def openrouter_generate(prompt: str):
        if not OPENROUTER_API_KEY:
            return None

        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                data=json.dumps({
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 600,
                }),
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

    rule_key = issue.get('rule')

    # Get rule-specific prompt from database
    prompt_template = get_prompt_for_rule(rule_key)

    if not prompt_template:
        # Fallback to generic prompt
        prompt_template = """
You are a senior Java developer.

Fix this SonarQube issue:

Issue: {message}
Rule: {rule}
File: {file}
Line: {line}

Provide:
1. Explanation
2. Fixed Java code
3. Best practice
"""

    # Format the prompt with issue data only for the known placeholders
    prompt = prompt_template.replace("{message}", str(issue.get("message", ""))) \
                            .replace("{rule}", str(rule_key)) \
                            .replace("{file}", str(issue.get("component", ""))) \
                            .replace("{line}", str(issue.get("line", "")))

    # Add real code context (so the model can craft exact old_code/new_code).
    if code_context:
        prompt = (
            prompt.strip()
            + "\n\n"
            + f"CODE CONTEXT (from {file_relpath or issue.get('component','')}):\n"
            + code_context.strip()
            + "\n"
        )

    # Force structured output so automation scripts can apply changes reliably.
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
        + "- Prefer op=replace with exact old_code copied from CODE CONTEXT.\n"
        + "- If package name changes, include op=move for folder rename (e.g., Services -> services).\n"
        + "- If you cannot propose safe exact code edits using CODE CONTEXT, set code_changes to an empty array.\n"
    )

    # 1) Try Gemini with small retry/backoff (handles 503 spikes)
    if GEMINI_API_KEY:
        for attempt in range(3):
            try:
                response = genai_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )

                if response and response.text:
                    return response.text

                # If no text returned, break to fallbacks
                break
            except Exception as e:
                print(f"Gemini API Error: {str(e)}")
                # Backoff: 1s, 2s, 4s
                time.sleep(2 ** attempt)

    # 2) Fallback to OpenRouter (DeepSeek / cheap model)
    fallback = openrouter_generate(prompt)
    if fallback:
        return fallback

    # 3) Final fallback
    return manual_fix(issue)



# 📊 GET ISSUES
@app.get("/issues")
def get_issues():
    url = f"https://sonarcloud.io/api/issues/search?componentKeys={PROJECT_KEY}"

    response = requests.get(
        url,
        auth=(SONAR_TOKEN, ""),
        verify=False
    )

    data = response.json()
    issues = []

    for issue in data.get("issues", []):
        issue_data = {
            "key": issue.get("key"),
            "rule": issue.get("rule"),
            "severity": issue.get("severity"),
            "message": issue.get("message"),
            "file": issue.get("component"),
            "line": issue.get("line"),
            "status": "open",
            "created_at": datetime.now()
        }

        # ✅ UPSERT (no duplicates)
        issues_collection.update_one(
            {"key": issue_data["key"]},
            {"$set": issue_data},
            upsert=True
        )

        issues.append(issue_data)

    return {"issues": issues}


# 🛠️ GET FIXES
@app.get("/fixes")
def get_fixes(limit: int = Query(5, ge=1, le=20), refresh: bool = False):
    url = f"https://sonarcloud.io/api/issues/search?componentKeys={PROJECT_KEY}"

    response = requests.get(
        url,
        auth=(SONAR_TOKEN, ""),
        verify=False
    )

    data = response.json()
    results = []

    def component_to_relpath(component: Optional[str]) -> str:
        # Sonar component often looks like: "<projectKey>:src/main/java/..."
        if not component or not isinstance(component, str):
            return ""
        if ":" in component:
            return component.split(":", 1)[1]
        return component

    def read_file_lines(abs_path: str) -> Optional[List[str]]:
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return f.readlines()
        except Exception:
            # Some repos use other encodings; try latin-1 as a fallback.
            try:
                with open(abs_path, "r", encoding="latin-1") as f:
                    return f.readlines()
            except Exception:
                return None

    def read_github_file_lines(file_relpath: str) -> Optional[List[str]]:
        """
        Read file content from GitHub using the Contents API.
        Works for text files; returns list of lines.
        """
        if not (GITHUB_REPO_OWNER and GITHUB_REPO_NAME and file_relpath):
            return None

        url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{file_relpath}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

        try:
            r = requests.get(url, headers=headers, params={"ref": GITHUB_REF}, timeout=20)
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, dict):
                return None
            if data.get("type") != "file":
                return None
            content_b64 = data.get("content")
            if not content_b64 or not isinstance(content_b64, str):
                return None
            import base64
            # GitHub may include newlines in base64 content
            raw = base64.b64decode(content_b64.encode("utf-8"), validate=False)
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = raw.decode("latin-1")
            return text.splitlines(keepends=True)
        except Exception:
            return None

    def build_context_snippet(file_relpath: str, line: Optional[int], radius: int = 25) -> str:
        """
        Returns a snippet with line numbers to help the LLM craft exact replacements.
        """
        if not file_relpath:
            return ""

        lines = None
        if CODEBASE_ROOT:
            abs_path = os.path.join(CODEBASE_ROOT, file_relpath)
            lines = read_file_lines(abs_path)

        # If local checkout not present, try GitHub.
        if not lines:
            lines = read_github_file_lines(file_relpath)

        if not lines:
            return ""
        if not isinstance(line, int) or line <= 0:
            line = 1
        start = max(1, line - radius)
        end = min(len(lines), line + radius)
        out = [f"(showing {start}-{end} of {len(lines)})"]
        for i in range(start, end + 1):
            prefix = ">>" if i == line else "  "
            out.append(f"{prefix} L{i}: {lines[i - 1].rstrip()}")
        return "\n".join(out)

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

    def ensure_fix_json(issue_obj, raw_text: str):
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
            # Normalize operations so scripts can rely on stable keys.
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

        # Not JSON → wrap as a structured object so downstream scripts have a stable shape.
        return {
            "problem": issue_obj.get("message") or "Sonar issue",
            "solution": raw_text if isinstance(raw_text, str) else str(raw_text),
            "code_changes": [],
        }

    def to_fix_string_from_legacy(fix_data):
        if isinstance(fix_data, str):
            return fix_data
        if isinstance(fix_data, (dict, list)):
            return json.dumps(fix_data, ensure_ascii=False, indent=2)
        return str(fix_data)

    for issue in data.get("issues", [])[:limit]:
        issue_key = issue.get("key")
        file_relpath = component_to_relpath(issue.get("component"))
        code_context = build_context_snippet(file_relpath, issue.get("line"))

        cached = None
        if issue_key and not refresh:
            cached = fixes_collection.find_one({"issue_key": issue_key}, {"_id": 0})

        if cached and cached.get("fix"):
            cached_fix = cached.get("fix")
            cached_raw = cached.get("fix_raw") or cached_fix
            cached_json = cached.get("fix_json")

            # Backfill JSON if missing but fix looks like JSON (including fenced json)
            if cached_json is None:
                cached_json = ensure_fix_json(issue, cached_raw)
                fixes_collection.update_one(
                    {"issue_key": issue_key},
                    {"$set": {
                        "fix_raw": cached_raw,
                        "fix_json": cached_json,
                        "fix": json.dumps(cached_json, ensure_ascii=False, indent=2),
                        "updated_at": datetime.now(),
                    }},
                )
                cached_fix = json.dumps(cached_json, ensure_ascii=False, indent=2)

            # Backfill raw if missing
            if cached.get("fix_raw") is None:
                fixes_collection.update_one(
                    {"issue_key": issue_key},
                    {"$set": {"fix_raw": cached_raw, "updated_at": datetime.now()}},
                )

            results.append({
                "issue": {
                    "key": issue_key,
                    "message": issue.get("message"),
                    "severity": issue.get("severity"),
                    "file": issue.get("component"),
                    "line": issue.get("line")
                },
                "fix": cached_fix,
                "fix_raw": cached_raw,
                "fix_json": cached_json,
                "source": "cache",
            })
            continue

        # Migrate legacy field if present (old records stored fix_data)
        if cached and cached.get("fix_data") is not None and issue_key and not refresh:
            fix_string = to_fix_string_from_legacy(cached.get("fix_data"))
            fixes_collection.update_one(
                {"issue_key": issue_key},
                {"$set": {
                    "fix": fix_string,
                    "fix_raw": cached.get("fix_raw") or (cached.get("fix_data") if isinstance(cached.get("fix_data"), str) else None),
                    "fix_json": cached.get("fix_json") or (cached.get("fix_data") if isinstance(cached.get("fix_data"), (dict, list)) else None),
                    "updated_at": datetime.now(),
                }},
            )
            results.append({
                "issue": {
                    "key": issue_key,
                    "message": issue.get("message"),
                    "severity": issue.get("severity"),
                    "file": issue.get("component"),
                    "line": issue.get("line")
                },
                "fix": fix_string,
                "fix_raw": cached.get("fix_raw"),
                "fix_json": cached.get("fix_json"),
                "source": "cache",
            })
            continue

        # Not cached (or refresh=true) → generate and save once
        fix_text = generate_fix(issue, code_context=code_context, file_relpath=file_relpath)  # raw model text (string)

        fix_json = ensure_fix_json(issue, fix_text)

        # Small deterministic post-process for common Java package rename: suggest folder move.
        try:
            msg = str(issue.get("message", "")).lower()
            if "package" in msg and "rename" in msg and isinstance(fix_json, dict):
                changes = fix_json.get("code_changes") or []
                if isinstance(changes, list) and file_relpath and "/Services/" in file_relpath:
                    # If the model proposed changing ".Services" -> ".services", ensure a move op exists.
                    has_move = any(isinstance(c, dict) and c.get("op") == "move" for c in changes)
                    if not has_move:
                        changes.append({
                            "op": "move",
                            "from": file_relpath.replace("/Services/", "/Services/").rsplit("/", 1)[0],
                            "to": file_relpath.replace("/Services/", "/services/").rsplit("/", 1)[0],
                            "notes": "Rename package folder to match lowercase package name.",
                        })
                        fix_json["code_changes"] = changes
        except Exception:
            pass

        fix_string = json.dumps(fix_json, ensure_ascii=False, indent=2)

        fix_record = {
            "issue_key": issue_key,
            "issue_rule": issue.get("rule"),
            "fix": fix_string,
            "fix_raw": fix_text,
            "fix_json": fix_json,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

        if issue_key:
            fixes_collection.update_one(
                {"issue_key": issue_key},
                {"$set": fix_record},
                upsert=True
            )

        results.append({
            "issue": {
                "key": issue_key,
                "message": issue.get("message"),
                "severity": issue.get("severity"),
                "file": issue.get("component"),
                "line": issue.get("line")
            },
            "fix": fix_string,
            "fix_raw": fix_text,
            "fix_json": fix_json,
            "source": "generated",
        })

    return {"results": results}


# 📝 PROMPT MANAGEMENT ENDPOINTS
@app.get("/prompts")
def get_all_prompts():
    """Get all stored prompts"""
    prompts = list(prompts_collection.find({}, {"_id": 0}))
    return {"prompts": prompts, "count": len(prompts)}

@app.post("/prompts")
def create_or_update_prompt(prompt_data: dict):
    """Add or update a prompt"""
    rule_key = prompt_data.get("rule_key")
    description = prompt_data.get("description")
    prompt_template = prompt_data.get("prompt_template")
    category = prompt_data.get("category", "General")
    
    if not rule_key or not prompt_template:
        return {"error": "rule_key and prompt_template are required"}
    
    save_prompt_to_db(rule_key, description, prompt_template, category)
    return {"status": "Prompt saved", "rule_key": rule_key}

@app.get("/prompts/{rule_key}")
def get_prompt(rule_key: str):
    """Get specific prompt"""
    prompt_doc = prompts_collection.find_one({"rule_key": rule_key}, {"_id": 0})
    if prompt_doc:
        return prompt_doc
    else:
        return {"error": "Prompt not found"}

@app.delete("/prompts/{rule_key}")
def delete_prompt(rule_key: str):
    """Delete a prompt"""
    result = prompts_collection.delete_one({"rule_key": rule_key})
    if result.deleted_count > 0:
        return {"status": "Prompt deleted", "rule_key": rule_key}
    else:
        return {"error": "Prompt not found"}