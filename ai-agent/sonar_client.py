from typing import Any, Dict, List

import requests

from config import SONAR_PROJECT_KEY, SONAR_TOKEN


def fetch_sonar_issues() -> List[Dict[str, Any]]:
    url = f"https://sonarcloud.io/api/issues/search?componentKeys={SONAR_PROJECT_KEY}"
    response = requests.get(url, auth=(SONAR_TOKEN, ""), verify=False)
    data = response.json()
    return list(data.get("issues", []) or [])

