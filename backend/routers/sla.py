"""
SLA Monitoring router v3:
SLA calculation, uptime heatmap, device grades, export.
Uses sla_events collection populated by polling.py on status transitions.
"""
import logging
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from core.db import get_db
from core.auth import get_current_user, require_admin

router = APIRouter(prefix="/sla", tags=["sla"])
logger = logging.getLogger(__name__)

SLA_GRADE_THRESHOLDS = {
    "A": 99.9,
    "B": 99.0,
    "C": 95.0,
}

def uptime_to_grade(uptime_pct: float) -> str:
    if uptime_pct >= SLA_GRADE_THRESHOLDS["A"]:
        return "A"
    elif uptime_pct >= SLA_GRADE_THRESHOLDS["B"]:
        return "B"
    elif uptime_pct >= SLA_GRADE_THRESHOLDS["C"]:
        return "C"
    return "D"


def calc_sla_for_device(device: dict, events: list, start: datetime, end: datetime) -> dict:
    """
    Calculate SLA metrics for a single device given its events in [start, end].
    events: list of {event_type, timestamp, duration_seconds}
    Returns: {uptime_pct, downtime_seconds, incident_count, mttr_seconds}
    """
    total_seconds = max((end - start).total_seconds(), 1)
    downtime_seconds = 0
    incident_count = 0
    mttr_total = 0

    # Sort events by timestamp
    sorted_events = sorted(events, key=lambda e: e.get("timestamp", ""))

    offline_start = None
    for ev in sorted_events:
        etype = ev.get("event_type", "")
        try:
            ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if etype == "offline":
            offline_start = ts
            incident_count += 1
        elif etype == "online" and offline_start is not None:
            duration = (ts - offline_start).total_seconds()
            downtime_seconds += max(0, duration)
            mttr_total += max(0, duration)
            offline_start = None

    # If device is currently offline, count till now
    if offline_start is not None:
        duration = (end - offline_start).total_seconds()
        downtime_seconds += max(0, duration)

    uptime_seconds = max(0, total_seconds - downtime_seconds)
    uptime_pct = round((uptime_seconds / total_seconds) * 100, 4)
    mttr_seconds = round(mttr_total / incident_count, 1) if incident_count > 0 else 0

    return {
        "uptime_pct": uptime_pct,
        "downtime_seconds": round(downtime_seconds),
        "incident_count": incident_count,
        "mttr_seconds": mttr_seconds,
    }


def _period_range(period: str):
    """Return (start, end) UTC datetimes for the given period string."""
    now = datetime.now(timezone.utc)
    if period == "7d":
        return now - timedelta(days=7), now
    elif period == "30d":
        return now - timedelta(days=30), now
    elif period == "90d":
        return now - timedelta(days=90), now
    else:  # default 30d
        return now - timedelta(days=30), now


@router.get("/summary")
async def sla_summary(
    period: str = Query("30d", description="7d | 30d | 90d"),
    user=Depends(get_current_user)
):
    """
    KPI cards: avg uptime %, total incidents, MTTR, top performer.
    """
    db = get_db()
    start, end = _period_range(period)
    start_str = start.isoformat()
    end_str = end.isoformat()

    devices = await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "status": 1}).to_list(200)
    if not devices:
        return {
            "avg_uptime_pct": 100.0, "total_incidents": 0,
            "mttr_minutes": 0, "top_performer": None, "period": period,
        }

    all_events = await db.sla_events.find(
        {"timestamp": {"$gte": start_str, "$lte": end_str}},
        {"_id": 0}
    ).to_list(10000)

    # Group events by device
    events_by_device: dict = {}
    for ev in all_events:
        did = ev.get("device_id", "")
        events_by_device.setdefault(did, []).append(ev)

    device_slas = []
    for d in devices:
        did = d["id"]
        devents = events_by_device.get(did, [])
        sla = calc_sla_for_device(d, devents, start, end)
        sla["device_id"] = did
        sla["device_name"] = d["name"]
        device_slas.append(sla)

    if not device_slas:
        return {"avg_uptime_pct": 100.0, "total_incidents": 0, "mttr_minutes": 0, "top_performer": None, "period": period}

    avg_uptime = round(sum(s["uptime_pct"] for s in device_slas) / len(device_slas), 2)
    total_incidents = sum(s["incident_count"] for s in device_slas)

    mttr_candidates = [s["mttr_seconds"] for s in device_slas if s["mttr_seconds"] > 0]
    overall_mttr = round(sum(mttr_candidates) / len(mttr_candidates) / 60, 1) if mttr_candidates else 0

    top = max(device_slas, key=lambda s: s["uptime_pct"])

    return {
        "avg_uptime_pct": avg_uptime,
        "total_incidents": total_incidents,
        "mttr_minutes": overall_mttr,
        "top_performer": {"name": top["device_name"], "uptime_pct": top["uptime_pct"]},
        "period": period,
        "total_devices": len(device_slas),
    }


@router.get("/devices")
async def sla_devices(
    period: str = Query("30d"),
    user=Depends(get_current_user)
):
    """
    Per-device SLA table: name, IP, uptime%, downtime, incident count, SLA grade.
    """
    db = get_db()
    start, end = _period_range(period)
    start_str = start.isoformat()

    devices = await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "ip_address": 1, "status": 1, "model": 1}).to_list(200)

    all_events = await db.sla_events.find(
        {"timestamp": {"$gte": start_str}},
        {"_id": 0}
    ).to_list(10000)

    events_by_device: dict = {}
    for ev in all_events:
        did = ev.get("device_id", "")
        events_by_device.setdefault(did, []).append(ev)

    result = []
    for d in devices:
        did = d["id"]
        devents = events_by_device.get(did, [])
        sla = calc_sla_for_device(d, devents, start, end)
        downtime_hr = round(sla["downtime_seconds"] / 3600, 2)
        mttr_min = round(sla["mttr_seconds"] / 60, 1)
        grade = uptime_to_grade(sla["uptime_pct"])
        result.append({
            "device_id": did,
            "name": d["name"],
            "ip_address": d.get("ip_address", ""),
            "model": d.get("model", ""),
            "status": d.get("status", "unknown"),
            "uptime_pct": sla["uptime_pct"],
            "downtime_hours": downtime_hr,
            "incident_count": sla["incident_count"],
            "mttr_minutes": mttr_min,
            "grade": grade,
        })

    result.sort(key=lambda x: x["uptime_pct"])
    return result


@router.get("/heatmap")
async def sla_heatmap(
    period: str = Query("30d"),
    device_id: Optional[str] = Query(None),
    user=Depends(get_current_user)
):
    """
    Uptime heatmap data in GitHub contribution graph style.
    Returns a list of {date, uptime_pct, downtime_hours, incident_count} per day.
    """
    db = get_db()
    start, end = _period_range(period)

    # Build date buckets
    days = []
    cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)

    # Get all SLA events in the range
    query_filter: dict = {
        "timestamp": {"$gte": start.isoformat(), "$lte": end.isoformat()}
    }
    if device_id:
        query_filter["device_id"] = device_id

    all_events = await db.sla_events.find(query_filter, {"_id": 0}).to_list(20000)

    # Get device list
    if device_id:
        devices = [{"id": device_id}]
    else:
        devices = await db.devices.find({}, {"_id": 0, "id": 1}).to_list(200)

    # Build daily summary
    result = []
    for day_start in days:
        day_end = day_start + timedelta(days=1)
        day_events = [
            e for e in all_events
            if day_start.isoformat() <= e.get("timestamp", "") < day_end.isoformat()
        ]

        total_downtime = 0
        total_incidents = 0

        for d in devices:
            did = d["id"]
            dev_events = [e for e in day_events if e.get("device_id") == did]
            sla = calc_sla_for_device(d, dev_events, day_start, day_end)
            total_downtime += sla["downtime_seconds"]
            total_incidents += sla["incident_count"]

        # Average downtime across devices (per-day, hours)
        downtime_hours = round(total_downtime / max(len(devices), 1) / 3600, 2)
        uptime_pct = round(100 - (downtime_hours / 24 * 100), 2)

        result.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "uptime_pct": max(0, min(100, uptime_pct)),
            "downtime_hours": downtime_hours,
            "incident_count": total_incidents,
        })

    return result


@router.get("/export")
async def sla_export(
    period: str = Query("30d"),
    user=Depends(get_current_user)
):
    """Export SLA device table as CSV."""
    devices_data = await sla_devices(period=period, user=user)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "name", "ip_address", "model", "status",
        "uptime_pct", "downtime_hours", "incident_count", "mttr_minutes", "grade"
    ])
    writer.writeheader()
    for row in devices_data:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    output.seek(0)
    filename = f"sla_report_{period}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/incidents-weekly")
async def sla_incidents_weekly(user=Depends(get_current_user)):
    """
    Return incident counts grouped by week for bar chart.
    Last 12 weeks.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    weeks = []
    for i in range(11, -1, -1):
        week_start = now - timedelta(weeks=i + 1)
        week_end = now - timedelta(weeks=i)
        label = week_start.strftime("%d/%m")
        count = await db.incidents.count_documents({
            "created_at": {
                "$gte": week_start.isoformat(),
                "$lt": week_end.isoformat(),
            }
        })
        weeks.append({"week": label, "count": count})
    return weeks
