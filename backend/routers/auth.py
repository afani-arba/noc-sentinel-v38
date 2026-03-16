"""
Auth router: login and get current user.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from core.db import get_db
from core.auth import create_token, get_current_user, pwd_context

router = APIRouter(prefix="/auth", tags=["auth"])


class UserLogin(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(data: UserLogin):
    db = get_db()
    user = await db.admin_users.find_one({"username": data.username}, {"_id": 0})
    if not user or not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": create_token(user), "user": {k: v for k, v in user.items() if k != "password"}}


@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password"}
