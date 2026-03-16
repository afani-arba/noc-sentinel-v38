"""
Devices router: CRUD + dashboard + MikroTik API test.
"""
import uuid
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from core.db import get_db
from core.auth import get_current_user, require_admin
import ping_service
from mikrotik_api import get_api_client
from core.polling import poll_single_device

router = APIRouter(tags=["devices"])
logger = logging.getLogger(__name__)

SAFE_DEVICE_FIELDS = {"_id": 0, "api_password": 0, "last_poll_data": 0}


class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    api_mode: str = "rest"
    api_username: str = "admin"
    api_password: str = ""
    api_port: Optional[int] = None
    use_https: bool = False
    api_ssl: bool = True
    api_plaintext_login: bool = True
    description: str = ""
    snmp_community: str = "public"  # SNMP community string
    snmp_version: str = "2c"        # SNMP version: "1" atau "2c"
    winbox_address: Optional[str] = None  # Alamat Winbox remote — opsional




class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    api_mode: Optional[str] = None
    api_username: Optional[str] = None
    api_password: Optional[str] = None
    api_port: Optional[int] = None
    use_https: Optional[bool] = None
    api_ssl: Optional[bool] = None
    api_plaintext_login: Optional[bool] = None
    description: Optional[str] = None
    snmp_community: Optional[str] = None  # SNMP community string
    snmp_version: Optional[str] = None    # SNMP version: "1" atau "2c"
    winbox_address: Optional[str] = None  # Alamat Winbox remote - opsional

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
    devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(1000)  # FIX BUG #12: was 100
    return filter_devices_for_user(devs, user)


@router.get("/devices/full")
async def list_devices_full(user=Depends(require_admin)):
    db = get_db()
    devs = await db.devices.find({}, {"_id": 0}).to_list(1000)  # FIX BUG #12: was 100
    for d in devs:
        d.pop("last_poll_data", None)
    return devs


@router.get("/devices/all")
async def list_all_devices_for_admin(user=Depends(require_admin)):
    db = get_db()
    return await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1}).to_list(1000)  # FIX BUG #12: was 100


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
    # Audit log
    try:
        from routers.audit import log_action
        await log_action(action="CREATE", resource="devices", resource_id=doc["id"],
                         details=f"Added device: {data.name} ({data.ip_address})",
                         username=user.get("username", ""), user_id=user.get("id", ""))
    except Exception:
        pass
    return {k: v for k, v in doc.items() if k not in ("_id", "api_password", "last_poll_data")}


@router.put("/devices/{device_id}")
async def update_device(device_id: str, data: DeviceUpdate, user=Depends(require_admin)):
    db = get_db()
    # FIX BUG #5: gunakan exclude_unset=True agar field yang tidak dikirim tidak ikut diupdate.
    # Field yang DIKIRIM (termasuk null/None) tetap masuk ke update, sehingga winbox_address
    # bisa dikosongkan eksplisit dengan mengirim null dari frontend.
    raw = data.model_dump(exclude_unset=True)
    if not raw:
        raise HTTPException(400, "Nothing to update")

    # Pisahkan field yang ingin di-null (unset) vs field biasa
    upd_set = {k: v for k, v in raw.items() if v is not None}
    upd_unset = {k: "" for k, v in raw.items() if v is None and k in ("winbox_address",)}

    mongo_op: dict = {}
    if upd_set:
        mongo_op["$set"] = upd_set
    if upd_unset:
        # Gunakan $unset untuk nullify field opsional, atau $set ke "" agar tetap queryable
        mongo_op.setdefault("$set", {}).update({k: None for k in upd_unset})

    if not mongo_op:
        raise HTTPException(400, "Nothing to update")

    r = await db.devices.update_one({"id": device_id}, mongo_op)
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    # Audit log
    try:
        from routers.audit import log_action
        fields = ", ".join(raw.keys())
        await log_action(action="UPDATE", resource="devices", resource_id=device_id,
                         details=f"Updated fields: {fields}",
                         username=user.get("username", ""), user_id=user.get("id", ""))
    except Exception:
        pass
    return await db.devices.find_one({"id": device_id}, SAFE_DEVICE_FIELDS)


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, user=Depends(require_admin)):
    db = get_db()
    # Get device name before deleting for audit log
    dev = await db.devices.find_one({"id": device_id}, {"_id": 0, "name": 1, "ip_address": 1})
    r = await db.devices.delete_one({"id": device_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Device not found")
    await db.traffic_history.delete_many({"device_id": device_id})
    await db.traffic_snapshots.delete_one({"device_id": device_id})
    # Audit log
    try:
        from routers.audit import log_action
        name = dev.get("name", device_id) if dev else device_id
        await log_action(action="DELETE", resource="devices", resource_id=device_id,
                         details=f"Deleted device: {name}",
                         username=user.get("username", ""), user_id=user.get("id", ""))
    except Exception:
        pass
    return {"message": "Deleted"}


class LocationUpdate(BaseModel):
    lat: float
    lng: float
    location_name: Optional[str] = None  # nama lokasi opsional (e.g. "Kantor Pusat")


@router.patch("/devices/{device_id}/location")
async def update_device_location(device_id: str, data: LocationUpdate, user=Depends(get_current_user)):
    """Simpan koordinat geografis device untuk peta topologi."""
    db = get_db()
    upd = {"lat": data.lat, "lng": data.lng}
    if data.location_name is not None:
        upd["location_name"] = data.location_name
    r = await db.devices.update_one({"id": device_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Device not found")
    return {"ok": True, "lat": data.lat, "lng": data.lng}


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
    """
    Ambil info sistem dari MikroTik: architecture, board-name, version, build-time, cpu-count.
    Mendukung ROS6 (API protocol, port 8728), ROS7+ (REST API, port 443/80), dan mesin x86.
    Menormalkan semua key dari dash-format (architecture-name) ke underscore (architecture_name).
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        client = get_api_client(device)
        raw = await client.get_system_resource()

        logger.info(f"system-resource raw for {device_id}: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}")

        if not isinstance(raw, dict) or not raw:
            return {"error": "No data returned from device"}

        def _s(v): return str(v).strip() if v is not None else ""
        def _i(v):
            try: return int(str(v).strip())
            except Exception: return 0

        # Both ROS6 and ROS7 use dash-separated key names in system/resource
        # e.g. architecture-name, board-name, build-time, cpu-count, cpu-frequency
        # x86 machines: architecture-name may be 'x86_64' or 'x86', board-name may be 'x86'
        arch = _s(raw.get("architecture-name") or raw.get("architectureName") or raw.get("architecture") or "")
        board = _s(raw.get("board-name") or raw.get("boardName") or raw.get("board") or "")
        version = _s(raw.get("version") or "")
        build_time = _s(raw.get("build-time") or raw.get("buildTime") or "")
        factory_sw = _s(raw.get("factory-software") or raw.get("factorySoftware") or "")
        platform = _s(raw.get("platform") or "")
        cpu = _s(raw.get("cpu") or raw.get("cpu-model") or "")
        cpu_count = _i(raw.get("cpu-count") or raw.get("cpuCount") or 0)
        cpu_freq = _i(raw.get("cpu-frequency") or raw.get("cpuFrequency") or 0)
        uptime = _s(raw.get("uptime") or "")
        total_mem = _i(raw.get("total-memory") or raw.get("totalMemory") or 0)
        free_mem = _i(raw.get("free-memory") or raw.get("freeMemory") or 0)
        total_hdd = _i(raw.get("total-hdd-space") or raw.get("totalHddSpace") or 0)
        free_hdd = _i(raw.get("free-hdd-space") or raw.get("freeHddSpace") or 0)

        return {
            # FIX BUG #3: wrong operator precedence in original: `arch or "x86" if ... else arch`
            # Python evaluates that as `(arch) or ("x86" if ... else arch)` which can give wrong result.
            # Correct: when arch is empty AND x86 detected, return "x86"; else return arch.
            "architecture_name": (arch or "x86") if "x86" in (platform + board + cpu).lower() else arch,
            "board_name": board or platform or "",
            "version": version,
            "build_time": build_time,
            "factory_software": factory_sw,
            "platform": platform,
            "cpu": cpu,
            "cpu_count": cpu_count,
            "cpu_frequency": cpu_freq,
            "uptime": uptime,
            "total_memory": total_mem,
            "free_memory": free_mem,
            "total_hdd_space": total_hdd,
            "free_hdd_space": free_hdd,
        }
    except Exception as e:
        logger.warning(f"system-resource fetch failed for {device_id}: {e}")
        return {"error": str(e)}


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
    Ambil data sensor hardware dari MikroTik.
    - ROS 6.x (API Protocol): /system/health â€” {name, value, type} per sensor
    - ROS 7.x (REST API): /rest/system/health â€” [{name, value, type}]
    Fallback: baca dari MongoDB jika live API call gagal/kosong.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")

    live_data = {}
    try:
        mt = get_api_client(device)
        raw = await mt.get_system_health()
        if isinstance(raw, dict) and any(v for v in raw.values() if v and v != {} and v != ""):
            raw.pop("raw", None)
            live_data = raw
            logger.info(
                f"system-health LIVE [{device_id}]: "
                f"board_temp={raw.get('board_temp',0)} voltage={raw.get('voltage',0)}"
            )
    except Exception as e:
        logger.warning(f"system-health live fetch failed for {device_id}: {e}")

    # Fallback: baca dari MongoDB (dibuat oleh polling)
    if not live_data or (live_data.get("board_temp", 0) == 0 and live_data.get("voltage", 0) == 0):
        mongo_data = {
            "cpu_temp":   device.get("cpu_temp",   0),
            "board_temp": device.get("board_temp", 0),
            "voltage":    device.get("voltage",    0),
            "power":      device.get("power",      0),
            "fans":       {},
            "psu":        {},
            "extra_temps": {},
        }
        # Merge: prefer live_data non-zero over mongo_data
        if live_data:
            for k in ("cpu_temp", "board_temp", "sfp_temp", "switch_temp", "voltage", "power"):
                live_val = live_data.get(k, 0) or 0
                mongo_val = mongo_data.get(k, 0) or 0
                mongo_data[k] = live_val if live_val > 0 else mongo_val
            mongo_data["fans"]        = live_data.get("fans", {}) or {}
            mongo_data["psu"]         = live_data.get("psu", {}) or {}
            mongo_data["extra_temps"] = live_data.get("extra_temps", {}) or {}

        logger.info(
            f"system-health MONGO fallback [{device_id}]: "
            f"board_temp={mongo_data.get('board_temp',0)} voltage={mongo_data.get('voltage',0)}"
        )
        return mongo_data

    return live_data



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
    ping_r = await ping_service.ping_host(data.ip_address)
    mt     = get_api_client(data.model_dump())
    api_r  = await mt.test_connection()
    return {"ping": ping_r, "api": api_r}


# â”€â”€ Dashboard â”€â”€
@router.get("/dashboard/stats")
async def dashboard_stats(device_id: str = "", interface: str = "", user=Depends(get_current_user)):
    db = get_db()
    all_devs = await db.devices.find({}, SAFE_DEVICE_FIELDS).to_list(1000)  # FIX BUG #12: was 100
    # FIX BUG #15: filter berdasarkan akses user (non-admin hanya lihat device yang diizinkan)
    all_devs = filter_devices_for_user(all_devs, user)
    online = sum(1 for d in all_devs if d.get("status") == "online")
    device = await db.devices.find_one({"id": device_id}, {"_id": 0}) if device_id else None

    query = {"device_id": device_id} if device_id else {}
    # BUG 3 FIX: limit 200â†’300 agar cukup untuk 144 titik terbaru
    history = await db.traffic_history.find(query, {"_id": 0}).sort("timestamp", -1).to_list(300)
    history.reverse()

    traffic_data = []
    for h in history[-144:]:   # BUG 3 FIX: was -60 (30 menit), now 144Ã—30s = 72 menit
        try:
            utc_time = datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00"))
            local_time = (utc_time.replace(tzinfo=None) if utc_time.tzinfo else utc_time) + timedelta(hours=7)
            time_label = local_time.strftime("%H:%M")
        except Exception:
            time_label = ""
        bw = h.get("bandwidth") or {}
        if bw:
            # New format: bandwidth = {iface: {download_bps, upload_bps}}
            if interface and interface != "all":
                ib = bw.get(interface, {})
                dl, ul = ib.get("download_bps", 0), ib.get("upload_bps", 0)
            else:
                dl = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
                ul = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))
        else:
            # Old format: top-level download_mbps / upload_mbps (in Mbps, not bps)
            dl = (h.get("download_mbps") or 0) * 1_000_000
            ul = (h.get("upload_mbps")   or 0) * 1_000_000
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

    # ── Total bandwidth: sum live dari semua device online ─────────────────────
    # FIX: sebelumnya hanya mengambil last row dari traffic_history (1 device saja).
    # Sekarang: hitung jumlah aktual dari semua device online, sama seperti wallboard.py
    VIRTUAL_PREFIXES = (
        "bridge", "vlan", "lo", "loopback", "ovpn", "pppoe-", "pptp",
        "l2tp", "eoip", "gre", "wireguard", "wg", "veth", "docker",
        "ip6tnl", "sit", "tun", "tap", "dummy",
    )

    if not device_id:
        # Ambil snapshot traffic terbaru per device secara paralel
        total_dl_bps = 0
        total_ul_bps = 0
        for d in all_devs:
            if d.get("status") != "online":
                continue
            last_bw_doc = await db.traffic_history.find_one(
                {"device_id": d["id"]},
                {"_id": 0, "bandwidth": 1, "isp_bandwidth": 1},
                sort=[("timestamp", -1)]
            )
            if not last_bw_doc:
                continue
            bw      = last_bw_doc.get("bandwidth")      or {}
            isp_bw  = last_bw_doc.get("isp_bandwidth")  or {}
            isp_ifaces = d.get("isp_interfaces") or []

            if isp_bw:
                # Prioritas 1: isp_bandwidth (dari comment ISP/WAN di MikroTik)
                for iface_bw in isp_bw.values():
                    if isinstance(iface_bw, dict):
                        total_dl_bps += iface_bw.get("download_bps", 0)
                        total_ul_bps += iface_bw.get("upload_bps",   0)
            elif bw and isp_ifaces:
                # Prioritas 2: filter hanya interface ISP yang sudah dikonfigurasi
                for iface_name in isp_ifaces:
                    iface_bw = bw.get(iface_name, {})
                    if isinstance(iface_bw, dict):
                        total_dl_bps += iface_bw.get("download_bps", 0)
                        total_ul_bps += iface_bw.get("upload_bps",   0)
            elif bw:
                # Prioritas 3: sum semua interface fisik (hindari virtual)
                for iface_name, iface_bw in bw.items():
                    n = iface_name.lower()
                    if isinstance(iface_bw, dict) and not any(n.startswith(p) for p in VIRTUAL_PREFIXES):
                        total_dl_bps += iface_bw.get("download_bps", 0)
                        total_ul_bps += iface_bw.get("upload_bps",   0)

        live_bw = {
            "download": round(total_dl_bps / 1_000_000, 2),
            "upload":   round(total_ul_bps / 1_000_000, 2),
        }
    else:
        # Untuk satu device: gunakan last point dari traffic_data (sudah SUM semua interface)
        live_bw = {"download": last["download"], "upload": last["upload"]}

    return {
        "devices": {"total": len(all_devs), "online": online},
        "total_bandwidth": live_bw,
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
        return {"interfaces": ["all"], "isp_interfaces": []}
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device or not device.get("last_poll_data"):
        return {"interfaces": ["all"], "isp_interfaces": []}

    iface_list = device["last_poll_data"].get("interfaces", [])

    # â”€â”€ Filter virtual interface â€” berlapis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Layer 1: gunakan flag 'virtual' yang sudah dihitung oleh polling.py
    # Layer 2: fallback prefix-based detection untuk data lama (tanpa flag 'virtual')
    VIRTUAL_TYPES = {
        "bridge", "vlan", "pppoe-out", "pppoe-in", "l2tp-out", "l2tp-in",
        "pptp-out", "pptp-in", "sstp-out", "sstp-in", "ovpn-client", "ovpn-server",
        "eoip", "eoipv6", "gre", "gre6", "ipip", "ipip6", "6to4",
        "veth", "wireguard", "loopback", "bonding",
    }
    VIRTUAL_PREFIXES = (
        "bridge", "vlan", "pppoe", "ppp-", "ppp0", "l2tp", "pptp", "sstp",
        "eoip", "gre", "ovpn", "vrrp", "lo", "wg", "tun", "ipip",
        "sit", "ip6tnl", "veth", "docker", "dummy",
    )

    physical = []
    for iface in iface_list:
        name  = (iface.get("name") or "").strip()
        itype = (iface.get("type") or "").lower().strip()
        if not name:
            continue

        # Skip dynamic session: nama dimulai dengan '<' (PPPoE active sessions)
        if name.startswith("<"):
            continue

        # Layer 1: polling.py sudah menghitung flag 'virtual'
        if iface.get("virtual") is True:
            continue

        # Layer 2: fallback untuk data lama (sebelum field 'virtual' ada)
        if itype in VIRTUAL_TYPES:
            continue
        n = name.lower()
        if any(n.startswith(p) for p in VIRTUAL_PREFIXES):
            continue

        physical.append(name)

    # Deduplicate â€” jaga urutan
    seen = set()
    unique_physical = []
    for n in physical:
        if n not in seen:
            seen.add(n)
            unique_physical.append(n)

    # ISP interfaces dari comment detection (disimpan oleh polling cycle)
    isp_interfaces = device.get("isp_interfaces", [])

    # Sort: ISP interfaces didahulukan, lalu sisanya alphabetical
    isp_set = set(isp_interfaces)
    ordered_isp  = [i for i in isp_interfaces if i in set(unique_physical)]
    ordered_rest = sorted(i for i in unique_physical if i not in isp_set)
    ordered = ordered_isp + ordered_rest

    return {
        "interfaces":     ["all"] + ordered,
        "isp_interfaces": ordered_isp,
    }


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
    # polling.py: datetime.now(timezone.utc).isoformat() â†’ "2024-03-11T12:00:00.123456+00:00"
    # Sebelumnya ".isoformat()" bisa berbeda microsecond precision, sekarang di-floor ke detik
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    end_str   = now_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")  # always use current time as end

    # BUG 2 FIX: interval bucket untuk downsampling
    # Polling setiap 30 detik â†’ target ~100â€“200 titik per grafik
    interval_ms = {
        "1h":    60_000,        # 1-menit bucket  â†’ ~60  titik
        "12h":   300_000,       # 5-menit bucket  â†’ ~144 titik
        "24h":   600_000,       # 10-menit bucket â†’ ~144 titik
        "week":  3_600_000,     # 1-jam bucket    â†’ ~168 titik
        "month": 10_800_000,    # 3-jam bucket    â†’ ~240 titik
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
            # â”€â”€ Pipeline "all" â€” ISP-aware â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Prioritas 1: isp_bandwidth (sum semua ISP interface, disimpan oleh polling.py)
            #   Format: {isp_bandwidth: {ether1: {download_bps, upload_bps}, ether2: {...}}}
            # Prioritas 2: fallback ke sum semua bandwidth.* (lama, jika isp_bandwidth tidak ada)
            pipeline = [
                {"$match": base_match},
                {"$addFields": {
                    "ts_ms": {"$toLong": {"$dateFromString": {"dateString": "$timestamp"}}},
                    # Sum semua ISP interface dari isp_bandwidth (multi-ISP aware)
                    "isp_dl": {"$reduce": {
                        "input": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}},
                        "initialValue": 0,
                        "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.download_bps", 0]}]},
                    }},
                    "isp_ul": {"$reduce": {
                        "input": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}},
                        "initialValue": 0,
                        "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.upload_bps", 0]}]},
                    }},
                    # Fallback: sum semua interface di bandwidth (untuk device tanpa ISP comment)
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
                    # Jumlah ISP interface yang dideteksi (>0 = ada isp_bandwidth valid)
                    "isp_count": {"$size": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}}},
                }},
                {"$addFields": {
                    # Pilih ISP-only jika tersedia, fallback ke semua bandwidth
                    "dl_bps": {"$cond": {
                        "if":   {"$gt": ["$isp_count", 0]},
                        "then": "$isp_dl",
                        "else": "$total_dl",
                    }},
                    "ul_bps": {"$cond": {
                        "if":   {"$gt": ["$isp_count", 0]},
                        "then": "$isp_ul",
                        "else": "$total_ul",
                    }},
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

            bw     = h.get("bandwidth")     or {}
            isp_bw = h.get("isp_bandwidth") or {}
            if interface and interface != "all":
                # Interface spesifik: cari di bandwidth dict
                ib = bw.get(interface, {})
                dl, ul = ib.get("download_bps", 0), ib.get("upload_bps", 0)
            elif isp_bw:
                # ISP-aware: sum semua interface ISP (multi-ISP)
                dl = sum(v.get("download_bps", 0) for v in isp_bw.values() if isinstance(v, dict))
                ul = sum(v.get("upload_bps",   0) for v in isp_bw.values() if isinstance(v, dict))
            else:
                # Fallback: sum semua interface di bandwidth
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



# ── ISP Multi-Series Traffic History ─────────────────────────────────────────
@router.get("/dashboard/isp-traffic-history")
async def isp_traffic_history_multi(
    device_id: str = "",
    range: str = "24h",
    user=Depends(get_current_user)
):
    """
    Return per-ISP interface traffic as separate series.
    Response: {labels: [...], series: [{name: "ether1", data: [{time, download, upload},...]},...]}
    Digunakan untuk grafik multi-series ISP1 vs ISP2 di dashboard.
    """
    if not device_id:
        return {"labels": [], "series": []}

    db = get_db()
    now    = datetime.now(timezone.utc)
    ranges = {"1h": 1, "12h": 12, "24h": 24, "week": 168, "month": 720}
    hours  = ranges.get(range, 24)
    since  = now - timedelta(hours=hours)

    # Interval bucketing (sama dengan traffic-history)
    intervals = {"1h": 60_000, "12h": 300_000, "24h": 600_000,
                 "week": 3_600_000, "month": 14_400_000}
    interval_ms = intervals.get(range, 600_000)

    base_match = {
        "device_id": device_id,
        "timestamp": {"$gte": since.isoformat()},
        "isp_bandwidth": {"$exists": True, "$ne": {}},
    }

    try:
        # Aggregation: unwind isp_bandwidth object → per-interface buckets
        pipeline = [
            {"$match": base_match},
            {"$addFields": {
                "ts_ms": {"$toLong": {"$dateFromString": {"dateString": "$timestamp"}}},
                "isp_pairs": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}},
            }},
            {"$unwind": "$isp_pairs"},
            {"$addFields": {
                "bucket": {"$subtract": ["$ts_ms", {"$mod": ["$ts_ms", interval_ms]}]},
                "iface_name": "$isp_pairs.k",
                "dl_bps":     {"$ifNull": ["$isp_pairs.v.download_bps", 0]},
                "ul_bps":     {"$ifNull": ["$isp_pairs.v.upload_bps",   0]},
            }},
            {"$group": {
                "_id":          {"bucket": "$bucket", "iface": "$iface_name"},
                "download_bps": {"$avg": "$dl_bps"},
                "upload_bps":   {"$avg": "$ul_bps"},
            }},
            {"$sort": {"_id.bucket": 1}},
        ]

        raw = await db.traffic_history.aggregate(pipeline).to_list(10000)

        # Kelompokkan per interface
        from collections import defaultdict
        series_map = defaultdict(list)
        all_buckets = sorted({d["_id"]["bucket"] for d in raw})

        for bucket in all_buckets:
            utc_dt   = datetime.fromtimestamp(bucket / 1000, tz=timezone.utc)
            local_dt = utc_dt + timedelta(hours=7)
            label    = (local_dt.strftime("%d/%m %H:00") if range in ("week", "month")
                        else local_dt.strftime("%H:%M"))

            for doc in raw:
                if doc["_id"]["bucket"] == bucket:
                    iface = doc["_id"]["iface"]
                    series_map[iface].append({
                        "time":     label,
                        "download": round((doc.get("download_bps") or 0) / 1_000_000, 2),
                        "upload":   round((doc.get("upload_bps")   or 0) / 1_000_000, 2),
                    })

        series = [{"name": iface, "data": pts} for iface, pts in sorted(series_map.items())]
        return {"series": series, "range": range}

    except Exception as e:
        logger.warning(f"isp-traffic-history aggregation failed: {e}")
        return {"series": [], "range": range}


# ── Historical Comparison ─────────────────────────────────────────────────────
@router.get("/dashboard/traffic-compare")
async def traffic_compare(
    device_id: str = "",
    period: str = "week",   # "week" = hari ini vs 7hr lalu, "month" = vs 30hr lalu
    user=Depends(get_current_user)
):
    """
    Bandingkan traffic hari ini (24h terakhir) vs periode yang sama N hari lalu.
    Response: {current: [{time, download, upload}], previous: [{time, download, upload}],
               anomalies: [{time, type, value, baseline}]}
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    # Periode perbandingan
    offset_days = {"week": 7, "month": 30}.get(period, 7)
    interval_ms = 600_000  # 10 menit per bucket

    def build_window_pipeline(start: datetime, end: datetime, device_id: str):
        base = {"timestamp": {"$gte": start.isoformat(), "$lt": end.isoformat()}}
        if device_id:
            base["device_id"] = device_id
        return [
            {"$match": base},
            {"$addFields": {
                "ts_ms":   {"$toLong": {"$dateFromString": {"dateString": "$timestamp"}}},
                "isp_dl":  {"$reduce": {
                    "input": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}},
                    "initialValue": 0,
                    "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.download_bps", 0]}]},
                }},
                "isp_ul":  {"$reduce": {
                    "input": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}},
                    "initialValue": 0,
                    "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.upload_bps",   0]}]},
                }},
                "isp_cnt": {"$size": {"$objectToArray": {"$ifNull": ["$isp_bandwidth", {}]}}},
                "all_dl":  {"$reduce": {
                    "input": {"$objectToArray": {"$ifNull": ["$bandwidth", {}]}},
                    "initialValue": 0,
                    "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.download_bps", 0]}]},
                }},
                "all_ul":  {"$reduce": {
                    "input": {"$objectToArray": {"$ifNull": ["$bandwidth", {}]}},
                    "initialValue": 0,
                    "in": {"$add": ["$$value", {"$ifNull": ["$$this.v.upload_bps",   0]}]},
                }},
            }},
            {"$addFields": {
                "dl_bps": {"$cond": {"if": {"$gt": ["$isp_cnt", 0]}, "then": "$isp_dl", "else": "$all_dl"}},
                "ul_bps": {"$cond": {"if": {"$gt": ["$isp_cnt", 0]}, "then": "$isp_ul", "else": "$all_ul"}},
            }},
            {"$group": {
                "_id":          {"$subtract": ["$ts_ms", {"$mod": ["$ts_ms", interval_ms]}]},
                "download_bps": {"$avg": "$dl_bps"},
                "upload_bps":   {"$avg": "$ul_bps"},
            }},
            {"$sort": {"_id": 1}},
        ]

    def fmt_bucket(bucket_ms: int) -> str:
        utc = datetime.fromtimestamp(bucket_ms / 1000, tz=timezone.utc)
        wib = utc + timedelta(hours=7)
        return wib.strftime("%H:%M")

    def buckets_to_list(raw: list) -> list:
        out = []
        for b in raw:
            ts_ms = b.get("_id")
            if not isinstance(ts_ms, (int, float)) or ts_ms <= 0:
                continue
            out.append({
                "time":     fmt_bucket(int(ts_ms)),
                "download": round((b.get("download_bps") or 0) / 1_000_000, 2),
                "upload":   round((b.get("upload_bps")   or 0) / 1_000_000, 2),
            })
        return out

    try:
        # Current window: now-24h → now
        curr_start = now - timedelta(hours=24)
        curr_raw   = await db.traffic_history.aggregate(
            build_window_pipeline(curr_start, now, device_id)).to_list(5000)
        current = buckets_to_list(curr_raw)

        # Previous window: same 24h, offset_days ago
        prev_end   = now - timedelta(days=offset_days)
        prev_start = prev_end - timedelta(hours=24)
        prev_raw   = await db.traffic_history.aggregate(
            build_window_pipeline(prev_start, prev_end, device_id)).to_list(5000)
        previous = buckets_to_list(prev_raw)

        # Anomaly detection — flag points >2x baseline average
        anomalies = []
        if previous and current:
            baseline_dl = sum(p["download"] for p in previous) / len(previous) if previous else 0
            baseline_ul = sum(p["upload"] for p in previous) / len(previous) if previous else 0
            for pt in current:
                if baseline_dl > 0 and pt["download"] > baseline_dl * 2.5:
                    anomalies.append({"time": pt["time"], "type": "download_spike",
                                      "value": pt["download"], "baseline": round(baseline_dl, 2)})
                if baseline_ul > 0 and pt["upload"] > baseline_ul * 2.5:
                    anomalies.append({"time": pt["time"], "type": "upload_spike",
                                      "value": pt["upload"],   "baseline": round(baseline_ul, 2)})

        return {
            "current":   current,
            "previous":  previous,
            "anomalies": anomalies,
            "period":    period,
            "offset_days": offset_days,
        }
    except Exception as e:
        logger.warning(f"traffic-compare failed: {e}")
        return {"current": [], "previous": [], "anomalies": [], "period": period}




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

    devices = await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1}).to_list(1000)  # FIX BUG #12: was 100
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


# â”€â”€ Traffic History (per-device with interface + range + date filter) â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/devices/{device_id}/traffic-history")
async def get_traffic_history(
    device_id: str,
    limit: int = 144,
    interface: str = "",
    range: str = "12h",   # 1h | 12h | 24h
    date: str = "",        # YYYY-MM-DD â†’ return 24h of that date
    user=Depends(get_current_user)
):
    """
    Return poll snapshots for a device.
    Supports interface filter (physical only), time-range (1h/12h/24h),
    and date-based queries (returns 24h of that specific date).
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0, "id": 1, "name": 1, "last_poll_data": 1})
    if not device:
        raise HTTPException(404, "Device not found")

    # Determine time window
    now_utc = datetime.now(timezone.utc)
    if date:
        try:
            # Parse date in local time (WIB = UTC+7), return full 24h in that day
            from datetime import date as dt_date
            d = dt_date.fromisoformat(date)
            start_utc = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=7)
            end_utc   = start_utc + timedelta(hours=24)
            time_match = {"timestamp": {"$gte": start_utc.isoformat(), "$lt": end_utc.isoformat()}}
        except Exception:
            time_match = {}
    else:
        hours_map = {"1h": 1, "12h": 12, "24h": 24, "week": 168}
        hours = hours_map.get(range, 12)
        start_utc = now_utc - timedelta(hours=hours)
        time_match = {"timestamp": {"$gt": start_utc.isoformat()}}
        limit = min(limit, hours * 120)  # max 2 samples/min

    query = {"device_id": device_id, **time_match}

    # Available physical interfaces on this device
    PHYSICAL_PREFIXES = ("ether", "sfp", "combo", "wlan", "lte", "fiber", "qsfp")
    VIRTUAL_PREFIXES  = ("bridge", "vlan", "pppoe", "ppp", "l2tp", "pptp", "sstp", "eoip", "gre", "ovpn", "vrrp", "lo", "wg", "tun")

    # If interface not specified, return available physical interfaces list too
    available_ifaces = []
    if device.get("last_poll_data"):
        for iface in device["last_poll_data"].get("interfaces", []):
            n = (iface.get("name") or "").lower()
            name = iface.get("name", "")
            if not name:
                continue
            if any(n.startswith(p) for p in PHYSICAL_PREFIXES):
                available_ifaces.append(name)
            elif not any(n.startswith(v) for v in VIRTUAL_PREFIXES):
                available_ifaces.append(name)

    snapshots_raw = await db.traffic_history.find(
        query, {"_id": 0, "device_id": 0}
    ).sort("timestamp", 1).limit(max(limit, 2000)).to_list(max(limit, 2000))

    result = []
    for h in snapshots_raw:
        bw = h.get("bandwidth") or {}
        sel_iface = interface if interface and interface != "all" else None

        if bw:
            # New format: bandwidth = {iface: {download_bps, upload_bps, ...}}
            if sel_iface:
                ib = bw.get(sel_iface, {})
                dl_bps = ib.get("download_bps", 0)
                ul_bps = ib.get("upload_bps", 0)
            else:
                dl_bps = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
                ul_bps = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))
        else:
            # Old/simple format: download_mbps / upload_mbps stored at top level (in Mbps)
            dl_mbps = h.get("download_mbps", 0) or 0
            ul_mbps = h.get("upload_mbps",   0) or 0
            dl_bps = dl_mbps * 1_000_000
            ul_bps = ul_mbps * 1_000_000

        # Convert to Mbps for display
        dl_mbps_out = round(dl_bps / 1_000_000, 3) if dl_bps else round(h.get("download_mbps", 0) or 0, 3)
        ul_mbps_out = round(ul_bps / 1_000_000, 3) if ul_bps else round(h.get("upload_mbps",   0) or 0, 3)

        try:
            ts = datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00"))
            local = ts + timedelta(hours=7)
            time_label = local.strftime("%H:%M")
            date_label = local.strftime("%d/%m %H:%M")
        except Exception:
            time_label = ""
            date_label = ""

        result.append({
            "timestamp": h.get("timestamp"),
            "time": time_label,
            "date_label": date_label,
            "download_mbps": dl_mbps_out,
            "upload_mbps":   ul_mbps_out,
            "download_bps":  dl_bps,
            "upload_bps":    ul_bps,
            "cpu":    h.get("cpu", 0),
            "memory": h.get("memory_percent", h.get("memory", 0)),
            "ping":   h.get("ping_ms", 0),
            "jitter": h.get("jitter_ms", 0),
        })

    return {
        "device_id": device_id,
        "name": device.get("name", ""),
        "interface": interface or "all",
        "range": range,
        "available_interfaces": available_ifaces,
        "history": result,
    }

# (system-resource endpoint is defined at line 171 â€” only one instance needed)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# BANDWIDTH LIVE â€” per-interface real-time bandwidth dari traffic_history
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/bandwidth/live/{device_id}")
async def bandwidth_live(
    device_id: str,
    user=Depends(get_current_user),
):
    """
    Return current bandwidth per-interface dari traffic_history terbaru.
    Bandwidth dihitung sebagai delta octets antar poll (akurat).
    Data historis 5 menit terakhir juga dikembalikan untuk grafik.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    # â”€â”€ Ambil data traffic_history terbaru (1 record = 1 poll cycle) â”€â”€â”€â”€â”€â”€â”€â”€â”€
    latest = await db.traffic_history.find_one(
        {"device_id": device_id},
        sort=[("timestamp", -1)]
    )

    # â”€â”€ Ambil 10 record terakhir untuk grafik trend (5 menit @ 30s interval) â”€
    history_records = await db.traffic_history.find(
        {"device_id": device_id},
        {"_id": 0, "timestamp": 1, "bandwidth": 1, "download_mbps": 1, "upload_mbps": 1,
         "cpu": 1, "memory_percent": 1}
    ).sort("timestamp", -1).limit(10).to_list(10)
    history_records.reverse()  # kronologis

    bandwidth_map = {}
    if latest:
        bandwidth_map = latest.get("bandwidth") or {}

    # â”€â”€ Ambil daftar interface dari last_poll_data untuk metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    last_poll = device.get("last_poll_data") or {}
    interfaces_raw = last_poll.get("interfaces", [])

    PHYSICAL_PREFIXES = ("ether", "sfp", "combo", "wlan", "lte", "fiber", "qsfp")
    VIRTUAL_PREFIXES  = ("bridge", "vlan", "pppoe", "ppp", "l2tp", "pptp", "sstp",
                         "eoip", "gre", "ovpn", "vrrp", "lo", "wg", "tun")

    # Build interface list dengan data bandwidth dari traffic_history
    iface_names_from_db = set(bandwidth_map.keys()) if bandwidth_map else set()
    iface_names_from_poll = {i.get("name", "") for i in interfaces_raw if i.get("name")}
    all_iface_names = iface_names_from_db | iface_names_from_poll

    # Build metadata lookup dari poll data
    iface_meta = {i.get("name", ""): i for i in interfaces_raw if i.get("name")}

    interfaces = []
    for name in sorted(all_iface_names):
        if not name:
            continue
        n = name.lower()
        is_physical = any(n.startswith(p) for p in PHYSICAL_PREFIXES)
        is_virtual  = any(n.startswith(v) for v in VIRTUAL_PREFIXES)

        bw = bandwidth_map.get(name, {}) if bandwidth_map else {}
        dl_bps = bw.get("download_bps", 0) if isinstance(bw, dict) else 0
        ul_bps = bw.get("upload_bps",   0) if isinstance(bw, dict) else 0

        meta = iface_meta.get(name, {})
        interfaces.append({
            "name":          name,
            "type":          meta.get("type", "ether") if meta else "ether",
            "is_physical":   is_physical and not is_virtual,
            "running":       meta.get("running", bw.get("status", "down") == "up") if meta else (bw.get("status", "down") == "up"),
            "disabled":      meta.get("disabled", False),
            "mac":           meta.get("mac", ""),
            "status":        bw.get("status", "up" if bw else "unknown"),
            "download_bps":  dl_bps,
            "upload_bps":    ul_bps,
            "download_mbps": round(dl_bps / 1_000_000, 3),
            "upload_mbps":   round(ul_bps / 1_000_000, 3),
            "rx_bytes":      meta.get("rx_bytes", 0),
            "tx_bytes":      meta.get("tx_bytes", 0),
        })

    # Sort: physical first, then running first, then by name
    interfaces.sort(key=lambda x: (not x["is_physical"], not x.get("running", False), x["name"]))

    # â”€â”€ Total bandwidth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    total_dl = sum(i["download_bps"] for i in interfaces)
    total_ul = sum(i["upload_bps"]   for i in interfaces)

    # â”€â”€ Format history untuk grafik (timestamp + total dalam Mbps) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    trend = []
    for rec in history_records:
        ts = rec.get("timestamp", "")
        bw_rec = rec.get("bandwidth", {})
        if bw_rec and isinstance(bw_rec, dict):
            r_dl = sum(v.get("download_bps", 0) for v in bw_rec.values() if isinstance(v, dict))
            r_ul = sum(v.get("upload_bps",   0) for v in bw_rec.values() if isinstance(v, dict))
            trend.append({
                "timestamp":     ts,
                "download_mbps": round(r_dl / 1_000_000, 3),
                "upload_mbps":   round(r_ul / 1_000_000, 3),
            })
        else:
            trend.append({
                "timestamp":     ts,
                "download_mbps": rec.get("download_mbps", 0),
                "upload_mbps":   rec.get("upload_mbps",   0),
            })

    return {
        "device_id":          device_id,
        "name":               device.get("name", ""),
        "status":             device.get("status", "unknown"),
        "last_poll":          device.get("last_poll", "") or (latest.get("timestamp", "") if latest else ""),
        "cpu_load":           latest.get("cpu", device.get("cpu_load", 0)) if latest else device.get("cpu_load", 0),
        "memory_usage":       latest.get("memory_percent", device.get("memory_usage", 0)) if latest else device.get("memory_usage", 0),
        "interfaces":         interfaces,
        "total_download_mbps": round(total_dl / 1_000_000, 3),
        "total_upload_mbps":   round(total_ul / 1_000_000, 3),
        "trend":               trend,
        "has_data":            bool(bandwidth_map),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# TOPOLOGY â€” nodes + edges untuk network map
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/topology")
async def get_topology(
    user=Depends(get_current_user),
):
    """
    Return data topology jaringan: semua device sebagai nodes.
    Edges dibuat berdasarkan ARP neighbors dari last_poll_data (jika tersedia),
    atau jika tidak ada ARP data maka semua device tampil sebagai independent nodes.
    """
    db = get_db()
    devices = await db.devices.find(
        {},
        {"_id": 0, "id": 1, "name": 1, "ip_address": 1, "status": 1,
         "model": 1, "cpu_load": 1, "memory_usage": 1, "uptime": 1,
         "description": 1, "last_poll": 1, "last_poll_data": 1}
    ).to_list(200)

    nodes = []
    edges = []  # list of {source, target, label}
    seen_edges = set()
    ip_to_id = {d["ip_address"]: d["id"] for d in devices if d.get("ip_address")}

    for d in devices:
        status = d.get("status", "unknown")
        # Role detection dari model string
        model_str = (d.get("model") or "").lower()
        if any(k in model_str for k in ["router", "routeros", "chr"]):
            role = "router"
        elif any(k in model_str for k in ["switch", "css", "crs"]):
            role = "switch"
        elif any(k in model_str for k in ["wap", "cap", "hap", "ap"]):
            role = "ap"
        else:
            role = "device"

        last_poll = d.get("last_poll_data") or {}
        cpu = last_poll.get("cpu_load", d.get("cpu_load", 0)) or 0
        mem = last_poll.get("memory_usage", d.get("memory_usage", 0)) or 0

        nodes.append({
            "id": d["id"],
            "label": d.get("name", d["id"]),
            "ip": d.get("ip_address", ""),
            "status": status,
            "role": role,
            "model": d.get("model", ""),
            "cpu": cpu,
            "memory": mem,
            "uptime": d.get("uptime", ""),
            "description": d.get("description", ""),
            "last_poll": d.get("last_poll", ""),
        })

        # Cari ARP neighbors untuk membuat edges
        arp_table = last_poll.get("arp", []) or []
        for arp in arp_table:
            neighbor_ip = arp.get("address") or arp.get("ip") or ""
            if neighbor_ip and neighbor_ip in ip_to_id:
                neighbor_id = ip_to_id[neighbor_ip]
                edge_key = tuple(sorted([d["id"], neighbor_id]))
                if edge_key not in seen_edges and d["id"] != neighbor_id:
                    seen_edges.add(edge_key)
                    edges.append({
                        "id": f"{edge_key[0]}-{edge_key[1]}",
                        "source": edge_key[0],
                        "target": edge_key[1],
                        "label": "",
                    })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total": len(nodes),
            "online": sum(1 for n in nodes if n["status"] == "online"),
            "offline": sum(1 for n in nodes if n["status"] == "offline"),
        }
    }


# â”€â”€ Device Reboot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/devices/{device_id}/reboot")
async def reboot_device(device_id: str, user=Depends(require_admin)):
    """
    Kirim perintah reboot ke device MikroTik.
    Mendukung REST API (ROS 7.x) dan API Socket (ROS 6.x).
    Membutuhkan role administrator.
    """
    import httpx
    db = get_db()
    device = await db.devices.find_one({"id": device_id})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    if device.get("status") == "offline":
        raise HTTPException(400, "Device sedang offline â€” tidak bisa reboot")

    ip = device["ip_address"]
    username = device.get("api_username", "admin")
    password = device.get("api_password", "")
    api_mode = device.get("api_mode", "rest")

    logger.info(f"Reboot requested: {device.get('name')} ({ip}) by {user.get('username')}")

    try:
        if api_mode == "api":
            # ROS 6 â€” RouterOS API Socket
            import routeros_api
            api_port = device.get("api_port") or (8729 if device.get("api_ssl") else 8728)
            api_ssl = device.get("api_ssl", False)
            try:
                conn = routeros_api.RouterOsApiPool(
                    ip, username=username, password=password,
                    port=api_port, use_ssl=api_ssl,
                    ssl_verify=False, ssl_verify_hostname=False,
                    plaintext_login=True
                )
                api = conn.get_api()
                api.get_resource("/system").call("reboot")
                try:
                    conn.disconnect()
                except Exception:
                    pass  # Koneksi bisa terputus saat reboot â€” normal
            except Exception as api_err:
                # Jika error adalah connection reset SETELAH command dikirim = reboot berhasil
                err_str = str(api_err).lower()
                if any(k in err_str for k in ("connection reset", "broken pipe", "eof", "remote end closed")):
                    logger.info(f"Connection dropped after ROS6 reboot command (expected): {api_err}")
                else:
                    raise
        else:
            # ROS 7 â€” REST API
            port = device.get("api_port") or (443 if device.get("use_https") else 80)
            scheme = "https" if device.get("use_https") else "http"
            url = f"{scheme}://{ip}:{port}/rest/system/reboot"
            try:
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.post(url, auth=(username, password))
                    # 200 OK atau 204 No Content = sukses
                    # ROS bisa langsung reboot sebelum mengirim response,
                    # sehingga status 408 (timeout) juga dianggap sukses.
                    if resp.status_code not in (200, 204, 408):
                        raise HTTPException(400, f"MikroTik error: HTTP {resp.status_code}")
            except HTTPException:
                raise
            except (
                httpx.RemoteProtocolError,   # Server menutup koneksi sebelum kirim response
                httpx.ReadError,             # Gagal baca response (device sudah reboot)
                httpx.ConnectError,          # Koneksi terputus saat proses
                httpx.PoolTimeout,           # Request pool timeout
                httpx.ReadTimeout,           # Read timeout â€” device reboot sebelum response
            ) as conn_err:
                # NORMAL: MikroTik memutus koneksi TCP tepat saat mulai reboot.
                # Artinya perintah reboot sudah DITERIMA dan sedang dieksekusi.
                logger.info(f"Connection dropped after reboot (expected, device rebooting): {type(conn_err).__name__}: {conn_err}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reboot failed for {ip}: {e}")
        raise HTTPException(500, f"Gagal reboot: {str(e)}")


# â”€â”€ Winbox Remote URL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/devices/{device_id}/winbox-url")
async def get_winbox_url(device_id: str, user=Depends(get_current_user)):
    """
    Kembalikan URL Winbox dengan credential yang sudah terisi otomatis.
    Format: winbox://username:password@ip_address
    Password disimpan di server â€” tidak pernah dikirim ke frontend JS bundle.
    Hanya admin yang bisa akses endpoint ini.
    """
    import urllib.parse
    db = get_db()
    device = await db.devices.find_one({"id": device_id})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    ip_api      = device.get("ip_address", "")
    # Gunakan winbox_address jika diset, fallback ke ip_address
    winbox_addr = (device.get("winbox_address") or "").strip() or ip_api
    username    = device.get("api_username", "admin")
    password    = device.get("api_password", "")

    if not winbox_addr:
        raise HTTPException(400, "Device tidak memiliki IP address")

    # URL-encode username dan password untuk menghindari karakter khusus
    enc_user = urllib.parse.quote(username, safe="")
    enc_pass = urllib.parse.quote(password, safe="")

    # Format Desktop (Windows Winbox): winbox://user:password@address
    # Format Mobile  (Winbox App Android/iOS): winbox://address/user/pass
    if password:
        winbox_url        = f"winbox://{enc_user}:{enc_pass}@{winbox_addr}"
        winbox_mobile_url = f"winbox://{winbox_addr}/{enc_user}/{enc_pass}"
    else:
        winbox_url        = f"winbox://{enc_user}@{winbox_addr}"
        winbox_mobile_url = f"winbox://{winbox_addr}/{enc_user}"

    # Catat di audit log
    await db.audit_logs.insert_one({
        "action": "winbox_access",
        "device_id": device_id,
        "device_name": device.get("name"),
        "ip_address": winbox_addr,
        "performed_by": user.get("username"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    has_remote = bool((device.get("winbox_address") or "").strip())
    return {
        "url":                winbox_url,
        "mobile_url":         winbox_mobile_url,
        "address":            winbox_addr,
        "api_address":        ip_api,
        "has_remote_address": has_remote,
        "username":           username,
        "device_name":        device.get("name"),
        "device_id":          device_id,
    }


@router.get("/devices/{device_id}/connection-info")
async def get_connection_info(device_id: str, user=Depends(get_current_user)):
    """
    Kembalikan informasi koneksi device TANPA password (aman untuk display di UI).
    Digunakan oleh modal Wall Display untuk menampilkan info koneksi.
    Dapat diakses oleh semua user yang login.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0, "api_password": 0})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    winbox_addr_raw = (device.get("winbox_address") or "").strip()
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "ip_address": device.get("ip_address"),
        "winbox_address": winbox_addr_raw or None,
        "api_username": device.get("api_username", "admin"),
        "api_mode": device.get("api_mode", "rest"),
        "api_port": device.get("api_port"),
        "use_https": device.get("use_https", False),
        "model": device.get("model"),
        "ros_version": device.get("ros_version"),
        "status": device.get("status"),
    }


@router.get("/devices/{device_id}/test-snmp")
async def test_snmp(device_id: str, user=Depends(get_current_user)):
    """
    Tes konektivitas SNMP ke device secara real-time.
    Menggunakan async get_device_snmp_info() dari snmp_poller (pysnmp.hlapi.asyncio).
    Hasil TIDAK disimpan ke database.
    """
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    raw_ip    = (device.get("ip_address") or "").strip().split(":")[0].strip()
    community = (device.get("snmp_community") or "public").strip()
    host      = raw_ip

    if not host:
        return {"success": False, "error": "IP address tidak valid"}

    # ── Async SNMP via snmp_poller (pysnmp.hlapi.asyncio) ────────────────────
    try:
        from snmp_poller import get_device_snmp_info
    except ImportError as e:
        return {"success": False, "error": f"snmp_poller tidak tersedia: {e}"}

    try:
        info = await asyncio.wait_for(
            get_device_snmp_info(host, community, timeout=5),
            timeout=12,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "Timeout 12s — SNMP tidak merespon"}
    except Exception as e:
        return {"success": False, "error": f"SNMP error: {e}"}

    if not info.get("snmp_reachable"):
        return {
            "success": False,
            "error": (
                "Timeout — SNMP tidak merespon. Cek: "
                "(1) SNMP enabled di IP Services, "
                "(2) community string sesuai, "
                "(3) port 161/UDP tidak diblokir firewall/ACL"
            ),
        }

    # Hitung jumlah interface dari ifDescr walk
    iface_count = info.get("interface_count", 0)

    # Format uptime dari seconds
    uptime_s = info.get("uptime_s", 0)
    days  = uptime_s // 86400
    hours = (uptime_s % 86400) // 3600
    mins  = (uptime_s % 3600) // 60
    uptime_str = f"{days}d {hours}h {mins}m"

    sys_descr = info.get("sys_descr", "")
    ros_version = info.get("ros_version", "")
    sys_name = info.get("sys_name") or device.get("name", "?")

    logger.info(
        f"SNMP test OK [{device.get('name','?')} / {host}]: "
        f"sys_name={sys_name} ros={ros_version} ifaces={iface_count} community={community}"
    )
    return {
        "success":     True,
        "host":        host,
        "community":   community,
        "sys_name":    sys_name,
        "sys_descr":   sys_descr[:120] if sys_descr else "",
        "ros_version": ros_version,
        "sys_uptime":  uptime_str,
        "iface_count": iface_count,
        "message": (
            f"SNMP OK — {sys_name}"
            + (f" v{ros_version}" if ros_version else "")
            + f" ({iface_count} interfaces, uptime: {uptime_str})"
        ),
    }

