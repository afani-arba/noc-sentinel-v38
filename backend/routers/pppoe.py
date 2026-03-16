"""
PPPoE users router: list, create, update, delete via MikroTik API.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from core.db import get_db
from core.auth import get_current_user, require_admin, require_write
from mikrotik_api import get_api_client

router = APIRouter(tags=["pppoe"])


class PPPoEUserCreate(BaseModel):
    name: str
    password: str
    profile: str = "default"
    service: str = "pppoe"
    comment: str = ""


class PPPoEUserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    service: Optional[str] = None
    comment: Optional[str] = None
    disabled: Optional[str] = None


async def _get_mt_api(device_id: str):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    return get_api_client(device), device


@router.get("/pppoe-users")
async def list_pppoe_users(device_id: str = "", search: str = "", user=Depends(get_current_user)):
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        secrets = await mt.list_pppoe_secrets()
        active_list = await mt.list_pppoe_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")
    active_names = {a.get("name", "") for a in active_list}
    result = []
    for s in secrets:
        s["is_online"] = s.get("name", "") in active_names
        if search and search.lower() not in str(s).lower():
            continue
        result.append(s)
    return result


@router.post("/pppoe-users", status_code=201)
async def create_pppoe_user(device_id: str, data: PPPoEUserCreate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v}
    try:
        return await mt.create_pppoe_secret(body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.put("/pppoe-users/{mt_id}")
async def update_pppoe_user(mt_id: str, device_id: str, data: PPPoEUserUpdate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        return await mt.update_pppoe_secret(mt_id, body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.delete("/pppoe-users/{mt_id}")
async def delete_pppoe_user(mt_id: str, device_id: str, user=Depends(require_admin)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.delete_pppoe_secret(mt_id)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/pppoe-active")
async def list_pppoe_active(device_id: str, user=Depends(get_current_user)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.list_pppoe_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/pppoe-profiles")
async def list_pppoe_profiles(device_id: str, user=Depends(get_current_user)):
    """List PPP profiles from MikroTik (for use in create/edit user forms)."""
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        profiles = await mt.list_pppoe_profiles()
        return [
            {"name": p.get("name", ""), "rate_limit": p.get("rate-limit", p.get("rate_limit", "")), "comment": p.get("comment", "")}
            for p in profiles if p.get("name")
        ]
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")
