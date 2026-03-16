"""
Auth helpers: JWT creation, dependency injection for route protection.
"""
import os
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from datetime import datetime, timezone, timedelta
from core.db import get_db

import warnings

security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = "dev_secret_change_in_production"
    warnings.warn(
        "JWT_SECRET not set! Using insecure default. Set JWT_SECRET in production.",
        UserWarning,
    )


def create_token(user_data: dict) -> str:
    return jwt.encode(
        {
            "sub": user_data["id"],
            "username": user_data["username"],
            "role": user_data["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    db = get_db()
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user = await db.admin_users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user=Depends(get_current_user)):
    if user["role"] != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_write(user=Depends(get_current_user)):
    if user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="Viewer cannot modify data")
    return user
