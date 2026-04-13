import urllib3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.db import get_collections
from .routes.fixes import register_fix_routes
from .routes.issues import register_issue_routes
from .routes.preview import register_preview_routes
from .routes.prompts import register_prompt_routes
from .routes.webhook import register_webhook_routes


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
    register_webhook_routes(app, cols["fixes"], cols["prompts"])

    @app.get("/")
    def home():
        return {"message": "Backend is running 🚀"}

    return app

