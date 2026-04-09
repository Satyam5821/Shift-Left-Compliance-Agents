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
    }

