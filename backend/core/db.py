"""
Database connection singleton for NOC-Sentinel backend.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient

_client = None
_db = None


def get_client() -> AsyncIOMotorClient:
    return _client


def get_db():
    return _db


def init_db():
    global _client, _db
    mongo_url = os.environ["MONGO_URL"]
    _client = AsyncIOMotorClient(mongo_url)
    _db = _client[os.environ["DB_NAME"]]
    return _db


def close_db():
    global _client
    if _client:
        _client.close()
