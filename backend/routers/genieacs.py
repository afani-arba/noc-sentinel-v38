"""
GenieACS router: endpoints for managing TR-069 CPE devices via GenieACS NBI.
All endpoints prefixed with /genieacs
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from core.auth import get_current_user, require_admin
from services import genieacs_service as svc

router = APIRouter(prefix="/genieacs", tags=["genieacs"])
logger = logging.getLogger(__name__)


def _err(e: Exception, default="GenieACS error"):
    msg = str(e)
    if "Connection refused" in msg or "Failed to establish" in msg:
        raise HTTPException(503, "Tidak dapat terhubung ke GenieACS. Pastikan GENIEACS_URL benar dan server GenieACS aktif.")
    if "401" in msg or "Unauthorized" in msg:
        raise HTTPException(401, "Autentikasi GenieACS gagal. Periksa GENIEACS_USERNAME dan GENIEACS_PASSWORD.")
    if "404" in msg:
        raise HTTPException(404, "Device tidak ditemukan di GenieACS.")
    raise HTTPException(502, f"{default}: {msg}")


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(user=Depends(get_current_user)):
    """Overall GenieACS stats: total, online, offline, faults."""
    try:
        return await asyncio.to_thread(svc.get_stats)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get stats")


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_devices(
    limit: int = Query(200, le=1000),
    search: str = Query(""),
    model: str = Query(""),
    user=Depends(get_current_user),
):
    """List CPE devices with optional search/filter."""
    try:
        devices = await asyncio.to_thread(svc.get_devices, limit, search, model)
        return _normalize_devices(devices)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to list devices")


@router.get("/devices/{device_id:path}")
async def get_device(device_id: str, user=Depends(get_current_user)):
    """Get detailed info + parameter tree for one device."""
    try:
        return await asyncio.to_thread(svc.get_device, device_id)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get device")


# ── Actions ───────────────────────────────────────────────────────────────────

@router.post("/devices/{device_id:path}/reboot")
async def reboot_device(device_id: str, user=Depends(require_admin)):
    """Send reboot command to CPE."""
    try:
        result = await asyncio.to_thread(svc.reboot_device, device_id)
        return {"message": "Perintah reboot dikirim ke device", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Reboot failed")


@router.post("/devices/{device_id:path}/factory-reset")
async def factory_reset(device_id: str, user=Depends(require_admin)):
    """Send factory reset to CPE."""
    try:
        result = await asyncio.to_thread(svc.factory_reset_device, device_id)
        return {"message": "Perintah factory reset dikirim", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Factory reset failed")


@router.post("/devices/{device_id:path}/refresh")
async def refresh_device(device_id: str, user=Depends(require_admin)):
    """Refresh all parameters from CPE."""
    try:
        result = await asyncio.to_thread(svc.refresh_device, device_id)
        return {"message": "Refresh parameter dikirim", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Refresh failed")


@router.post("/devices/{device_id:path}/set-parameter")
async def set_param(device_id: str, body: dict, user=Depends(require_admin)):
    """Set a specific TR-069 parameter on device."""
    name = body.get("name")
    value = body.get("value", "")
    type_ = body.get("type", "xsd:string")
    if not name:
        raise HTTPException(400, "Parameter name wajib diisi")
    try:
        result = await asyncio.to_thread(svc.set_parameter, device_id, name, value, type_)
        return {"message": f"Parameter {name} berhasil diset", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Set parameter failed")


# ── Faults ────────────────────────────────────────────────────────────────────

@router.get("/faults")
async def list_faults(limit: int = Query(100), user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(svc.get_faults, limit)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get faults")


@router.delete("/faults/{fault_id:path}")
async def delete_fault(fault_id: str, user=Depends(require_admin)):
    try:
        return await asyncio.to_thread(svc.delete_fault, fault_id)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to delete fault")


# ── Presets & Files ───────────────────────────────────────────────────────────

@router.get("/presets")
async def list_presets(user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(svc.get_presets)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get presets")


@router.get("/files")
async def list_files(user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(svc.get_files)
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Failed to get files")


# ── Test Connection ───────────────────────────────────────────────────────────

@router.post("/devices/{device_id:path}/summon")
async def summon_device(device_id: str, user=Depends(require_admin)):
    """Trigger connection request to CPE (summon device to check in)."""
    try:
        result = await asyncio.to_thread(svc.summon_device, device_id)
        return {"message": "Connection request dikirim ke device", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        _err(e, "Summon failed")


@router.post("/bulk-reboot")
async def bulk_reboot(
    body: dict,
    user=Depends(require_admin),
):
    """
    Bulk reboot ONT via GenieACS.
    Terima: {device_ids: ["id1", "id2"]} atau {filter: "offline"}
    Return: {success, failed, total, results}
    """
    device_ids: list[str] = body.get("device_ids", [])
    filter_mode: str = body.get("filter", "")  # "offline" = otomatis ambil semua offline

    # Jika filter=offline, ambil semua device yang offline dari GenieACS
    if filter_mode == "offline" and not device_ids:
        try:
            all_devices = await asyncio.to_thread(svc.get_devices, 500, "", "")
            device_ids = [
                d.get("_id", "")
                for d in all_devices
                if not _is_online(d)
            ]
        except Exception as e:
            raise HTTPException(502, f"Gagal ambil daftar device offline: {e}")

    if not device_ids:
        return {"message": "Tidak ada device yang perlu di-reboot", "success": 0, "failed": 0, "total": 0, "results": []}

    async def _do_reboot(dev_id: str) -> dict:
        try:
            result = await asyncio.to_thread(svc.reboot_device, dev_id)
            return {"device_id": dev_id, "success": True, "message": "Reboot task dikirim", "result": result}
        except Exception as e:
            return {"device_id": dev_id, "success": False, "message": str(e)}

    # Concurrent reboot — batching 20 per wave agar tidak overload GenieACS
    BATCH = 20
    all_results = []
    for i in range(0, len(device_ids), BATCH):
        batch = device_ids[i:i + BATCH]
        batch_results = await asyncio.gather(*[_do_reboot(did) for did in batch])
        all_results.extend(batch_results)

    success = sum(1 for r in all_results if r["success"])
    failed = len(all_results) - success

    return {
        "message": f"Bulk reboot selesai: {success} berhasil, {failed} gagal",
        "success": success,
        "failed": failed,
        "total": len(all_results),
        "results": all_results,
    }


def _is_online(device: dict) -> bool:
    """Cek apakah device GenieACS online (last_inform < 15 menit)."""
    from datetime import datetime, timezone, timedelta
    last = device.get("_lastInform", "")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        return dt > datetime.now(timezone.utc) - timedelta(minutes=15)
    except Exception:
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_rx(v: str) -> bool:
    """
    Return True jika nilai RX power bermakna (bukan kosong / nol / N/A).
    Alasan: GenieACS kadang mengirim "0", "0.0", integer 0, "-0.0", atau "N/A"
    untuk perangkat yang belum punya data PON — harus di-skip agar fallback
    ke path alternatif.
    """
    if not v or not v.strip():
        return False
    s = v.strip().lower()
    if s in ("n/a", "na", "null", "none", "-"):
        return False
    try:
        return float(s) != 0.0
    except ValueError:
        return bool(s)


def _normalize_devices(devices: list) -> list:
    """Extract key fields from raw GenieACS device objects for list view."""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    result = []
    for d in devices:
        last_inform = d.get("_lastInform", "")
        is_online = False
        if last_inform:
            try:
                dt = datetime.fromisoformat(last_inform.replace("Z", "+00:00"))
                is_online = dt > cutoff
            except Exception:
                pass

        igd = d.get("InternetGatewayDevice", {})
        dev_info = igd.get("DeviceInfo", {})
        device_id = d.get("_id", "")

        # WAN connection — try PPP first then IP
        wan_conn_dev = (
            igd.get("WANDevice", {})
               .get("1", {})
               .get("WANConnectionDevice", {})
               .get("1", {})
        )
        wan_ppp = wan_conn_dev.get("WANPPPConnection", {}).get("1", {})
        wan_ip  = wan_conn_dev.get("WANIPConnection", {}).get("1", {})

        pppoe_username = _val(wan_ppp, "Username") or _val(wan_ip, "Username")
        pppoe_ip       = _val(wan_ppp, "ExternalIPAddress") or _val(wan_ip, "ExternalIPAddress")

        # LAN / WiFi
        lan1 = igd.get("LANDevice", {}).get("1", {})
        wlan = lan1.get("WLANConfiguration", {}).get("1", {})
        hosts = lan1.get("Hosts", {})
        ssid          = _val(wlan, "SSID")
        active_devices = _val(hosts, "HostNumberOfEntries") or "0"

        # Product Class — from DeviceInfo, fallback parse from device ID (OUI-ProductClass-Serial)
        product_class = _val(dev_info, "ProductClass")
        if not product_class and device_id:
            parts = device_id.split("-")
            if len(parts) >= 2:
                product_class = parts[1]  # e.g. "688AF0-F663NV3A-ZTEGCA8..." → "F663NV3A"

        # Redaman ONT — try VirtualParameters first, then vendor-specific IGD paths
        rx_power = ""
        device_id = d.get("_id", "")

        # LOG: catat VP keys dan WANDevice.1 keys untuk diagnosa
        vp = d.get("VirtualParameters") or {}
        wan_device_obj = igd.get("WANDevice") or {}
        wan_dev1 = wan_device_obj.get("1") or {} if isinstance(wan_device_obj, dict) else {}
        logger.debug(
            "[rxpower] device=%s vp_keys=%s wan1_keys=%s",
            device_id,
            list(vp.keys()),
            list(wan_dev1.keys()) if isinstance(wan_dev1, dict) else [],
        )
        for vp_key in [
            # ── Nama-nama dengan SPASI (dari screenshot GenieACS UI) ──
            "Optic Rx Power",      # ← EXACT: terlihat di GenieACS UI F663NV3A EPON
            "Optic RX Power",
            "Optic RxPower",
            "RX Power",
            "Rx Power",
            # ── Nama tanpa spasi (camelCase / snake_case) ──
            "RXPower",
            "RxPower",
            "OpticRxPower",
            "opticRxPower",
            "optic_rx_power",
            "OpticalRxPower",
            "rxPower",
            "rx_power",
            "EponRxPower",
            "eponRxPower",
            "PonRxPower",
            "GponRxPower",
            "RxSignal",
            "RxOpticalPower",
            "optical_rx_power",
            "TransmitPower",
        ]:
            v = _val(vp, vp_key)
            if _valid_rx(v):
                rx_power = v
                logger.debug("[rxpower] device=%s found via VP key='%s' val=%s", device_id, vp_key, v)
                break


        if not rx_power:
            # 2. Path UTAMA ZTE EPON/GPON via WANDevice.1
            zte_wan_configs = [
                "X_ZTE-COM_WANPONInterfaceConfig",
                "X_ZTE-COM_WANEPONInterfaceConfig",
                "X_ZTE-COM_WANGPONInterfaceConfig",
            ]
            for cfg_key in zte_wan_configs:
                cfg_obj = wan_dev1.get(cfg_key, {}) if isinstance(wan_dev1, dict) else {}
                if isinstance(cfg_obj, dict):
                    v = (_val(cfg_obj, "RXPower") or _val(cfg_obj, "RxPower")
                         or _val(cfg_obj, "Rx_Power") or _val(cfg_obj, "RxOpticalPower"))
                    if _valid_rx(v):
                        rx_power = v
                        logger.debug("[rxpower] device=%s found via ZTE WANDevice.1.%s val=%s", device_id, cfg_key, v)
                        break

        if not rx_power:
            # 3. CT-COM paths via WANDevice.1
            ct_wan_configs = [
                "X_CT-COM_GponInterfaceConfig",
                "X_CT-COM_EponInterfaceConfig",
                "X_CT-COM_WANPONInterfaceConfig",
            ]
            for cfg_key in ct_wan_configs:
                cfg_obj = wan_dev1.get(cfg_key, {}) if isinstance(wan_dev1, dict) else {}
                if isinstance(cfg_obj, dict):
                    v = _val(cfg_obj, "RXPower") or _val(cfg_obj, "RxPower")
                    if _valid_rx(v):   # FIX: was using old inline check
                        rx_power = v
                        logger.debug("[rxpower] device=%s found via CT-COM WANDevice.1.%s val=%s", device_id, cfg_key, v)
                        break

        if not rx_power:
            # 4. Nested ZTE paths langsung di IGD root (older firmware)
            for parent_key, child_key in [
                ("X_ZTE-COM_ONU_PonPower",     "RxPower"),
                ("X_ZTE-COM_ONU_PonPower",     "Rx_Power"),
                ("X_ZTE-COM_GponOnu",          "RxPower"),
                ("X_ZTE-COM_GponOnu",          "RxOpticalPower"),
                ("X_ZTE-COM_OntOptics",        "RxPower"),
                ("X_ZTE-COM_EponOnu",          "RxPower"),
                ("X_ZTE-COM_GPON",             "RxPower"),
                ("X_FIBERHOME-COM_GponStatus", "RxPower"),
                ("X_CT-COM_GponOntPower",      "RxPower"),
            ]:
                parent = igd.get(parent_key, {})
                if isinstance(parent, dict):
                    v = _val(parent, child_key)
                    if _valid_rx(v):
                        rx_power = v
                        logger.debug("[rxpower] device=%s found via IGD.%s.%s val=%s", device_id, parent_key, child_key, v)
                        break

        if not rx_power:
            logger.debug("[rxpower] device=%s NOT FOUND — vp_keys=%s wan1_keys=%s",
                         device_id, list(vp.keys()),
                         list(wan_dev1.keys()) if isinstance(wan_dev1, dict) else [])


        result.append({
            "id": device_id,
            "manufacturer": _val(dev_info, "Manufacturer"),
            "model": _val(dev_info, "ModelName"),
            "product_class": product_class,
            "serial": _val(dev_info, "SerialNumber"),
            "firmware": _val(dev_info, "SoftwareVersion"),
            "uptime": _val(dev_info, "UpTime"),
            "ip": pppoe_ip or _val(wan_ip, "ExternalIPAddress"),
            "pppoe_username": pppoe_username,
            "pppoe_ip": pppoe_ip,
            "ssid": ssid,
            "active_devices": active_devices,
            "rx_power": rx_power,   # redaman ONT
            "last_inform": last_inform,
            "online": is_online,
            "registered": d.get("_registered", ""),
        })
    return result


def _val(obj: dict, key: str) -> str:
    """
    Extract ._value from GenieACS parameter dict.
    Handles 3 cases GenieACS mengirim data:
      1. {"_value": -23.5, "_type": "xsd:int"}  → ambil _value
      2. Nilai langsung (str/int/float) tanpa wrapper dict
      3. Key tidak ada atau obj kosong → return ""
    """
    if not obj or key not in obj:
        return ""
    item = obj[key]
    if isinstance(item, dict):
        v = item.get("_value")
        if v is None:
            return ""
        return str(v).strip()
    # Nilai langsung (bukan dict)
    if isinstance(item, (int, float)):
        return str(item)
    return str(item).strip()


# ── Debug Endpoint ──────────────────────────────────────────────────────────────

@router.get("/devices/{device_id:path}/debug")
async def debug_device(device_id: str, user=Depends(require_admin)):
    """
    Return raw data struktur device untuk diagnosa path RXPower.
    Cek: VirtualParameters, WANDevice.1 (ZTE/CT-COM PON path), IGD root keys.
    """
    try:
        raw = await asyncio.to_thread(svc.get_device, device_id)
        if isinstance(raw, list):
            raw = raw[0] if raw else {}

        igd     = raw.get("InternetGatewayDevice", {}) or {}
        vp      = raw.get("VirtualParameters", {}) or {}
        wan1    = igd.get("WANDevice", {}).get("1", {}) if isinstance(igd.get("WANDevice"), dict) else {}

        # ── VirtualParameters lengkap ──────────────────────────────────────────
        vp_values = {}
        for k, v in vp.items():
            vp_values[k] = v.get("_value") if isinstance(v, dict) else v

        # ── WANDevice.1 top-level keys ─────────────────────────────────────────
        wan1_keys = list(wan1.keys()) if isinstance(wan1, dict) else []

        # ── Cari semua key PON yang mengandung RXPower / RxPower ──────────────
        pon_configs = {}
        pon_keywords = ["PON", "GPON", "EPON", "ONU", "OLT", "Optic", "Fiber"]
        for k in wan1_keys:
            if any(kw.upper() in k.upper() for kw in pon_keywords) or k.startswith("X_"):
                obj = wan1.get(k, {})
                if isinstance(obj, dict):
                    pon_configs[f"WANDevice.1.{k}"] = {
                        sk: sv.get("_value") if isinstance(sv, dict) else sv
                        for sk, sv in obj.items()
                    }

        # ── IGD root level vendor keys ─────────────────────────────────────────
        igd_vendor = {}
        for k in igd.keys():
            if k.startswith("X_") or any(kw.upper() in k.upper() for kw in pon_keywords):
                obj = igd.get(k, {})
                if isinstance(obj, dict):
                    igd_vendor[k] = {
                        sk: sv.get("_value") if isinstance(sv, dict) else sv
                        for sk, sv in list(obj.items())[:30]
                    }

        # ── Coba extract rx_power pakai logika normalizer ──────────────────────
        [norm] = _normalize_devices([raw])
        rx_found = norm.get("rx_power", "")

        return {
            "device_id": device_id,
            "rx_power_extracted": rx_found,   # hasil dari normalizer — apakah berhasil?
            "raw_top_keys": list(raw.keys()),
            "igd_top_keys": list(igd.keys()),
            "wan1_top_keys": wan1_keys,
            "virtual_parameters": vp_values,       # semua VP + nilainya
            "pon_configs_in_wan1": pon_configs,    # KUNCI: ZTE/CT-COM PON di WANDevice.1
            "igd_vendor_keys": igd_vendor,         # fallback: vendor key di IGD root
        }
    except Exception as e:
        _err(e, "Debug failed")


# ── Health Check ──────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check(user=Depends(get_current_user)):
    """Test connectivity to GenieACS server. Returns {connected, url, latency_ms, error}."""
    try:
        result = await asyncio.to_thread(svc.check_health)
        return result
    except Exception as e:
        return {"connected": False, "url": "", "latency_ms": 0, "error": str(e)}
