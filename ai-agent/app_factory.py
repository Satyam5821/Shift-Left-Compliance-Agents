from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import urllib3

from db import get_collections
from fixes_routes import register_fix_routes
from issues_routes import register_issue_routes
from prompts_routes import register_prompt_routes


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

    @app.get("/")
    def home():
        return {"message": "Backend is running 🚀"}

    return app

