from fastapi import FastAPI
import requests
import os
from dotenv import load_dotenv
import urllib3
from datetime import datetime
from pymongo import MongoClient
import certifi

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load env
load_dotenv()

app = FastAPI()

# 🔐 ENV
SONAR_TOKEN = os.getenv("SONAR_TOKEN")
PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODEL = os.getenv("HF_MODEL", "ollam/ollama-2")
HF_ROUTER_URL = os.getenv("HF_ROUTER_URL", "https://router.huggingface.co/hf-inference/models")

# 🗄️ MongoDB (FIXED SSL)
client = MongoClient(
    MONGO_URI,
    tlsCAFile=certifi.where()
)

db = client[DB_NAME]

issues_collection = db["issues"]
fixes_collection = db["fixes"]

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


# 🤖 AI FIX (HuggingFace Router + ollam model)
def generate_fix(issue):
    if not HF_API_KEY:
        return manual_fix(issue)

    model = HF_MODEL
    url = f"{HF_ROUTER_URL}/{model}"

    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
You are a senior Java developer.

Fix this SonarQube issue:

Issue: {issue.get('message')}
Rule: {issue.get('rule')}
File: {issue.get('component')}
Line: {issue.get('line')}

Provide:
1. Explanation
2. Fixed Java code
3. Best practice
"""

    payload = {
        "inputs": prompt
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        print(f"HF Router Response for {model}:", response.status_code, response.text)

        if response.status_code == 404:
            print(f"HF model not found ({model}); check HF_MODEL, current path: {url}")
            return manual_fix(issue)

        if response.status_code != 200:
            # fallback to manual fix if HF fails
            print("HF Error Response", response.text)
            return manual_fix(issue)

        data = response.json()

        # Hugging Face router may return either list or dict
        if isinstance(data, list) and len(data) > 0:
            return data[0].get("generated_text", data[0].get("data", "No fix generated"))

        if isinstance(data, dict):
            if "generated_text" in data:
                return data["generated_text"]
            if "error" in data:
                return f"HF response error: {data['error']}"

        return "No fix generated from HF"

    except requests.exceptions.RequestException as e:
        return f"Error generating fix: HTTP request failed: {str(e)}"

    except Exception as e:
        return f"Error generating fix: {str(e)}"



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

    for issue in data.get("issues", [])[:5]:  # limit for testing
        fix = generate_fix(issue)

        # ✅ UPSERT (avoid duplicate fixes)
        fixes_collection.update_one(
            {"issue_key": issue.get("key")},
            {"$set": {
                "fix": fix,
                "created_at": datetime.now()
            }},
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
            "fix": fix
        })

    return {"results": results}