"""
Billing router: kelola paket berlangganan dan invoice tagihan pelanggan.
Endpoint prefix: /billing
"""
import uuid
from datetime import datetime, timezone, date
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from core.db import get_db
from core.auth import get_current_user, require_admin, require_write

router = APIRouter(prefix="/billing", tags=["billing"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _invoice_num(seq: int) -> str:
    d = date.today()
    return f"INV-{d.year}-{d.month:02d}-{seq:04d}"


def _rupiah(amount: int) -> str:
    return f"Rp {amount:,.0f}".replace(",", ".")


# ══════════════════════════════════════════════════════════════════════════════
# PACKAGES
# ══════════════════════════════════════════════════════════════════════════════

class PackageCreate(BaseModel):
    name: str
    price: int                       # harga dalam rupiah
    speed_up: str = ""               # misal "20M"
    speed_down: str = ""
    type: str = "pppoe"              # "pppoe" | "hotspot" | "both"
    billing_cycle: int = 30          # hari
    active: bool = True


class PackageUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    speed_up: Optional[str] = None
    speed_down: Optional[str] = None
    type: Optional[str] = None
    billing_cycle: Optional[int] = None
    active: Optional[bool] = None


@router.get("/packages")
async def list_packages(user=Depends(get_current_user)):
    db = get_db()
    pkgs = await db.billing_packages.find({}, {"_id": 0}).to_list(200)
    return pkgs


@router.post("/packages", status_code=201)
async def create_package(data: PackageCreate, user=Depends(require_write)):
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        **data.dict(),
        "created_at": _now(),
    }
    await db.billing_packages.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/packages/{pkg_id}")
async def update_package(pkg_id: str, data: PackageUpdate, user=Depends(require_write)):
    db = get_db()
    update = {k: v for k, v in data.dict().items() if v is not None}
    if not update:
        raise HTTPException(400, "Tidak ada perubahan")
    result = await db.billing_packages.update_one({"id": pkg_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(404, "Paket tidak ditemukan")
    return {"message": "Paket diupdate"}


@router.delete("/packages/{pkg_id}")
async def delete_package(pkg_id: str, user=Depends(require_admin)):
    db = get_db()
    result = await db.billing_packages.delete_one({"id": pkg_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Paket tidak ditemukan")
    return {"message": "Paket dihapus"}


@router.post("/packages/sync-from-mikrotik")
async def sync_packages_from_mikrotik(
    device_id: str = Query(..., description="ID device MikroTik"),
    user=Depends(require_admin),
):
    """
    Ambil semua profile PPPoE + Hotspot dari device MikroTik.
    Jika profile belum ada di billing_packages → buat baru dengan price=0.
    Jika sudah ada → biarkan (harga tidak diubah).
    Return: daftar paket yang baru ditambahkan dan yang sudah ada.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    from mikrotik_api import get_api_client
    try:
        mt = get_api_client(device)
    except Exception as e:
        raise HTTPException(502, f"Gagal inisialisasi MikroTik client: {e}")

    # Ambil profile dari MikroTik
    pppoe_profiles, hotspot_profiles = [], []
    try:
        pppoe_profiles = await mt.list_pppoe_profiles() or []
    except Exception as e:
        pppoe_profiles = []

    try:
        hotspot_profiles = await mt.list_hotspot_profiles() or []
    except Exception as e:
        hotspot_profiles = []

    added, existing = [], []
    device_name = device.get("name", device.get("host", device_id))

    # Proses PPPoE profiles
    for p in pppoe_profiles:
        pname = p.get("name", "")
        if not pname or pname == "default":
            continue
        existing_pkg = await db.billing_packages.find_one({
            "profile_name": pname,
            "service_type": "pppoe",
            "source_device_id": device_id,
        })
        if existing_pkg:
            existing.append(pname)
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "name": pname,
            "profile_name": pname,
            "source_device_id": device_id,
            "source_device_name": device_name,
            "service_type": "pppoe",
            "price": 0,
            "speed_up": p.get("rate-limit", "").split("/")[1] if "/" in p.get("rate-limit", "") else "",
            "speed_down": p.get("rate-limit", "").split("/")[0] if "/" in p.get("rate-limit", "") else "",
            "billing_cycle": 30,
            "active": True,
            "synced_at": _now(),
            "created_at": _now(),
        }
        await db.billing_packages.insert_one(doc)
        doc.pop("_id", None)
        added.append(pname)

    # Proses Hotspot profiles
    for p in hotspot_profiles:
        pname = p.get("name", "")
        if not pname or pname == "default":
            continue
        existing_pkg = await db.billing_packages.find_one({
            "profile_name": pname,
            "service_type": "hotspot",
            "source_device_id": device_id,
        })
        if existing_pkg:
            existing.append(f"{pname} (hs)")
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "name": f"{pname} (Hotspot)",
            "profile_name": pname,
            "source_device_id": device_id,
            "source_device_name": device_name,
            "service_type": "hotspot",
            "price": 0,
            "speed_up": p.get("rate-limit", "").split("/")[1] if "/" in p.get("rate-limit", "") else "",
            "speed_down": p.get("rate-limit", "").split("/")[0] if "/" in p.get("rate-limit", "") else "",
            "billing_cycle": 30,
            "active": True,
            "synced_at": _now(),
            "created_at": _now(),
        }
        await db.billing_packages.insert_one(doc)
        doc.pop("_id", None)
        added.append(f"{pname} (Hotspot)")

    return {
        "message": f"Sync selesai: {len(added)} paket baru, {len(existing)} sudah ada",
        "added": added,
        "existing": existing,
        "total_pppoe": len(pppoe_profiles),
        "total_hotspot": len(hotspot_profiles),
    }


@router.patch("/packages/{pkg_id}/price")
async def update_package_price(pkg_id: str, data: dict, user=Depends(require_write)):
    """Update harga paket (dipakai admin untuk set harga setelah sync dari MikroTik)."""
    db = get_db()
    price = data.get("price")
    active = data.get("active")
    update_set = {}
    if price is not None:
        try:
            update_set["price"] = int(price)
        except (ValueError, TypeError):
            raise HTTPException(400, "Harga tidak valid")
    if active is not None:
        update_set["active"] = bool(active)
    if not update_set:
        raise HTTPException(400, "Tidak ada perubahan")
    result = await db.billing_packages.update_one({"id": pkg_id}, {"$set": update_set})
    if result.matched_count == 0:
        raise HTTPException(404, "Paket tidak ditemukan")
    return {"message": "Harga paket diupdate"}


# ══════════════════════════════════════════════════════════════════════════════
# INVOICES

# ══════════════════════════════════════════════════════════════════════════════

class InvoiceCreate(BaseModel):
    customer_id: str
    package_id: str
    amount: int
    discount: int = 0
    period_start: str          # "2026-03-01"
    period_end: str            # "2026-03-31"
    due_date: str              # "2026-03-10"
    notes: str = ""


class PaymentUpdate(BaseModel):
    payment_method: str = "cash"   # "cash" | "transfer" | "qris"
    paid_notes: str = ""


@router.get("/stats")
async def billing_stats(
    month: int = Query(0),    # 0 = bulan ini
    year: int = Query(0),
    user=Depends(get_current_user),
):
    """Dashboard stats: total tagihan, lunas, belum bayar, jatuh tempo."""
    db = get_db()
    today = date.today()
    m = month or today.month
    y = year or today.year

    # Filter periode bulan
    period_prefix = f"{y}-{m:02d}"
    q = {"period_start": {"$regex": f"^{period_prefix}"}}

    all_inv = await db.invoices.find(q, {"_id": 0}).to_list(5000)

    total_amount = sum(i.get("total", 0) for i in all_inv)
    paid = [i for i in all_inv if i.get("status") == "paid"]
    unpaid = [i for i in all_inv if i.get("status") in ("unpaid", "overdue")]
    overdue = [i for i in all_inv if i.get("status") == "overdue" or (
        i.get("status") == "unpaid" and i.get("due_date", "") < today.isoformat()
    )]

    paid_amount = sum(i.get("total", 0) for i in paid)
    unpaid_amount = sum(i.get("total", 0) for i in unpaid)

    # Update overdue status
    overdue_ids = [i["id"] for i in overdue if i.get("status") == "unpaid"]
    if overdue_ids:
        await db.invoices.update_many(
            {"id": {"$in": overdue_ids}},
            {"$set": {"status": "overdue"}}
        )

    return {
        "month": m,
        "year": y,
        "total_invoices": len(all_inv),
        "total_amount": total_amount,
        "paid_count": len(paid),
        "paid_amount": paid_amount,
        "unpaid_count": len(unpaid),
        "unpaid_amount": unpaid_amount,
        "overdue_count": len(overdue),
    }


@router.get("/invoices")
async def list_invoices(
    month: int = Query(0),
    year: int = Query(0),
    status: str = Query(""),       # "" | "paid" | "unpaid" | "overdue"
    search: str = Query(""),
    customer_id: str = Query(""),
    user=Depends(get_current_user),
):
    db = get_db()
    today = date.today()
    m = month or today.month
    y = year or today.year
    period_prefix = f"{y}-{m:02d}"

    q = {"period_start": {"$regex": f"^{period_prefix}"}}
    if status:
        q["status"] = status
    if customer_id:
        q["customer_id"] = customer_id

    invoices = await db.invoices.find(q, {"_id": 0}).sort("due_date", 1).to_list(5000)

    # Enrich dengan data customer dan package
    customer_ids = list({i["customer_id"] for i in invoices})
    pkg_ids = list({i["package_id"] for i in invoices})

    customers = {c["id"]: c for c in await db.customers.find(
        {"id": {"$in": customer_ids}}, {"_id": 0}
    ).to_list(1000)}

    packages = {p["id"]: p for p in await db.billing_packages.find(
        {"id": {"$in": pkg_ids}}, {"_id": 0}
    ).to_list(200)}

    result = []
    for inv in invoices:
        customer = customers.get(inv["customer_id"], {})
        pkg = packages.get(inv["package_id"], {})
        inv["customer_name"] = customer.get("name", "—")
        inv["customer_username"] = customer.get("username", "—")
        inv["customer_phone"] = customer.get("phone", "")
        inv["package_name"] = pkg.get("name", "—")

        # Auto-update overdue
        if inv["status"] == "unpaid" and inv.get("due_date", "") < today.isoformat():
            inv["status"] = "overdue"
            await db.invoices.update_one({"id": inv["id"]}, {"$set": {"status": "overdue"}})

        if search:
            s = search.lower()
            if not (s in inv.get("customer_name", "").lower()
                    or s in inv.get("customer_username", "").lower()
                    or s in inv.get("invoice_number", "").lower()):
                continue
        result.append(inv)

    return result


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, user=Depends(get_current_user)):
    db = get_db()
    inv = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan")

    customer = await db.customers.find_one({"id": inv["customer_id"]}, {"_id": 0}) or {}
    pkg = await db.billing_packages.find_one({"id": inv["package_id"]}, {"_id": 0}) or {}

    inv["customer"] = customer
    inv["package"] = pkg
    return inv


@router.post("/invoices", status_code=201)
async def create_invoice(data: InvoiceCreate, user=Depends(require_write)):
    db = get_db()

    # Validasi customer dan package
    customer = await db.customers.find_one({"id": data.customer_id})
    if not customer:
        raise HTTPException(404, "Customer tidak ditemukan")
    pkg = await db.billing_packages.find_one({"id": data.package_id})
    if not pkg:
        raise HTTPException(404, "Paket tidak ditemukan")

    # Cek duplicate (customer + periode yang sama)
    existing = await db.invoices.find_one({
        "customer_id": data.customer_id,
        "period_start": data.period_start,
    })
    if existing:
        raise HTTPException(409, "Invoice periode ini sudah ada untuk customer tersebut")

    # Nomor invoice: hitung urutan bulan ini
    today = date.today()
    period_prefix = f"{today.year}-{today.month:02d}"
    count = await db.invoices.count_documents(
        {"period_start": {"$regex": f"^{period_prefix}"}}
    )

    total = data.amount - data.discount
    doc = {
        "id": str(uuid.uuid4()),
        "invoice_number": _invoice_num(count + 1),
        "customer_id": data.customer_id,
        "package_id": data.package_id,
        "amount": data.amount,
        "discount": data.discount,
        "total": total,
        "period_start": data.period_start,
        "period_end": data.period_end,
        "due_date": data.due_date,
        "status": "unpaid",
        "notes": data.notes,
        "paid_at": None,
        "payment_method": None,
        "created_at": _now(),
    }
    await db.invoices.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/invoices/bulk-create")
async def bulk_create_invoices(
    month: int = Query(...),
    year: int = Query(...),
    service_type: str = Query(""),    # "" = semua, "pppoe", "hotspot"
    user=Depends(require_write),
):
    """
    Buat invoice massal untuk semua customer aktif yang belum punya tagihan bulan ini.
    Harga diambil dari paket yang ditetapkan. Customer tanpa paket dilewati.
    """
    db = get_db()
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    period_start = f"{year}-{month:02d}-01"
    period_end = f"{year}-{month:02d}-{last_day:02d}"
    period_prefix = f"{year}-{month:02d}"

    q = {"active": True}
    if service_type:
        q["service_type"] = service_type

    customers = await db.customers.find(q).to_list(5000)

    created = 0
    skipped = 0
    errors = []

    for c in customers:
        if not c.get("package_id"):
            skipped += 1
            continue

        existing = await db.invoices.find_one({
            "customer_id": c["id"],
            "period_start": {"$regex": f"^{period_prefix}"},
        })
        if existing:
            skipped += 1
            continue

        pkg = await db.billing_packages.find_one({"id": c["package_id"]})
        if not pkg:
            errors.append(f"{c['name']}: paket tidak ditemukan")
            skipped += 1
            continue

        due_day = min(c.get("due_day", 10), last_day)
        due_date = f"{year}-{month:02d}-{due_day:02d}"

        count = await db.invoices.count_documents(
            {"period_start": {"$regex": f"^{period_prefix}"}}
        ) + created

        doc = {
            "id": str(uuid.uuid4()),
            "invoice_number": _invoice_num(count + 1),
            "customer_id": c["id"],
            "package_id": c["package_id"],
            "amount": pkg["price"],
            "discount": 0,
            "total": pkg["price"],
            "period_start": period_start,
            "period_end": period_end,
            "due_date": due_date,
            "status": "unpaid",
            "notes": "",
            "paid_at": None,
            "payment_method": None,
            "created_at": _now(),
        }
        await db.invoices.insert_one(doc)
        created += 1

    return {
        "message": f"Selesai: {created} invoice dibuat, {skipped} dilewati",
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


@router.patch("/invoices/{invoice_id}/pay")
async def mark_paid(invoice_id: str, data: PaymentUpdate, user=Depends(require_write)):
    """Tandai invoice sebagai lunas dan auto-enable user MikroTik jika sebelumnya di-disable."""
    db = get_db()
    inv = await db.invoices.find_one({"id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan")
    if inv.get("status") == "paid":
        raise HTTPException(400, "Invoice sudah lunas")

    paid_at = _now()
    await db.invoices.update_one(
        {"id": invoice_id},
        {"$set": {
            "status": "paid",
            "paid_at": paid_at,
            "payment_method": data.payment_method,
            "paid_notes": data.paid_notes,
        }}
    )

    # Auto-enable user MikroTik setelah lunas
    mt_msg = ""
    try:
        from mikrotik_api import get_api_client
        customer = await db.customers.find_one({"id": inv["customer_id"]})
        if customer:
            device = await db.devices.find_one({"id": customer.get("device_id", "")})
            if device:
                mt = get_api_client(device)
                username = customer.get("username", "")
                svc = customer.get("service_type", "pppoe")
                if svc == "pppoe":
                    await mt.enable_pppoe_user(username)
                else:
                    await mt.enable_hotspot_user(username)
                mt_msg = f" | User '{username}' di-enable di MikroTik"
    except Exception as e:
        mt_msg = f" | Gagal enable MikroTik: {e}"

    return {"message": f"Invoice ditandai lunas{mt_msg}", "paid_at": paid_at}


@router.patch("/invoices/{invoice_id}/unpay")
async def mark_unpaid(invoice_id: str, user=Depends(require_admin)):
    """Batalkan pembayaran (rollback ke unpaid)."""
    db = get_db()
    await db.invoices.update_one(
        {"id": invoice_id},
        {"$set": {"status": "unpaid", "paid_at": None, "payment_method": None}}
    )
    return {"message": "Status invoice dikembalikan ke belum bayar"}


@router.delete("/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, user=Depends(require_admin)):
    db = get_db()
    result = await db.invoices.delete_one({"id": invoice_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Invoice tidak ditemukan")
    return {"message": "Invoice dihapus"}


# ══════════════════════════════════════════════════════════════════════════════
# MIKROTIK DISCONNECT / RECONNECT
# ══════════════════════════════════════════════════════════════════════════════

async def _toggle_mikrotik_user(db, invoice_id: str, action: str):
    """Helper: disable atau enable user MikroTik berdasarkan invoice."""
    inv = await db.invoices.find_one({"id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan")
    customer = await db.customers.find_one({"id": inv["customer_id"]})
    if not customer:
        raise HTTPException(404, "Customer tidak ditemukan")
    device = await db.devices.find_one({"id": customer.get("device_id", "")})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    from mikrotik_api import get_api_client
    mt = get_api_client(device)
    username = customer.get("username", "")
    svc = customer.get("service_type", "pppoe")
    try:
        if action == "disable":
            if svc == "pppoe":
                await mt.disable_pppoe_user(username)
            else:
                await mt.disable_hotspot_user(username)
        else:
            if svc == "pppoe":
                await mt.enable_pppoe_user(username)
            else:
                await mt.enable_hotspot_user(username)
    except Exception as e:
        raise HTTPException(502, f"Gagal {action} user MikroTik: {e}")
    return username


@router.post("/invoices/{invoice_id}/disable-user")
async def disable_user(invoice_id: str, user=Depends(require_write)):
    """Disable user PPPoE/Hotspot di MikroTik (putus koneksi)."""
    db = get_db()
    username = await _toggle_mikrotik_user(db, invoice_id, "disable")
    # Update flag di invoice
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"mt_disabled": True}})
    return {"message": f"User '{username}' berhasil di-disable di MikroTik"}


@router.post("/invoices/{invoice_id}/enable-user")
async def enable_user(invoice_id: str, user=Depends(require_write)):
    """Enable kembali user PPPoE/Hotspot di MikroTik."""
    db = get_db()
    username = await _toggle_mikrotik_user(db, invoice_id, "enable")
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"mt_disabled": False}})
    return {"message": f"User '{username}' berhasil di-enable di MikroTik"}


@router.post("/invoices/sync-status")
async def sync_mikrotik_status(
    action: str = Query(...),  # "disable" atau "enable"
    status_filter: str = Query("overdue"),  # filter invoice: overdue, unpaid
    user=Depends(require_admin),
):
    """
    Bulk disable/enable user MikroTik berdasarkan status invoice.
    action=disable: putus semua yang overdue
    action=enable: sambungkan kembali semua yang sudah lunas
    """
    if action not in ("disable", "enable"):
        raise HTTPException(400, "action harus 'disable' atau 'enable'")

    db = get_db()
    from mikrotik_api import get_api_client

    q = {"status": status_filter} if action == "disable" else {"status": "paid"}
    invoices = await db.invoices.find(q).to_list(5000)

    success, failed, skipped = 0, 0, 0
    errors = []

    for inv in invoices:
        customer = await db.customers.find_one({"id": inv.get("customer_id", "")})
        if not customer:
            skipped += 1
            continue
        device = await db.devices.find_one({"id": customer.get("device_id", "")})
        if not device:
            skipped += 1
            continue
        try:
            mt = get_api_client(device)
            username = customer.get("username", "")
            svc = customer.get("service_type", "pppoe")
            if action == "disable":
                if svc == "pppoe":
                    await mt.disable_pppoe_user(username)
                else:
                    await mt.disable_hotspot_user(username)
                await db.invoices.update_one({"id": inv["id"]}, {"$set": {"mt_disabled": True}})
            else:
                if svc == "pppoe":
                    await mt.enable_pppoe_user(username)
                else:
                    await mt.enable_hotspot_user(username)
                await db.invoices.update_one({"id": inv["id"]}, {"$set": {"mt_disabled": False}})
            success += 1
        except Exception as e:
            failed += 1
            errors.append(f"{customer.get('name', '?')}: {e}")

    return {
        "message": f"Sync selesai: {success} berhasil, {failed} gagal, {skipped} dilewati",
        "success": success, "failed": failed, "skipped": skipped,
        "errors": errors[:20],
    }


# ══════════════════════════════════════════════════════════════════════════════
# MONTHLY SUMMARY (untuk grafik tren pendapatan)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/monthly-summary")
async def monthly_summary(
    months: int = Query(6),   # jumlah bulan ke belakang
    user=Depends(get_current_user),
):
    """Data tren pendapatan N bulan terakhir untuk grafik bar/line chart."""
    from dateutil.relativedelta import relativedelta  # pip install python-dateutil
    db = get_db()
    today = date.today()
    result = []

    for i in range(months - 1, -1, -1):
        d = today - relativedelta(months=i)
        prefix = f"{d.year}-{d.month:02d}"
        inv_month = await db.invoices.find(
            {"period_start": {"$regex": f"^{prefix}"}}, {"_id": 0}
        ).to_list(5000)

        paid = [x for x in inv_month if x.get("status") == "paid"]
        unpaid = [x for x in inv_month if x.get("status") in ("unpaid", "overdue")]
        result.append({
            "month": d.month,
            "year": d.year,
            "label": d.strftime("%b %Y"),
            "total": sum(x.get("total", 0) for x in inv_month),
            "paid": sum(x.get("total", 0) for x in paid),
            "unpaid": sum(x.get("total", 0) for x in unpaid),
            "count": len(inv_month),
            "paid_count": len(paid),
        })
    return result


# ── WhatsApp link helper ──────────────────────────────────────────────────────

@router.get("/invoices/{invoice_id}/whatsapp-link")
async def get_whatsapp_link(invoice_id: str, user=Depends(get_current_user)):
    """Generate link wa.me dengan template pesan tagihan."""
    import urllib.parse
    db = get_db()
    inv = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan")

    customer = await db.customers.find_one({"id": inv["customer_id"]}, {"_id": 0}) or {}
    pkg = await db.billing_packages.find_one({"id": inv["package_id"]}, {"_id": 0}) or {}

    phone = customer.get("phone", "").strip().replace(" ", "").replace("-", "")
    if not phone:
        raise HTTPException(400, "Nomor telepon pelanggan belum diisi")

    # Normalize: 08xx → 628xx
    if phone.startswith("0"):
        phone = "62" + phone[1:]
    elif not phone.startswith("62"):
        phone = "62" + phone

    name = customer.get("name", "Pelanggan")
    invoice_no = inv.get("invoice_number", "")
    total = _rupiah(inv.get("total", 0))
    due = inv.get("due_date", "")
    pkg_name = pkg.get("name", "")
    period = f"{inv.get('period_start','')} s/d {inv.get('period_end','')}"

    message = (
        f"Yth. {name},\n\n"
        f"Tagihan internet Anda:\n"
        f"No. Invoice : {invoice_no}\n"
        f"Paket       : {pkg_name}\n"
        f"Periode     : {period}\n"
        f"Total       : {total}\n"
        f"Jatuh Tempo : {due}\n\n"
        f"Mohon segera melakukan pembayaran. Terima kasih 🙏"
    )

    link = f"https://wa.me/{phone}?text={urllib.parse.quote(message)}"
    return {"link": link, "phone": phone}
