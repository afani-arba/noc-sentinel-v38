"""
Core polling module: poll individual devices and run the background polling loop.
Also triggers WhatsApp notifications when threshold conditions are met.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from core.db import get_db
import snmp_service

logger = logging.getLogger(__name__)
POLL_INTERVAL = 30


async def poll_single_device(device: dict) -> dict:
    db = get_db()
    did = device["id"]
    host = device["ip_address"]
    port = device.get("snmp_port", 161)
    comm = device.get("snmp_community", "public")

    try:
        result = await asyncio.wait_for(snmp_service.poll_device(host, port, comm), timeout=25)
    except (asyncio.TimeoutError, Exception):
        result = {
            "reachable": False,
            "ping": {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
            "system": {}, "cpu": 0,
            "memory": {"total": 0, "used": 0, "percent": 0},
            "interfaces": [], "traffic": {},
            "health": {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0}
        }

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": "online" if result["reachable"] else "offline", "last_poll": now, "last_poll_data": result}

    if result["reachable"] and result.get("system"):
        s = result["system"]
        health = result.get("health", {})
        update.update({
            "model": s.get("board_name", ""),
            "sys_name": s.get("sys_name", ""),
            "identity": s.get("identity", s.get("sys_name", "")),
            "architecture": s.get("architecture", ""),
            "ros_version": s.get("ros_version", ""),
            "uptime": s.get("uptime_formatted", ""),
            "serial": s.get("serial", ""),
            "cpu_load": result.get("cpu", 0),
            "memory_usage": result.get("memory", {}).get("percent", 0),
            "cpu_temp": health.get("cpu_temp", 0),
            "board_temp": health.get("board_temp", 0),
            "voltage": health.get("voltage", 0),
            "power": health.get("power", 0),
        })

    # ── SLA Event Recording: detect status transitions ────────────────────────
    # Compare new status vs stored status to record online/offline events
    old_status = device.get("status", "unknown")
    new_status = update["status"]
    if old_status != new_status and new_status in ("online", "offline"):
        try:
            await db.sla_events.insert_one({
                "device_id": did,
                "device_name": device.get("name", did),
                "event_type": new_status,     # "online" or "offline"
                "from_status": old_status,
                "timestamp": now,
            })
            logger.info(f"SLA event recorded: {device.get('name', did)} → {new_status}")
        except Exception as sla_err:
            logger.debug(f"SLA event write failed: {sla_err}")

    await db.devices.update_one({"id": did}, {"$set": update})

    # Fire WhatsApp notifications if enabled
    try:
        from services.notification_service import check_and_notify
        await check_and_notify(device, result, update)
    except Exception as e:
        logger.debug(f"Notification check skipped: {e}")

    # Bandwidth calculation from octets diff
    prev = await db.traffic_snapshots.find_one({"device_id": did})
    curr_traffic = result.get("traffic", {})
    ping_data = result.get("ping", {})

    if prev and curr_traffic:
        prev_t = prev.get("traffic", {})
        try:
            delta = max((datetime.fromisoformat(now) - datetime.fromisoformat(prev["timestamp"])).total_seconds(), 1)
        except Exception:
            delta = POLL_INTERVAL
        bw = {}
        for iface, cv in curr_traffic.items():
            pv = prev_t.get(iface, {})
            if pv:
                ind = max(0, cv["in_octets"] - pv.get("in_octets", 0))
                outd = max(0, cv["out_octets"] - pv.get("out_octets", 0))
                if ind > 2**62: ind = 0
                if outd > 2**62: outd = 0
                bw[iface] = {
                    "download_bps": round((ind * 8) / delta),
                    "upload_bps": round((outd * 8) / delta),
                    "status": cv.get("status", "down")
                }
        if bw:
            await db.traffic_history.insert_one({
                "device_id": did, "timestamp": now, "bandwidth": bw,
                "ping_ms": ping_data.get("avg", 0),
                "jitter_ms": ping_data.get("jitter", 0),
                "cpu": result.get("cpu", 0),
                "memory_percent": result.get("memory", {}).get("percent", 0),
            })
            # Write to InfluxDB if configured
            try:
                from services.metrics_service import write_device_metrics, is_enabled
                if is_enabled():
                    metrics_payload = {
                        "cpu": result.get("cpu", 0),
                        "memory": result.get("memory", {}),
                        "ping": ping_data,
                        "health": result.get("health", {}),
                        "bandwidth": bw,
                    }
                    await asyncio.to_thread(
                        write_device_metrics,
                        did,
                        device.get("name", did),
                        metrics_payload,
                    )
            except Exception as e:
                logger.debug(f"InfluxDB write skipped: {e}")

    await db.traffic_snapshots.update_one(
        {"device_id": did},
        {"$set": {"device_id": did, "timestamp": now, "traffic": curr_traffic}},
        upsert=True
    )
    return result



async def polling_loop():
    """Background task: poll all devices every POLL_INTERVAL seconds."""
    while True:
        try:
            db = get_db()
            devices = await db.devices.find({}, {"_id": 0}).to_list(100)
            if devices:
                await asyncio.gather(*[poll_single_device(d) for d in devices], return_exceptions=True)
            # Cleanup data lama: simpan 31 hari agar tombol "Bulan" berfungsi
            # BUG FIX: sebelumnya 7 hari → data "Bulan" tidak pernah ada
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff}})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
