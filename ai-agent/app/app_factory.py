import urllib3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.db import get_collections
from .routes.fixes import register_fix_routes
from .routes.issues import register_issue_routes
from .routes.preview import register_preview_routes
from .routes.prompts import register_prompt_routes
from .routes.webhook import register_webhook_routes
from .routes.scans import register_scan_routes
from .routes.github_install import register_github_install_routes
from .routes.workspaces import register_workspace_routes
from .routes.auth_github import register_auth_routes


def create_app() -> FastAPI:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    cols = get_collections()
    register_issue_routes(app, cols["issues"])
    register_fix_routes(app, cols["fixes"], cols["prompts"])
    register_prompt_routes(app, cols["prompts"])
    register_preview_routes(app)
    register_webhook_routes(
        app,
        cols["fixes"],
        cols["prompts"],
        cols["scans"],
        cols["scan_issues"],
        cols["scan_fix_attempts"],
        cols["github_app_installations"],
    )
    register_scan_routes(app, cols["scans"], cols["scan_issues"], cols["scan_fix_attempts"])
    register_github_install_routes(app, cols["github_app_installations"])
    register_workspace_routes(
        app,
        cols["workspaces"],
        cols["scans"],
        cols["scan_issues"],
        cols["scan_fix_attempts"],
    )
    register_auth_routes(app, cols["users"])

    @app.get("/")
    def home():
        return {"message": "Backend is running 🚀"}

    return app

