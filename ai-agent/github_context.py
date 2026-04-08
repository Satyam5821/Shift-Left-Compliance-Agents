import base64
from typing import List, Optional

import requests

from config import (
    GITHUB_REF,
    GITHUB_REPO_NAME,
    GITHUB_REPO_OWNER,
    GITHUB_TOKEN,
)


def component_to_relpath(component: Optional[str]) -> str:
    # Sonar component often looks like: "<projectKey>:src/main/java/..."
    if not component or not isinstance(component, str):
        return ""
    if ":" in component:
        return component.split(":", 1)[1]
    return component


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
    GitHub-only (no local filesystem reads).
    """
    if not file_relpath:
        return ""

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

