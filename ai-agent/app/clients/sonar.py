from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from ..core.config import SONAR_PROJECT_KEY, SONAR_PROJECT_KEYS_BY_REPO, SONAR_TOKEN, SONAR_VERIFY


def resolve_sonar_component_key(
    repo: Optional[str] = None,
    explicit_project_key: Optional[str] = None,
) -> Optional[str]:
    """
    Map GitHub full name (owner/repo) to SonarCloud componentKeys, or use env default.

    SonarCloud often uses project keys like ``Owner_reponame`` (slash → underscore).
    Override per repo with SONAR_PROJECT_KEYS_JSON in config.
    """
    if explicit_project_key and str(explicit_project_key).strip():
        return str(explicit_project_key).strip()
    r = (repo or "").strip()
    if not r:
        return (SONAR_PROJECT_KEY or "").strip() or None
    mapped = SONAR_PROJECT_KEYS_BY_REPO.get(r)
    if mapped:
        return mapped
    if "/" in r:
        owner, name = r.split("/", 1)
        return f"{owner}_{name}"
    return (SONAR_PROJECT_KEY or "").strip() or None


def fetch_sonar_issues(component_key: Optional[str] = None, token_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    SonarCloud UI commonly highlights "New Code" (leak period) issues.
    We align the dashboard with that default by fetching issues since leak period.
    """
    key = (component_key or "").strip() or (SONAR_PROJECT_KEY or "").strip()
    if not key:
        return []
    tok = (token_override or "").strip() or (SONAR_TOKEN or "").strip()
    if not tok:
        return []

    base_url = "https://sonarcloud.io"
    url = urljoin(base_url, "/api/issues/search")

    # Query params chosen to match SonarCloud default "Open issues" on New Code
    # and to avoid returning historical backlog that can inflate counts.
    params: Dict[str, Any] = {
        "componentKeys": key,
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
            response = session.get(url, params=params, auth=(tok, ""), verify=SONAR_VERIFY)
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
