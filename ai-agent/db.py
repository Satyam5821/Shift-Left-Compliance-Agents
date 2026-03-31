import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI"),
    tlsCAFile=certifi.where()
)

db = client[os.getenv("DB_NAME")]

issues_collection = db["issues"]
fixes_collection = db["fixes"]