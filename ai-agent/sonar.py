import os
import requests
from dotenv import load_dotenv

load_dotenv()

SONAR_TOKEN = os.getenv("SONAR_TOKEN")
PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")

def fetch_issues():
    url = "https://sonarcloud.io/api/issues/search"

    params = {
        "componentKeys": PROJECT_KEY
    }

    response = requests.get(url, params=params, auth=(SONAR_TOKEN, ""))
    return response.json()