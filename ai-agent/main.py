from fastapi import FastAPI
import requests
import os
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


load_dotenv()

app = FastAPI()

SONAR_TOKEN = os.getenv("SONAR_TOKEN")
PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")

@app.get("/")
def home():
    return {"message": "Backend is running 🚀"}

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
        issues.append({
            "key": issue.get("key"),
            "rule": issue.get("rule"),
            "severity": issue.get("severity"),
            "message": issue.get("message"),
            "file": issue.get("component"),
            "line": issue.get("line")
        })

    return {"issues": issues}