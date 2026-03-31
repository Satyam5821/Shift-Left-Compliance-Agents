from fastapi import FastAPI
import requests
import os
from dotenv import load_dotenv
import urllib3
from datetime import datetime
from pymongo import MongoClient

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

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# 🗄️ MongoDB
client = MongoClient(
    MONGO_URI,
    tls=True,
    tlsAllowInvalidCertificates=True
)
db = client[DB_NAME]

issues_collection = db["issues"]
fixes_collection = db["fixes"]

# 🏠 HOME
@app.get("/")
def home():
    return {"message": "Backend is running 🚀"}


# 🤖 AI FIX (OpenRouter)
def generate_fix(issue):
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
    Fix this code issue:

    Issue: {issue.get('message')}
    Rule: {issue.get('rule')}

    Provide:
    - Explanation
    - Fixed code
    """

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()

        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            print("OpenRouter Error:", data)
            return "Error generating fix"

    except Exception as e:
        return f"Error: {str(e)}"


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

    for issue in data.get("issues", [])[:2]:  # limit for testing
        fix = generate_fix(issue)

        fixes_collection.insert_one({
            "issue_key": issue.get("key"),
            "fix": fix,
            "created_at": datetime.now()
        })

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