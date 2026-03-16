"""
Admin users router: CRUD for system users.
"""
import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from core.db import get_db
from core.auth import require_admin, pwd_context

router = APIRouter(prefix="/admin", tags=["admin"])


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "user"
    allowed_devices: List[str] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    allowed_devices: Optional[List[str]] = None


VALID_ROLES = ["administrator", "viewer", "user"]


@router.get("/users")
async def list_admin_users(user=Depends(require_admin)):
    db = get_db()
    return await db.admin_users.find({}, {"_id": 0, "password": 0}).to_list(100)


@router.post("/users", status_code=201)
async def create_admin_user(data: UserCreate, user=Depends(require_admin)):
    db = get_db()
    if await db.admin_users.find_one({"username": data.username}):
        raise HTTPException(400, "Username exists")
    if data.role not in VALID_ROLES:
        raise HTTPException(400, "Invalid role")
    doc = {
        "id": str(uuid.uuid4()), "username": data.username,
        "password": pwd_context.hash(data.password), "full_name": data.full_name,
        "role": data.role, "allowed_devices": data.allowed_devices,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.admin_users.insert_one(doc)
    return {k: v for k, v in doc.items() if k not in ("_id", "password")}


@router.put("/users/{user_id}")
async def update_admin_user(user_id: str, data: UserUpdate, user=Depends(require_admin)):
    db = get_db()
    upd = {}
    if data.full_name is not None:
        upd["full_name"] = data.full_name
    if data.role is not None:
        if data.role not in VALID_ROLES:
            raise HTTPException(400, "Invalid role")
        upd["role"] = data.role
    if data.password is not None:
        upd["password"] = pwd_context.hash(data.password)
    if data.allowed_devices is not None:
        upd["allowed_devices"] = data.allowed_devices
    if not upd:
        raise HTTPException(400, "Nothing to update")
    r = await db.admin_users.update_one({"id": user_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    return await db.admin_users.find_one({"id": user_id}, {"_id": 0, "password": 0})


@router.delete("/users/{user_id}")
async def delete_admin_user(user_id: str, user=Depends(require_admin)):
    db = get_db()
    target = await db.admin_users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Not found")
    if target["id"] == user["id"]:
        raise HTTPException(400, "Cannot delete yourself")
    await db.admin_users.delete_one({"id": user_id})
    return {"message": "Deleted"}
