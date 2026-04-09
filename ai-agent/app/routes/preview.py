from fastapi import Query

from ..clients.github_context import read_github_file_lines


def register_preview_routes(app):
    @app.get("/snippet")
    def get_snippet(
        file: str = Query(..., description="Repo-relative path like src/main/java/..."),
        line: int = Query(1, ge=1),
        radius: int = Query(15, ge=0, le=200),
    ):
        lines = read_github_file_lines(file)
        if not lines:
            return {"ok": False, "error": "Unable to fetch file from GitHub", "file": file}

        start = max(1, line - radius)
        end = min(len(lines), line + radius)
        snippet_lines = []
        for i in range(start, end + 1):
            snippet_lines.append({"line": i, "text": lines[i - 1].rstrip("\n")})

        return {
            "ok": True,
            "file": file,
            "start": start,
            "end": end,
            "total": len(lines),
            "lines": snippet_lines,
        }

