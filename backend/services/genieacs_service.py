"""
GenieACS NBI (Northbound Interface) service.
Connects to GenieACS REST API at port 7557 to manage TR-069 CPE devices.

Configure via .env:
  GENIEACS_URL=http://10.x.x.x:7557
  GENIEACS_USERNAME=admin
  GENIEACS_PASSWORD=secret
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

GENIEACS_URL = os.environ.get("GENIEACS_URL", "http://localhost:7557").rstrip("/")
GENIEACS_USER = os.environ.get("GENIEACS_USERNAME", "")
GENIEACS_PASS = os.environ.get("GENIEACS_PASSWORD", "")
TIMEOUT = 20


def _auth() -> Optional[tuple]:
    if GENIEACS_USER:
        return (GENIEACS_USER, GENIEACS_PASS)
    return None


def _get(path: str, params: dict = None) -> any:
    url = f"{GENIEACS_URL}/{path.lstrip('/')}"
    resp = requests.get(url, params=params, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict = None) -> any:
    url = f"{GENIEACS_URL}/{path.lstrip('/')}"
    resp = requests.post(url, json=data, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code}


def _delete(path: str) -> any:
    url = f"{GENIEACS_URL}/{path.lstrip('/')}"
    resp = requests.delete(url, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return {"success": True}


# ── Devices ───────────────────────────────────────────────────────────────────

def get_devices(limit: int = 200, search: str = "", model: str = "") -> list:
    """
    List all CPE devices from GenieACS.
    GenieACS query uses MongoDB-style queries via 'query' param.
    """
    # Eksplisit projection agar VirtualParameters & WANDevice fields pasti disertakan.
    # PENTING: path ZTE PON ada di DALAM WANDevice.1, bukan langsung di IGD root.
    projection_fields = [
        "_id", "_lastInform", "_registered",
        "VirtualParameters",
        "InternetGatewayDevice.DeviceInfo",
        "InternetGatewayDevice.LANDevice",
        # --- WANDevice (PPPoE IP + koneksi + PON interface) ---
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1",
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1",
        # --- ZTE EPON/GPON via WANDevice.1 (path utama F663NV3A) ---
        "InternetGatewayDevice.WANDevice.1.X_ZTE-COM_WANPONInterfaceConfig",
        "InternetGatewayDevice.WANDevice.1.X_ZTE-COM_WANEPONInterfaceConfig",
        "InternetGatewayDevice.WANDevice.1.X_ZTE-COM_WANGPONInterfaceConfig",
        # --- CT-COM GPON/EPON via WANDevice.1 ---
        "InternetGatewayDevice.WANDevice.1.X_CT-COM_GponInterfaceConfig",
        "InternetGatewayDevice.WANDevice.1.X_CT-COM_EponInterfaceConfig",
        "InternetGatewayDevice.WANDevice.1.X_CT-COM_WANPONInterfaceConfig",
        # --- ZTE path langsung di IGD (older firmware) ---
        "InternetGatewayDevice.X_ZTE-COM_ONU_PonPower",
        "InternetGatewayDevice.X_ZTE-COM_GponOnu",
        "InternetGatewayDevice.X_ZTE-COM_OntOptics",
        "InternetGatewayDevice.X_ZTE-COM_EponOnu",
        "InternetGatewayDevice.X_ZTE-COM_GPON",
        "InternetGatewayDevice.X_FIBERHOME-COM_GponStatus",
        "InternetGatewayDevice.X_CT-COM_GponOntPower",
    ]
    params = {
        "limit": limit,
        "projection": ",".join(projection_fields),
    }
    if search:
        params["query"] = (
            '{"$or":['
            f'{{"_id":{{"$regex":"{search}","$options":"i"}}}},'
            f'{{"InternetGatewayDevice.DeviceInfo.ModelName._value":{{"$regex":"{search}","$options":"i"}}}},'
            f'{{"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress._value":{{"$regex":"{search}","$options":"i"}}}}'
            ']}'
        )
    elif model:
        params["query"] = f'{{"InternetGatewayDevice.DeviceInfo.ModelName._value":{{"$regex":"{model}","$options":"i"}}}}'
    return _get("/devices", params)


def get_device(device_id: str) -> dict:
    """Get full parameter tree of one device."""
    return _get(f"/devices/{requests.utils.quote(device_id, safe='')}")


def get_rx_power_raw(device_id: str) -> str:
    """
    Fetch RXPower directly with minimal projection — untuk fallback / debug.
    Tries VirtualParameters.RXPower then WANDevice ZTE path.
    """
    fields = [
        "VirtualParameters.RXPower",
        "InternetGatewayDevice.WANDevice.1.X_ZTE-COM_WANPONInterfaceConfig.RXPower",
        "InternetGatewayDevice.WANDevice.1.X_ZTE-COM_WANEPONInterfaceConfig.RXPower",
        "InternetGatewayDevice.WANDevice.1.X_CT-COM_GponInterfaceConfig.RXPower",
        "InternetGatewayDevice.WANDevice.1.X_CT-COM_EponInterfaceConfig.RXPower",
    ]
    params = {
        "projection": ",".join(fields),
        "limit": 1,
        "query": '{"_id":"' + device_id.replace('"', '\\"') + '"}',
    }
    try:
        results = _get("/devices", params)
        if not results:
            return ""
        d = results[0]
        vp = d.get("VirtualParameters", {})
        rxp = vp.get("RXPower", {})
        if isinstance(rxp, dict) and rxp.get("_value") not in (None, "", "0", "0.0"):
            return str(rxp["_value"])
        igd = d.get("InternetGatewayDevice", {})
        wan1 = igd.get("WANDevice", {}).get("1", {})
        for cfg_key in [
            "X_ZTE-COM_WANPONInterfaceConfig",
            "X_ZTE-COM_WANEPONInterfaceConfig",
            "X_CT-COM_GponInterfaceConfig",
            "X_CT-COM_EponInterfaceConfig",
        ]:
            cfg = wan1.get(cfg_key, {})
            if isinstance(cfg, dict):
                rx = cfg.get("RXPower", {})
                if isinstance(rx, dict) and rx.get("_value") not in (None, "", "0", "0.0"):
                    return str(rx["_value"])
        return ""
    except Exception:
        return ""


def get_device_summary(device_id: str) -> dict:
    """Get key info fields for a device (lighter than full tree)."""
    fields = [
        "_id", "_lastInform", "_registered",
        "InternetGatewayDevice.DeviceInfo.Manufacturer._value",
        "InternetGatewayDevice.DeviceInfo.ModelName._value",
        "InternetGatewayDevice.DeviceInfo.SerialNumber._value",
        "InternetGatewayDevice.DeviceInfo.SoftwareVersion._value",
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress._value",
        "InternetGatewayDevice.DeviceInfo.UpTime._value",
        "VirtualParameters.Tag._value",
    ]
    params = {
        "projection": ",".join(fields),
        "limit": 1,
        "query": f'{{"_id":"{device_id}"}}',
    }
    results = _get("/devices", params)
    return results[0] if results else {}


def reboot_device(device_id: str) -> dict:
    """Send reboot task to device."""
    return _post(f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request", {"name": "reboot"})


def factory_reset_device(device_id: str) -> dict:
    """Send factory reset task to device."""
    return _post(f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request", {"name": "factoryReset"})


def refresh_device(device_id: str) -> dict:
    """Send refreshObject task to refresh all parameters."""
    return _post(
        f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request",
        {"name": "refreshObject", "objectName": ""}
    )


def set_parameter(device_id: str, param_name: str, param_value: str, param_type: str = "xsd:string") -> dict:
    """Set a TR-069 parameter on device."""
    return _post(
        f"/devices/{requests.utils.quote(device_id, safe='')}/tasks?timeout=3000&connection_request",
        {
            "name": "setParameterValues",
            "parameterValues": [[param_name, param_value, param_type]]
        }
    )


def summon_device(device_id: str) -> dict:
    """
    Send a connection request to the device (summon it to check in to ACS).
    Posts an empty connection request — no task, just forces device session.
    """
    url = f"{GENIEACS_URL}/devices/{requests.utils.quote(device_id, safe='')}/tasks?connection_request"
    resp = requests.post(url, json={"name": "refreshObject", "objectName": ""}, auth=_auth(), timeout=TIMEOUT)
    # 202 = task queued (device offline, will run on next inform)
    # 200 = task executed (device online, ran immediately)
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
    return {"status": resp.status_code, "queued": resp.status_code == 202}


# ── Faults ────────────────────────────────────────────────────────────────────

def get_faults(limit: int = 100) -> list:
    """List recent faults across all devices."""
    return _get("/faults", {"limit": limit})


def delete_fault(fault_id: str) -> dict:
    """Delete/resolve a fault."""
    return _delete(f"/faults/{fault_id}")


# ── Tasks ─────────────────────────────────────────────────────────────────────

def get_tasks(device_id: str) -> list:
    """List pending tasks for a device."""
    params = {"query": f'{{"device":"{device_id}"}}'}
    return _get("/tasks", params)


# ── Presets & Files ───────────────────────────────────────────────────────────

def get_presets() -> list:
    """List all provisioning presets."""
    return _get("/presets")


def get_files() -> list:
    """List firmware/config files uploaded to GenieACS."""
    return _get("/files")


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """
    Return overall stats: total devices, online count, faults count.
    'Online' = lastInform within last 15 minutes.
    """
    try:
        all_devices = _get("/devices", {"limit": 5000, "projection": "_id,_lastInform"})
        total = len(all_devices)

        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)

        online = 0
        for d in all_devices:
            last = d.get("_lastInform")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    if last_dt > cutoff:
                        online += 1
                except Exception:
                    pass

        faults = _get("/faults", {"limit": 1000, "projection": "_id"})
        return {"total": total, "online": online, "offline": total - online, "faults": len(faults)}
    except Exception as e:
        logger.warning(f"GenieACS stats error: {e}")
        return {"total": 0, "online": 0, "offline": 0, "faults": 0}
