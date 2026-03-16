"""
Firewall & Connections router: active connections (top talkers), firewall rules.
"""
from fastapi import APIRouter, HTTPException, Depends
from core.db import get_db
from core.auth import get_current_user
from mikrotik_api import get_api_client
import asyncio

router = APIRouter(tags=["firewall"])


async def _get_mt(device_id: str):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    return get_api_client(device), device


def _parse_bytes(val: str) -> int:
    """Parse MikroTik byte value like '1.5 GiB', '123 KiB', '456 B' to int bytes."""
    if not val:
        return 0
    try:
        val = str(val).strip()
        if val.isdigit():
            return int(val)
        multipliers = {
            "GiB": 1024**3, "MiB": 1024**2, "KiB": 1024,
            "GB": 1e9, "MB": 1e6, "KB": 1e3,
            "G": 1024**3, "M": 1024**2, "K": 1024, "B": 1,
        }
        for suffix, mult in multipliers.items():
            if suffix in val:
                num = float(val.replace(suffix, "").strip())
                return int(num * mult)
        return int(float(val.split()[0]))
    except Exception:
        return 0


# ── Active Connections ───────────────────────────────────────

@router.get("/firewall/connections")
async def get_connections(device_id: str, search: str = "", top: int = 100, user=Depends(get_current_user)):
    """
    Get active connection tracking entries.
    Returns top talkers sorted by bytes.
    """
    if not device_id:
        return {"connections": [], "total": 0, "top_talkers": []}
    try:
        mt, _ = await _get_mt(device_id)
        conns = await mt.list_connections(limit=2000)

        # Parse and enrich connections
        enriched = []
        for c in conns:
            src = c.get("src-address", c.get("src_address", ""))
            dst = c.get("dst-address", c.get("dst_address", ""))
            reply_src = c.get("reply-src-address", "")
            reply_dst = c.get("reply-dst-address", "")

            orig_bytes = _parse_bytes(c.get("orig-bytes", c.get("orig_bytes", "0")))
            reply_bytes = _parse_bytes(c.get("repl-bytes", c.get("reply-bytes", "0")))
            total_bytes = orig_bytes + reply_bytes

            proto = c.get("protocol", c.get("proto", "tcp")).lower()
            state = c.get("tcp-state", c.get("state", "")).lower()

            entry = {
                **c,
                "_src": src,
                "_dst": dst,
                "_reply_src": reply_src,
                "_reply_dst": reply_dst,
                "_protocol": proto,
                "_state": state,
                "_orig_bytes": orig_bytes,
                "_reply_bytes": reply_bytes,
                "_total_bytes": total_bytes,
            }

            if search and search.lower() not in str(entry).lower():
                continue
            enriched.append(entry)

        # Sort by total bytes descending (top talkers)
        enriched.sort(key=lambda x: x["_total_bytes"], reverse=True)

        # Build top talkers from source IPs
        src_totals: dict = {}
        for c in enriched:
            src_ip = c["_src"].split(":")[0] if ":" in c["_src"] else c["_src"]
            if src_ip:
                src_totals[src_ip] = src_totals.get(src_ip, 0) + c["_total_bytes"]

        top_talkers = sorted(
            [{"ip": ip, "bytes": b} for ip, b in src_totals.items()],
            key=lambda x: x["bytes"],
            reverse=True
        )[:20]

        return {
            "connections": enriched[:top],
            "total": len(enriched),
            "top_talkers": top_talkers,
        }
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


# ── Firewall Rules ───────────────────────────────────────────

@router.get("/firewall/rules")
async def get_firewall_rules(device_id: str, chain_type: str = "filter", user=Depends(get_current_user)):
    """
    Get firewall rules with byte/packet counters.
    chain_type: filter | nat | mangle
    """
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt(device_id)

        if chain_type == "nat":
            rules = await mt.list_firewall_nat()
        elif chain_type == "mangle":
            rules = await mt.list_firewall_mangle()
        else:
            rules = await mt.list_firewall_filter()

        # Normalize and enrich
        result = []
        for r in rules:
            comment = r.get("comment", "")
            chain = r.get("chain", "")
            action = r.get("action", "")
            disabled = r.get("disabled", "false") == "true"

            bytes_val = _parse_bytes(r.get("bytes", "0"))
            packets_val = int(r.get("packets", "0") or "0")

            result.append({
                **r,
                "_comment": comment,
                "_chain": chain,
                "_action": action,
                "_disabled": disabled,
                "_bytes": bytes_val,
                "_packets": packets_val,
                "_is_drop": action in ("drop", "reject", "tarpit"),
                "_is_accept": action in ("accept", "passthrough"),
            })

        return result
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")
