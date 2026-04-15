import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import jwt  # PyJWT
import requests

from ..core.config import GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PEM


@dataclass
class GitHubRef:
    owner: str
    repo: str


def _require_app_config() -> Tuple[str, str]:
    if not GITHUB_APP_ID or not GITHUB_APP_PRIVATE_KEY_PEM:
        raise RuntimeError("Missing GITHUB_APP_ID or GITHUB_APP_PRIVATE_KEY_PEM")
    return str(GITHUB_APP_ID), str(GITHUB_APP_PRIVATE_KEY_PEM)


def build_app_jwt() -> str:
    app_id, pem = _require_app_config()
    now = int(time.time())
    payload = {
        "iat": now - 30,
        "exp": now + 9 * 60,  # GitHub requires exp <= 10 minutes
        "iss": app_id,
    }
    return jwt.encode(payload, pem, algorithm="RS256")


def _gh_headers(token: str) -> Dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_installation_token(installation_id: int) -> str:
    app_jwt = build_app_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    r = requests.post(url, headers=_gh_headers(app_jwt), timeout=30)
    r.raise_for_status()
    data = r.json()
    tok = (data or {}).get("token")
    if not tok:
        raise RuntimeError("Failed to obtain installation token from GitHub")
    return tok


def get_file_content(
    repo: GitHubRef, token: str, path: str, ref: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (text, sha). text is decoded UTF-8/latin-1.
    """
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/contents/{path}"
    r = requests.get(url, headers=_gh_headers(token), params={"ref": ref}, timeout=30)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or data.get("type") != "file":
        return None, None
    b64 = data.get("content") or ""
    sha = data.get("sha")
    raw = base64.b64decode(b64.encode("utf-8"), validate=False)
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("latin-1")
    return text, sha


def put_file_content(
    repo: GitHubRef,
    token: str,
    path: str,
    branch: str,
    message: str,
    text: str,
    sha: Optional[str],
) -> str:
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/contents/{path}"
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=_gh_headers(token), data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    data = r.json()
    # return new sha if present
    return ((data or {}).get("content") or {}).get("sha") or ""


def delete_file(
    repo: GitHubRef,
    token: str,
    path: str,
    branch: str,
    message: str,
    sha: str,
) -> None:
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/contents/{path}"
    payload: Dict[str, Any] = {"message": message, "sha": sha, "branch": branch}
    r = requests.delete(url, headers=_gh_headers(token), data=json.dumps(payload), timeout=30)
    r.raise_for_status()


def get_branch_sha(repo: GitHubRef, token: str, branch: str) -> str:
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/git/ref/heads/{branch}"
    r = requests.get(url, headers=_gh_headers(token), timeout=30)
    r.raise_for_status()
    data = r.json()
    sha = ((data or {}).get("object") or {}).get("sha")
    if not sha:
        raise RuntimeError("Unable to read branch SHA")
    return sha


def create_branch(repo: GitHubRef, token: str, new_branch: str, base_branch: str) -> str:
    base_sha = get_branch_sha(repo, token, base_branch)
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/git/refs"
    payload = {"ref": f"refs/heads/{new_branch}", "sha": base_sha}
    r = requests.post(url, headers=_gh_headers(token), data=json.dumps(payload), timeout=30)
    if r.status_code in (201,):
        return base_sha
    # If branch exists, ignore
    if r.status_code == 422:
        return base_sha
    r.raise_for_status()
    return base_sha


def create_pull_request(
    repo: GitHubRef,
    token: str,
    title: str,
    body: str,
    head: str,
    base: str,
) -> Dict[str, Any]:
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/pulls"
    payload = {"title": title, "body": body, "head": head, "base": base}
    r = requests.post(url, headers=_gh_headers(token), data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()


def find_open_pull_request(repo: GitHubRef, token: str, head: str, base: str) -> Optional[Dict[str, Any]]:
    """
    Find existing open PR for given head/base.
    GitHub expects head in the form "owner:branch" when using the list API.
    """
    url = f"https://api.github.com/repos/{repo.owner}/{repo.repo}/pulls"
    r = requests.get(
        url,
        headers=_gh_headers(token),
        params={"state": "open", "head": f"{repo.owner}:{head}", "base": base},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        return data[0]
    return None

