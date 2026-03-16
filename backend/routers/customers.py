"""
Customers router: manage pelanggan PPPoE/Hotspot untuk billing.
Import otomatis dari MikroTik, atau tambah manual.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from core.db import get_db
from core.auth import get_current_user, require_admin, require_write
from mikrotik_api import get_api_client

router = APIRouter(prefix="/customers", tags=["customers"])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Models ────────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str
    phone: str = ""
    address: str = ""
    service_type: str = "pppoe"          # "pppoe" | "hotspot"
    username: str                         # username di MikroTik
    device_id: str                        # MikroTik device
    package_id: str = ""
    due_day: int = 10                     # tanggal jatuh tempo tiap bulan
    active: bool = True


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    package_id: Optional[str] = None
    due_day: Optional[int] = None
    active: Optional[bool] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_customers(
    search: str = Query(""),
    service_type: str = Query(""),
    active: Optional[bool] = Query(None),
    user=Depends(get_current_user),
):
    db = get_db()
    q = {}
    if service_type:
        q["service_type"] = service_type
    if active is not None:
        q["active"] = active

    cursor = db.customers.find(q, {"_id": 0})
    results = await cursor.to_list(length=1000)

    if search:
        s = search.lower()
        results = [c for c in results if (
            s in c.get("name", "").lower()
            or s in c.get("username", "").lower()
            or s in c.get("phone", "").lower()
        )]
    return results


@router.get("/{customer_id}")
async def get_customer(customer_id: str, user=Depends(get_current_user)):
    db = get_db()
    c = await db.customers.find_one({"id": customer_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Customer tidak ditemukan")
    return c


@router.post("", status_code=201)
async def create_customer(data: CustomerCreate, user=Depends(require_write)):
    db = get_db()

    # Cek duplicate username+device
    existing = await db.customers.find_one(
        {"username": data.username, "device_id": data.device_id}
    )
    if existing:
        raise HTTPException(409, f"Username '{data.username}' sudah terdaftar di device ini")

    doc = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "phone": data.phone,
        "address": data.address,
        "service_type": data.service_type,
        "username": data.username,
        "device_id": data.device_id,
        "package_id": data.package_id,
        "due_day": data.due_day,
        "active": data.active,
        "created_at": _now(),
    }
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/{customer_id}")
async def update_customer(customer_id: str, data: CustomerUpdate, user=Depends(require_write)):
    db = get_db()
    update = {k: v for k, v in data.dict().items() if v is not None}
    if not update:
        raise HTTPException(400, "Tidak ada data yang diupdate")
    result = await db.customers.update_one({"id": customer_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(404, "Customer tidak ditemukan")
    return {"message": "Customer berhasil diupdate"}


@router.delete("/{customer_id}")
async def delete_customer(customer_id: str, user=Depends(require_admin)):
    db = get_db()
    result = await db.customers.delete_one({"id": customer_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Customer tidak ditemukan")
    return {"message": "Customer dihapus"}


# ── Import dari MikroTik ──────────────────────────────────────────────────────

@router.post("/import/pppoe")
async def import_from_pppoe(
    device_id: str,
    due_day: int = 10,
    user=Depends(require_write),
):
    """
    Import PPPoE secrets dari MikroTik sebagai customers.
    Skip yang sudah ada.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    try:
        mt = get_api_client(device)
        secrets = await mt.list_pppoe_secrets()
    except Exception as e:
        raise HTTPException(502, f"Gagal terhubung ke MikroTik: {e}")

    imported = 0
    skipped = 0
    for secret in secrets:
        username = secret.get("name", "")
        if not username:
            continue
        existing = await db.customers.find_one(
            {"username": username, "device_id": device_id}
        )
        if existing:
            skipped += 1
            continue

        # Gunakan comment MikroTik sebagai nama pelanggan jika ada
        comment = secret.get("comment", "")
        name = comment if comment else username

        doc = {
            "id": str(uuid.uuid4()),
            "name": name,
            "phone": "",
            "address": "",
            "service_type": "pppoe",
            "username": username,
            "device_id": device_id,
            "package_id": "",
            "due_day": due_day,
            "active": secret.get("disabled", "false") != "true",
            "created_at": _now(),
            "profile": secret.get("profile", ""),
        }
        await db.customers.insert_one(doc)
        imported += 1

    return {
        "message": f"Import selesai: {imported} baru, {skipped} sudah ada",
        "imported": imported,
        "skipped": skipped,
    }


@router.post("/import/hotspot")
async def import_from_hotspot(
    device_id: str,
    due_day: int = 10,
    user=Depends(require_write),
):
    """
    Import Hotspot users dari MikroTik sebagai customers.
    Skip yang sudah ada.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    try:
        mt = get_api_client(device)
        hs_users = await mt.list_hotspot_users()
    except Exception as e:
        raise HTTPException(502, f"Gagal terhubung ke MikroTik: {e}")

    imported = 0
    skipped = 0
    for usr in hs_users:
        username = usr.get("name", "")
        if not username:
            continue
        existing = await db.customers.find_one(
            {"username": username, "device_id": device_id}
        )
        if existing:
            skipped += 1
            continue

        comment = usr.get("comment", "")
        name = comment if comment else username

        doc = {
            "id": str(uuid.uuid4()),
            "name": name,
            "phone": "",
            "address": "",
            "service_type": "hotspot",
            "username": username,
            "device_id": device_id,
            "package_id": "",
            "due_day": due_day,
            "active": usr.get("disabled", "false") != "true",
            "created_at": _now(),
            "profile": usr.get("profile", ""),
        }
        await db.customers.insert_one(doc)
        imported += 1

    return {
        "message": f"Import selesai: {imported} baru, {skipped} sudah ada",
        "imported": imported,
        "skipped": skipped,
    }
