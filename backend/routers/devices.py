"""
Devices router: CRUD + dashboard + SNMP test + MikroTik API test.
"""
import uuid
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from core.db import get_db
from core.auth import get_current_user, require_admin
import snmp_service
from mikrotik_api import get_api_client
from core.polling import poll_single_device

router = APIRouter(tags=["devices"])
logger = logging.getLogger(__name__)

SAFE_DEVICE_FIELDS = {"_id": 0, "snmp_community": 0, "api_password": 0, "last_poll_data": 0}


class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    snmp_community: str = "public"
    snmp_port: int = 161
    api_mode: str = "rest"
    api_username: str = "admin"
    api_password: str = ""
    api_port: Optional[int] = None
    use_https: bool = False
    api_ssl: bool = True
    api_plaintext_login: bool = True
    description: str = ""


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    snmp_community: Optional[str] = None
    snmp_port: Optional[int] = None
    api_mode: Optional[str] = None
    api_username: Optional[str] = None
    api_password: Optional[str] = None
    api_port: Optional[int] = None
    use_https: Optional[bool] = None
    api_ssl: Optional[bool] = None
    api_plaintext_login: Optional[bool] = None
    description: Optional[str] = None


def filter_devices_for_user(devices: list, user: dict) -> list:
    if user.get("role") == "administrator":
        return devices
    allowed = user.get("allowed_devices", [])
    if not allowed:
        return []
    return [d for d in devices if d.get("id") in allowed]


@router.get("/devices")
async def list_devices(user=Depends(get_current_user)):
    db = get_db()
    devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(100)
    return filter_devices_for_user(devs, user)


@router.get("/devices/full")
async def list_devices_full(user=Depends(require_admin)):
    db = get_db()
    devs = await db.devices.find({}, {"_id": 0}).to_list(100)
    for d in devs:
        d.pop("last_poll_data", None)
    return devs


@router.get("/devices/all")
async def list_all_devices_for_admin(user=Depends(require_admin)):
    db = get_db()
    return await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1}).to_list(100)


@router.post("/devices", status_code=201)
async def create_device(data: DeviceCreate, user=Depends(require_admin)):
    db = get_db()
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc.update({
        "status": "unknown", "model": "", "sys_name": "", "ros_version": "",
        "uptime": "", "serial": "", "cpu_load": 0, "memory_usage": 0,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    await db.devices.insert_one(doc)
    asyncio.create_task(poll_single_device(doc))
    return {k: v for k, v in doc.items() if k not in ("_id", "snmp_community", "api_password", "last_poll_data")}


@router.put("/devices/{device_id}")
async def update_device(device_id: str, data: DeviceUpdate, user=Depends(require_admin)):
    db = get_db()
    upd = {k: v for k, v in data.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    r = await db.devices.update_one({"id": device_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    return await db.devices.find_one({"id": device_id}, SAFE_DEVICE_FIELDS)


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, user=Depends(require_admin)):
    db = get_db()
    r = await db.devices.delete_one({"id": device_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Device not found")
    await db.traffic_history.delete_many({"device_id": device_id})
    await db.traffic_snapshots.delete_one({"device_id": device_id})
    return {"message": "Deleted"}


@router.post("/devices/{device_id}/test-snmp")
async def test_snmp(device_id: str, user=Depends(get_current_user)):
    db = get_db()
    d = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    snmp_result = await snmp_service.test_connection(d["ip_address"], d.get("snmp_port", 161), d.get("snmp_community", "public"))
    ping_result = await snmp_service.ping_host(d["ip_address"])
    return {"snmp": snmp_result, "ping": ping_result}


@router.post("/devices/{device_id}/test-api")
async def test_api(device_id: str, user=Depends(get_current_user)):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    return await mt.test_connection()


@router.get("/devices/{device_id}/system-resource")
async def get_system_resource(device_id: str, user=Depends(get_current_user)):
    """Ambil info CPU, memory, uptime langsung dari MikroTik REST API (ROS 7.x)."""
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        r = await mt.get_system_resource()
        return r
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.get("/devices/{device_id}/interfaces")
async def get_interfaces(device_id: str, user=Depends(get_current_user)):
    """List semua interface dari MikroTik (nama, status, type, MAC)."""
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        ifaces = await mt.list_interfaces()
        return ifaces
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.get("/devices/{device_id}/ip-addresses")
async def get_ip_addresses(device_id: str, user=Depends(get_current_user)):
    """List semua IP address yang dikonfigurasi di MikroTik."""
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        addrs = await mt.list_ip_addresses()
        return addrs
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.get("/devices/{device_id}/system-health")
async def get_system_health(device_id: str, user=Depends(get_current_user)):
    """
    Ambil data sensor hardware dari MikroTik REST API /rest/system/health.
    ROS 7.x: cpu-temperature, board-temperature, voltage, power-consumption.
    Lebih reliable dari SNMP untuk device yang tidak support MikroTik private MIB.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    mt = get_api_client(device)
    try:
        health = await mt.get_system_health()
        return health
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


@router.post("/devices/{device_id}/poll")
async def trigger_poll(device_id: str, user=Depends(get_current_user)):
    db = get_db()
    d = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    r = await poll_single_device(d)
    return {"reachable": r["reachable"]}


@router.post("/devices/test-new")
async def test_new(data: DeviceCreate, user=Depends(get_current_user)):
    snmp_r = await snmp_service.test_connection(data.ip_address, data.snmp_port, data.snmp_community)
    ping_r = await snmp_service.ping_host(data.ip_address)
    mt = get_api_client(data.model_dump())
    api_r = await mt.test_connection()
    return {"snmp": snmp_r, "ping": ping_r, "api": api_r}


# ── Dashboard ──
@router.get("/dashboard/stats")
async def dashboard_stats(device_id: str = "", interface: str = "", user=Depends(get_current_user)):
    db = get_db()
    all_devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(100)
    online = sum(1 for d in all_devs if d.get("status") == "online")
    device = await db.devices.find_one({"id": device_id}, {"_id": 0}) if device_id else None

    query = {"device_id": device_id} if device_id else {}
    # BUG 3 FIX: limit 200→300 agar cukup untuk 144 titik terbaru
    history = await db.traffic_history.find(query, {"_id": 0}).sort("timestamp", -1).to_list(300)
    history.reverse()

    traffic_data = []
    for h in history[-144:]:   # BUG 3 FIX: was -60 (30 menit), now 144×30s = 72 menit
        try:
            utc_time = datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00"))
            local_time = (utc_time.replace(tzinfo=None) if utc_time.tzinfo else utc_time) + timedelta(hours=7)
            time_label = local_time.strftime("%H:%M")
        except Exception:
            time_label = ""
        bw = h.get("bandwidth") or {}
        if interface and interface != "all":
            ib = bw.get(interface, {})
            dl, ul = ib.get("download_bps", 0), ib.get("upload_bps", 0)
        else:
            dl = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
            ul = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))
        traffic_data.append({
            "time": time_label, "download": round(dl / 1_000_000, 2), "upload": round(ul / 1_000_000, 2),
            "ping": h.get("ping_ms", 0), "jitter": h.get("jitter_ms", 0)
        })

    ifaces = []
    if device and device.get("last_poll_data"):
        ifaces = [i["name"] for i in device["last_poll_data"].get("interfaces", [])]

    sys_h = {"cpu": 0, "memory": 0, "cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0}
    if device:
        sys_h = {
            "cpu": device.get("cpu_load", 0), "memory": device.get("memory_usage", 0),
            "cpu_temp": device.get("cpu_temp", 0), "board_temp": device.get("board_temp", 0),
            "voltage": device.get("voltage", 0), "power": device.get("power", 0),
        }

    alerts = []
    for d in all_devs:
        if d.get("status") == "offline":
            alerts.append({"id": d["id"], "type": "error", "message": f"{d['name']} OFFLINE", "time": (d.get("last_poll") or "")[:16]})
        if d.get("cpu_load", 0) > 80:
            alerts.append({"id": d["id"] + "c", "type": "warning", "message": f"CPU {d['cpu_load']}% on {d['name']}", "time": (d.get("last_poll") or "")[:16]})
        if d.get("memory_usage", 0) > 80:
            alerts.append({"id": d["id"] + "m", "type": "warning", "message": f"Memory {d['memory_usage']}% on {d['name']}", "time": (d.get("last_poll") or "")[:16]})
    if not alerts:
        alerts.append({"id": "ok", "type": "success", "message": "All systems normal", "time": datetime.now(timezone.utc).strftime("%H:%M")})

    last = traffic_data[-1] if traffic_data else {"download": 0, "upload": 0}
    return {
        "devices": {"total": len(all_devs), "online": online},
        "total_bandwidth": {"download": last["download"], "upload": last["upload"]},
        "traffic_data": traffic_data, "alerts": alerts,
        "system_health": sys_h, "interfaces": ifaces,
        "selected_device": {
            "name": device.get("name", ""), "model": device.get("model", ""),
            "identity": device.get("identity", device.get("sys_name", "")),
            "uptime": device.get("uptime", ""), "ros_version": device.get("ros_version", ""),
            "architecture": device.get("architecture", ""),
            "status": device.get("status", ""), "ip_address": device.get("ip_address", "")
        } if device else None,
    }


@router.get("/dashboard/interfaces")
async def dashboard_interfaces(device_id: str = "", user=Depends(get_current_user)):
    if not device_id:
        return ["all"]
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device or not device.get("last_poll_data"):
        return ["all"]
    interfaces = [i["name"] for i in device["last_poll_data"].get("interfaces", []) if i.get("name")]
    return ["all"] + interfaces


@router.get("/dashboard/wan-interface")
async def detect_wan_interface(device_id: str, user=Depends(get_current_user)):
    """
    Detect WAN interface by pinging 8.8.8.8 from each interface on MikroTik.
    Returns the interface name that can reach internet.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    if device.get("status") != "online":
        raise HTTPException(400, "Device is offline")

    # Get interface list from stored poll data
    iface_list = []
    if device.get("last_poll_data"):
        iface_list = [
            i["name"] for i in device["last_poll_data"].get("interfaces", [])
            if i.get("name") and i.get("type") in ("ether", "vlan", "bonding", "bridge", "", None)
               and not i["name"].startswith("lo")
        ]

    if not iface_list:
        return {"wan_interface": None, "tested": []}

    try:
        mt = get_api_client(device)
        tested = []
        wan_iface = None

        for iface in iface_list[:10]:  # limit to 10 interfaces to avoid timeout
            try:
                result = await asyncio.to_thread(
                    mt.post, "/tool/ping",
                    {"address": "8.8.8.8", "interface": iface, "count": "2", "interval": "0.5s"}
                )
                ping_results = result if isinstance(result, list) else []
                received = sum(1 for r in ping_results if r.get("received", "0") != "0")
                tested.append({"interface": iface, "reachable": received > 0})
                if received > 0 and not wan_iface:
                    wan_iface = iface
                    break  # found WAN interface, stop testing
            except Exception:
                tested.append({"interface": iface, "reachable": False})

        return {"wan_interface": wan_iface, "tested": tested}
    except Exception as e:
        logger.error(f"WAN detect failed for {device_id}: {e}")
        return {"wan_interface": None, "tested": [], "error": str(e)}


@router.get("/dashboard/traffic-history")
async def traffic_history_range(
    device_id: str = "",
    range: str = "24h",         # 1h, 12h, 24h, week, month
    date: str = "",             # specific date YYYY-MM-DD
    interface: str = "",
    user=Depends(get_current_user)
):
    """
    Return traffic history dengan time-bucketed downsampling.
    Menggunakan MongoDB aggregation agar data week/month bisa diambil
    secara representatif tanpa harus fetch semua dokumen.
    """
    db = get_db()
    now_utc = datetime.now(timezone.utc)

    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            # Treat as local WIB (UTC+7), convert to UTC for query
            start = d.replace(tzinfo=timezone.utc) - timedelta(hours=7)
            end   = start + timedelta(days=1)
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    elif range == "1h":
        start, end = now_utc - timedelta(hours=1),  now_utc
    elif range == "12h":
        start, end = now_utc - timedelta(hours=12), now_utc
    elif range == "week":
        start, end = now_utc - timedelta(days=7),   now_utc
    elif range == "month":
        start, end = now_utc - timedelta(days=30),  now_utc
    else:  # 24h default
        start, end = now_utc - timedelta(hours=24), now_utc

    # BUG 1 FIX: gunakan format yang sama dengan cara polling menyimpan (+00:00 isoformat)
    # polling.py: datetime.now(timezone.utc).isoformat() → "2024-03-11T12:00:00.123456+00:00"
    # Sebelumnya ".isoformat()" bisa berbeda microsecond precision, sekarang di-floor ke detik
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    end_str   = now_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")  # always use current time as end

    # BUG 2 FIX: interval bucket untuk downsampling
    # Polling setiap 30 detik → target ~100–200 titik per grafik
    interval_ms = {
        "1h":    60_000,        # 1-menit bucket  → ~60  titik
        "12h":   300_000,       # 5-menit bucket  → ~144 titik
        "24h":   600_000,       # 10-menit bucket → ~144 titik
        "week":  3_600_000,     # 1-jam bucket    → ~168 titik
        "month": 10_800_000,    # 3-jam bucket    → ~240 titik
    }.get(range, 600_000)

    base_match: dict = {"timestamp": {"$gte": start_str, "$lte": end_str}}
    if device_id:
        base_match["device_id"] = device_id

    try:
        # MongoDB Aggregation pipeline dengan $dateFromString time-bucketing
        # Bekerja di MongoDB 3.6+ (aman untuk semua instalasi modern)
        if interface and interface != "all":
            # Interface spesifik: akses nested bandwidth.<iface>
            pipeline = [
                {"$match": base_match},
                {"$addFields": {
                    "ts_ms": {"$toLong": {"$dateFromString": {"dateString": "$timestamp"}}},
                    "dl_bps": {"$ifNull": [f"$bandwidth.{interface}.download_bps", 0]},
                    "ul_bps": {"$ifNull": [f"$bandwidth.{interface}.upload_bps", 0]},
                }},
                {"$group": {
                    "_id": {"$subtract": ["$ts_ms", {"$mod": ["$ts_ms", interval_ms]}]},
                    "download_bps": {"$avg": "$dl_bps"},
                    "upload_bps":   {"$avg": "$ul_bps"},
                    "ping_ms":      {"$avg": {"$ifNull": ["$ping_ms",  0]}},
                    "jitter_ms":    {"$avg": {"$ifNull": ["$jitter_ms",0]}},
                }},
                {"$sort": {"_id": 1}},
            ]
        else:
            # Semua interface: jumlahkan semua bandwidth lalu rata-ratakan per bucket
            pipeline = [
                {"$match": base_match},
                {"$addFields": {
                    "ts_ms": {"$toLong": {"$dateFromString": {"dateString": "$timestamp"}}},
                    "total_dl": {"$reduce": {
                        "input": {"$objectToArray": {"$ifNull": ["$bandwidth", {}]}},
                        "initialValue": 0,
                        "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.download_bps", 0]}]},
                    }},
                    "total_ul": {"$reduce": {
                        "input": {"$objectToArray": {"$ifNull": ["$bandwidth", {}]}},
                        "initialValue": 0,
                        "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.upload_bps", 0]}]},
                    }},
                }},
                {"$group": {
                    "_id": {"$subtract": ["$ts_ms", {"$mod": ["$ts_ms", interval_ms]}]},
                    "download_bps": {"$avg": "$total_dl"},
                    "upload_bps":   {"$avg": "$total_ul"},
                    "ping_ms":      {"$avg": {"$ifNull": ["$ping_ms",  0]}},
                    "jitter_ms":    {"$avg": {"$ifNull": ["$jitter_ms",0]}},
                }},
                {"$sort": {"_id": 1}},
            ]

        buckets = await db.traffic_history.aggregate(pipeline).to_list(5000)

        result = []
        for b in buckets:
            ts_ms = b.get("_id")
            if not isinstance(ts_ms, (int, float)) or ts_ms <= 0:
                continue
            utc_dt   = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            local_dt = utc_dt + timedelta(hours=7)  # WIB
            label = (
                local_dt.strftime("%d/%m %H:00") if range in ("week", "month")
                else local_dt.strftime("%H:%M")
            )
            result.append({
                "time":     label,
                "download": round((b.get("download_bps") or 0) / 1_000_000, 2),
                "upload":   round((b.get("upload_bps")   or 0) / 1_000_000, 2),
                "ping":     round(b.get("ping_ms")   or 0, 1),
                "jitter":   round(b.get("jitter_ms") or 0, 1),
            })
        return result

    except Exception as agg_err:
        # Fallback untuk MongoDB < 3.6 atau jika $dateFromString tidak tersedia
        logger.warning(f"traffic-history aggregation failed (fallback): {agg_err}")

        # Simple fetch dengan limit tinggi, lalu Python-level subsampling
        fetch_limit = {"1h": 200, "12h": 2000, "24h": 4000, "week": 5000, "month": 5000}.get(range, 2000)
        target_pts  = {"1h": 60,  "12h": 144,  "24h": 144,  "week": 168,  "month": 240 }.get(range, 144)

        raw = await db.traffic_history.find(base_match, {"_id": 0}).sort("timestamp", 1).to_list(fetch_limit)
        # Subsample
        step = max(1, len(raw) // target_pts)
        sampled = raw[::step]

        result = []
        for h in sampled:
            try:
                t = datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00"))
                local = (t.replace(tzinfo=None) if t.tzinfo else t) + timedelta(hours=7)
                label = local.strftime("%d/%m %H:00") if range in ("week","month") else local.strftime("%H:%M")
            except Exception:
                label = ""

            bw = h.get("bandwidth") or {}
            if interface and interface != "all":
                ib = bw.get(interface, {})
                dl, ul = ib.get("download_bps", 0), ib.get("upload_bps", 0)
            else:
                dl = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
                ul = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))

            result.append({
                "time":     label,
                "download": round(dl / 1_000_000, 2),
                "upload":   round(ul / 1_000_000, 2),
                "ping":     h.get("ping_ms",   0),
                "jitter":   h.get("jitter_ms", 0),
            })
        return result



# -- Top Talkers (v3) ---------------------------------------------------------
@router.get("/dashboard/top-talkers")
async def top_talkers(
    limit: int = 10,
    range: str = "1h",
    user=Depends(get_current_user)
):
    """Top N devices/interfaces by total bandwidth - last range period."""
    db = get_db()
    now_utc = datetime.now(timezone.utc)
    range_map = {"1h": timedelta(hours=1), "12h": timedelta(hours=12), "24h": timedelta(hours=24)}
    delta = range_map.get(range, timedelta(hours=1))
    start = (now_utc - delta).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    records = await db.traffic_history.find(
        {"timestamp": {"$gte": start}},
        {"_id": 0, "device_id": 1, "bandwidth": 1}
    ).to_list(5000)

    devices = await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1}).to_list(100)
    dev_map = {d["id"]: d for d in devices}

    tally = {}
    for rec in records:
        did = rec.get("device_id", "")
        for iface, bw in (rec.get("bandwidth") or {}).items():
            if not isinstance(bw, dict):
                continue
            key = (did, iface)
            if key not in tally:
                tally[key] = {"dl": 0, "ul": 0, "count": 0}
            tally[key]["dl"] += bw.get("download_bps", 0)
            tally[key]["ul"] += bw.get("upload_bps", 0)
            tally[key]["count"] += 1

    result = []
    for (did, iface), vals in tally.items():
        cnt = max(vals["count"], 1)
        avg_dl = vals["dl"] / cnt
        avg_ul = vals["ul"] / cnt
        total_avg_mbps = round((avg_dl + avg_ul) / 1_000_000, 2)
        dev = dev_map.get(did, {})
        result.append({
            "device_id": did,
            "device_name": dev.get("name", did),
            "ip_address": dev.get("ip_address", ""),
            "interface": iface,
            "label": f"{dev.get('name', did)} / {iface}",
            "download_mbps": round(avg_dl / 1_000_000, 2),
            "upload_mbps": round(avg_ul / 1_000_000, 2),
            "total_mbps": total_avg_mbps,
        })

    result.sort(key=lambda x: x["total_mbps"], reverse=True)
    return result[:limit]


# -- Heatmap (v3) -------------------------------------------------------------
@router.get("/dashboard/heatmap")
async def bandwidth_heatmap(
    device_id: str = "",
    metric: str = "bandwidth",
    days: int = 7,
    user=Depends(get_current_user)
):
    """7x24 heatmap: average metric (bandwidth/cpu/memory) per day x hour."""
    db = get_db()
    now_utc = datetime.now(timezone.utc)
    start = (now_utc - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    match_filter = {"timestamp": {"$gte": start}}
    if device_id:
        match_filter["device_id"] = device_id

    records = await db.traffic_history.find(
        match_filter,
        {"_id": 0, "timestamp": 1, "bandwidth": 1, "cpu": 1, "memory_percent": 1}
    ).to_list(50000)

    matrix = {}
    for rec in records:
        try:
            utc_dt = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            local_dt = utc_dt + timedelta(hours=7)
            day_idx = local_dt.weekday()
            hour_idx = local_dt.hour
        except Exception:
            continue

        if metric == "bandwidth":
            bw = rec.get("bandwidth") or {}
            total_bps = sum(
                (v.get("download_bps", 0) + v.get("upload_bps", 0))
                for v in bw.values() if isinstance(v, dict)
            )
            value = total_bps / 1_000_000
        elif metric == "cpu":
            value = rec.get("cpu", 0)
        elif metric == "memory":
            value = rec.get("memory_percent", 0)
        else:
            value = 0

        key = (day_idx, hour_idx)
        matrix.setdefault(key, []).append(value)

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    result = []
    for day_idx in range(7):
        for hour in range(24):
            vals = matrix.get((day_idx, hour), [])
            avg = round(sum(vals) / len(vals), 2) if vals else 0
            result.append({"day": day_names[day_idx], "day_idx": day_idx, "hour": hour, "value": avg, "count": len(vals)})

    return {"metric": metric, "days": days, "data": result, "unit": "Mbps" if metric == "bandwidth" else "%"}
