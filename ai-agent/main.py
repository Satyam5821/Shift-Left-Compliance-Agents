from fastapi import FastAPI
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

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load env
load_dotenv()

app = FastAPI()

# 🔐 CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow requests from any origin
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
def generate_fix(issue):
    if not GEMINI_API_KEY:
        return manual_fix(issue)

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

    try:
        response = genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        
        if response and response.text:
            return response.text
        else:
            return "No fix generated from Gemini"

    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
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
def get_fixes():
    url = f"https://sonarcloud.io/api/issues/search?componentKeys={PROJECT_KEY}"

    response = requests.get(
        url,
        auth=(SONAR_TOKEN, ""),
        verify=False
    )

    data = response.json()
    results = []

    for issue in data.get("issues", [])[:1]:  # limit to first issue only
        fix_text = generate_fix(issue)

        # Parse JSON response from Gemini
        fix_data = None
        try:
            fix_data = json.loads(fix_text)
        except json.JSONDecodeError:
            # Fallback if Gemini returns plain text
            fix_data = {"raw_response": fix_text}

        # ✅ UPSERT (save parsed fix to MongoDB)
        fix_record = {
            "issue_key": issue.get("key"),
            "issue_rule": issue.get("rule"),
            "fix_data": fix_data,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

        fixes_collection.update_one(
            {"issue_key": issue.get("key")},
            {"$set": fix_record},
            upsert=True
        )

        results.append({
            "issue": {
                "key": issue.get("key"),
                "message": issue.get("message"),
                "severity": issue.get("severity"),
                "file": issue.get("component"),
                "line": issue.get("line")
            },
            "fix": fix_data
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