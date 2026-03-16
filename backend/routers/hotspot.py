"""
Hotspot users router: list, create, update, delete via MikroTik API.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from core.db import get_db
from core.auth import get_current_user, require_admin, require_write
from mikrotik_api import get_api_client

router = APIRouter(tags=["hotspot"])


class HotspotUserCreate(BaseModel):
    name: str
    password: str
    profile: str = "default"
    server: str = "all"
    comment: str = ""


class HotspotUserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    profile: Optional[str] = None
    server: Optional[str] = None
    comment: Optional[str] = None
    disabled: Optional[str] = None


async def _get_mt_api(device_id: str):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    return get_api_client(device), device


@router.get("/hotspot-users")
async def list_hotspot_users(device_id: str = "", search: str = "", user=Depends(get_current_user)):
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        users = await mt.list_hotspot_users()
        active_list = await mt.list_hotspot_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")
    active_names = {a.get("user", "") for a in active_list}
    result = []
    for u in users:
        u["is_online"] = u.get("name", "") in active_names
        if search and search.lower() not in str(u).lower():
            continue
        result.append(u)
    return result


@router.post("/hotspot-users", status_code=201)
async def create_hotspot_user(device_id: str, data: HotspotUserCreate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v}
    try:
        return await mt.create_hotspot_user(body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.put("/hotspot-users/{mt_id}")
async def update_hotspot_user(mt_id: str, device_id: str, data: HotspotUserUpdate, user=Depends(require_write)):
    mt, _ = await _get_mt_api(device_id)
    body = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        return await mt.update_hotspot_user(mt_id, body)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.delete("/hotspot-users/{mt_id}")
async def delete_hotspot_user(mt_id: str, device_id: str, user=Depends(require_admin)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.delete_hotspot_user(mt_id)
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/hotspot-active")
async def list_hotspot_active(device_id: str, user=Depends(get_current_user)):
    mt, _ = await _get_mt_api(device_id)
    try:
        return await mt.list_hotspot_active()
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/hotspot-profiles")
async def list_hotspot_profiles(device_id: str, user=Depends(get_current_user)):
    """List Hotspot user profiles from MikroTik (for use in create/edit user forms)."""
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        profiles = await mt.list_hotspot_profiles()
        return [
            {"name": p.get("name", ""), "rate_limit": p.get("rate-limit", p.get("rate_limit", "")), "shared_users": p.get("shared-users", ""), "comment": p.get("comment", "")}
            for p in profiles if p.get("name")
        ]
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")


@router.get("/hotspot-servers")
async def list_hotspot_servers(device_id: str, user=Depends(get_current_user)):
    """List Hotspot servers from MikroTik."""
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt_api(device_id)
        servers = await mt.list_hotspot_servers()
        return [
            {"name": s.get("name", ""), "interface": s.get("interface", "")}
            for s in servers if s.get("name")
        ]
    except Exception as e:
        raise HTTPException(502, f"MikroTik: {e}")
