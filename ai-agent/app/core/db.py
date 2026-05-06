import certifi
from pymongo import MongoClient

from .config import DB_NAME, MONGO_URI


def get_db():
    mongo_client = MongoClient(
        MONGO_URI,
        tlsCAFile=certifi.where(),
    )
    return mongo_client[DB_NAME]


def get_collections():
    db = get_db()
    return {
        "issues": db["issues"],
        "fixes": db["fixes"],
        "prompts": db["prompts"],
        "scans": db["scans"],
        "scan_events": db["scan_events"],
        "scan_issues": db["scan_issues"],
        "scan_fix_attempts": db["scan_fix_attempts"],
        "github_app_installations": db["github_app_installations"],
        "workspaces": db["workspaces"],
        "sonar_connections": db["sonar_connections"],
        "users": db["users"],
        "quality_gate_retries": db["quality_gate_retries"],
    }

