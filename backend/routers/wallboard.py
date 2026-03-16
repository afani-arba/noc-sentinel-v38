"""
Wallboard router: NOC Wall Display endpoints.
Provides aggregated device status, live metrics, and event ticker
for NOC wall display screens.
"""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from core.db import get_db
from core.auth import get_current_user

router = APIRouter(prefix="/wallboard", tags=["wallboard"])
logger = logging.getLogger(__name__)


@router.get("/status")
async def wallboard_status(user=Depends(get_current_user)):
    """
    Return all devices with full real-time metrics for wall display grid.
    Includes: status, CPU, memory, ping, uptime, last bandwidth.
    """
    db = get_db()
    devices = await db.devices.find({}, {"_id": 0, "snmp_community": 0, "api_password": 0}).to_list(200)

    enriched = []
    for d in devices:
        # Get latest traffic snapshot for bandwidth
        snap = await db.traffic_snapshots.find_one({"device_id": d["id"]})

        # Get last bandwidth from traffic_history
        last_bw = await db.traffic_history.find_one(
            {"device_id": d["id"]},
            {"_id": 0, "bandwidth": 1, "ping_ms": 1, "timestamp": 1},
            sort=[("timestamp", -1)]
        )

        download_bps = 0
        upload_bps = 0
        if last_bw and last_bw.get("bandwidth"):
            bw = last_bw["bandwidth"]
            download_bps = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
            upload_bps = sum(v.get("upload_bps", 0) for v in bw.values() if isinstance(v, dict))

        # Determine alert level
        alert_level = "normal"
        cpu = d.get("cpu_load", 0)
        mem = d.get("memory_usage", 0)
        ping = last_bw.get("ping_ms", 0) if last_bw else 0

        if d.get("status") == "offline":
            alert_level = "critical"
        elif cpu > 90 or mem > 90:
            alert_level = "critical"
        elif cpu > 75 or mem > 75 or ping > 100:
            alert_level = "warning"

        enriched.append({
            "id": d.get("id"),
            "name": d.get("name", ""),
            "identity": d.get("identity", d.get("sys_name", d.get("name", ""))),
            "ip_address": d.get("ip_address", ""),
            "status": d.get("status", "unknown"),
            "model": d.get("model", ""),
            "ros_version": d.get("ros_version", ""),
            "uptime": d.get("uptime", ""),
            "cpu_load": cpu,
            "memory_usage": mem,
            "cpu_temp": d.get("cpu_temp", 0),
            "board_temp": d.get("board_temp", 0),
            "ping_ms": round(ping, 1),
            "download_mbps": round(download_bps / 1_000_000, 2),
            "upload_mbps": round(upload_bps / 1_000_000, 2),
            "last_poll": d.get("last_poll", ""),
            "alert_level": alert_level,  # normal | warning | critical
        })

    # Sort: critical first, then warning, then normal; within each group: alphabetical
    order = {"critical": 0, "warning": 1, "normal": 2}
    enriched.sort(key=lambda x: (order.get(x["alert_level"], 3), x["name"]))

    # Summary stats
    total = len(enriched)
    online = sum(1 for d in enriched if d["status"] == "online")
    offline = sum(1 for d in enriched if d["status"] == "offline")
    warning = sum(1 for d in enriched if d["alert_level"] == "warning")

    return {
        "devices": enriched,
        "summary": {
            "total": total,
            "online": online,
            "offline": offline,
            "warning": warning,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }


@router.get("/events")
async def wallboard_events(limit: int = 30, user=Depends(get_current_user)):
    """
    Return recent NOC events for the bottom ticker.
    Sources: sla_events (online/offline transitions) + recent alerts.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()

    # Get recent SLA events (online/offline transitions)
    sla_events = await db.sla_events.find(
        {"timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(limit)

    # Get recent incidents
    incidents = await db.incidents.find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "title": 1, "severity": 1, "device_name": 1, "created_at": 1, "status": 1}
    ).sort("created_at", -1).to_list(10)

    events = []

    for e in sla_events:
        event_type = e.get("event_type", "")
        color = "green" if event_type == "online" else "red"
        events.append({
            "id": str(e.get("_id", "")),
            "type": event_type,
            "device_name": e.get("device_name", ""),
            "device_id": e.get("device_id", ""),
            "message": f"{e.get('device_name', 'Device')} went {event_type.upper()}",
            "timestamp": e.get("timestamp", ""),
            "color": color,
        })

    for inc in incidents:
        sev = inc.get("severity", "medium")
        color_map = {"critical": "red", "high": "orange", "medium": "yellow", "low": "blue"}
        events.append({
            "id": inc.get("id", ""),
            "type": "incident",
            "device_name": inc.get("device_name", ""),
            "message": f"INC: {inc.get('title', 'Incident')} [{sev.upper()}]",
            "timestamp": inc.get("created_at", ""),
            "color": color_map.get(sev, "yellow"),
        })

    # Sort by timestamp descending
    events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return {"events": events[:limit]}
