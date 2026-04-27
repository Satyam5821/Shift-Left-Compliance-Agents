from typing import Any, Dict, List
from urllib.parse import urljoin

import requests

from ..core.config import SONAR_PROJECT_KEY, SONAR_TOKEN, SONAR_VERIFY


def fetch_sonar_issues() -> List[Dict[str, Any]]:
    """
    SonarCloud UI commonly highlights "New Code" (leak period) issues.
    We align the dashboard with that default by fetching issues since leak period.
    """
    base_url = "https://sonarcloud.io"
    url = urljoin(base_url, "/api/issues/search")

    # Query params chosen to match SonarCloud default "Open issues" on New Code
    # and to avoid returning historical backlog that can inflate counts.
    params: Dict[str, Any] = {
        "componentKeys": SONAR_PROJECT_KEY,
        "sinceLeakPeriod": "false",  # Fetch all open issues, not just new code
        # Explicit open statuses to avoid surprises from API defaults.
        "statuses": "OPEN,REOPENED,CONFIRMED",
        # Pull a large page size and paginate to ensure correctness.
        "ps": 500,
        "p": 1,
    }

    all_issues: List[Dict[str, Any]] = []
    session = requests.Session()

    try:
        while True:
            response = session.get(url, params=params, auth=(SONAR_TOKEN, ""), verify=SONAR_VERIFY)
            response.raise_for_status()
            data = response.json() or {}

            issues = list(data.get("issues", []) or [])
            all_issues.extend(issues)

            paging = data.get("paging") or {}
            page_index = int(paging.get("pageIndex") or params["p"])
            page_size = int(paging.get("pageSize") or params["ps"])
            total = int(paging.get("total") or len(all_issues))

            if page_index * page_size >= total:
                break

            params["p"] = page_index + 1

        return all_issues
    except requests.exceptions.RequestException:
        return []

