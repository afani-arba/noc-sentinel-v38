"""
BGP & OSPF Routing router: monitor BGP peers, OSPF neighbors, IP routes.
ROS 7.x REST API field mapping:
  BGP connection: name, remote.as, remote.address, local.role, output.default-originate
  BGP session:    name, remote-as, remote-address, state, uptime, prefix-count, ...
  OSPF neighbor:  address, interface, state, priority, dr, bdr
  IP route:       dst-address, gateway, distance, scope, bgp, ospf, type, active
"""
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from core.db import get_db
from core.auth import get_current_user
from mikrotik_api import get_api_client

router = APIRouter(tags=["routing"])


async def _get_mt(device_id: str):
    db = get_db()
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device not found")
    return get_api_client(device), device


def _state_to_status(raw: str) -> str:
    """Normalize any BGP state string to standard label."""
    s = (raw or "").lower()
    if "established" in s:
        return "established"
    if "active" in s:
        return "active"
    if "idle" in s:
        return "idle"
    if "connect" in s:
        return "connect"
    if "opensent" in s or "openconfirm" in s:
        return "opening"
    return s or "unknown"


def _normalize_bgp_peer(p: dict, sessions: list) -> dict:
    """
    Merge BGP connection + session for ROS 6.x and ROS 7.x.

    ROS 7.x /routing/bgp/connection:
      name="Peer-PGN"  remote.address=103.28.104.208/31  remote.as=56258

    ROS 7.x /routing/bgp/session:
      name="Peer-PGN-1"  (suffix -1 added!)  remote.address=103.28.104.208 (no CIDR)

    ROS 6.x /routing/bgp/peer:
      name, remote-as, remote-address, state, uptime
    """
    import re

    name = p.get("name") or p.get("instance") or p.get(".id", "")

    # Remote AS: ROS 7 connection = "remote.as", session/ROS6 = "remote-as"
    remote_as = (
        p.get("remote.as") or p.get("remote-as") or p.get("remote_as") or ""
    )

    # Remote Address: strip CIDR if present (connection has /31, session doesn't)
    raw_addr = p.get("remote.address") or p.get("remote-address") or p.get("address") or ""
    remote_addr = raw_addr.split("/")[0] if "/" in raw_addr else raw_addr

    def _ip(addr: str) -> str:
        return (addr or "").split("/")[0].strip()

    # Match session: by IP first (most reliable), then exact name, then strip -N suffix
    matched_session = None
    for s in sessions:
        s_addr = _ip(s.get("remote.address") or s.get("remote-address") or "")
        s_name = s.get("name", "")

        if remote_addr and s_addr == remote_addr:
            matched_session = s
            break
        if s_name == name:
            matched_session = s
            break
        # ROS 7 adds "-1"/"-2" suffix: "Peer-PGN-1" -> "Peer-PGN"
        if re.sub(r"-\d+$", "", s_name) == name:
            matched_session = s
            break

    if matched_session:
        raw_state = matched_session.get("state") or matched_session.get("status") or ""
        # ROS 7 sessions use flag "E" for established (no state field)
        if not raw_state:
            flags = str(matched_session.get("flags", "") or matched_session.get(".flags", ""))
            if "E" in flags or "established" in flags.lower():
                raw_state = "established"
        uptime = matched_session.get("uptime", "")
        prefix_count = matched_session.get("prefix-count", matched_session.get("prefix_count", ""))
        if not remote_as:
            remote_as = (matched_session.get("remote.as") or
                         matched_session.get("remote-as") or
                         matched_session.get("remote_as") or "")
        if not remote_addr:
            remote_addr = _ip(matched_session.get("remote.address") or
                              matched_session.get("remote-address") or "")
    else:
        raw_state = p.get("state") or p.get("established") or p.get("status") or ""
        uptime = p.get("uptime", "")
        prefix_count = p.get("prefix-count", p.get("prefix_count", ""))

    status = _state_to_status(raw_state)

    return {
        **p,
        "name": name,
        "remote-as": str(remote_as),
        "remote-address": remote_addr,
        "uptime": uptime,
        "prefix-count": prefix_count,
        "_status": status,
        "_is_up": status == "established",
    }


# ── BGP ──────────────────────────────────────────────────────

@router.get("/routing/bgp")
async def get_bgp(device_id: str, user=Depends(get_current_user)):
    """Get BGP peers + sessions status from MikroTik (ROS 6 & ROS 7 compatible)."""
    if not device_id:
        return {"peers": [], "sessions": []}
    try:
        mt, _ = await _get_mt(device_id)
        peers, sessions = await asyncio.gather(
            mt.list_bgp_peers(),
            mt.list_bgp_sessions(),
            return_exceptions=True,
        )
        peers = peers if isinstance(peers, list) else []
        sessions = sessions if isinstance(sessions, list) else []

        normalized_peers = [_normalize_bgp_peer(p, sessions) for p in peers]

        return {"peers": normalized_peers, "sessions": sessions}
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


# ── OSPF ─────────────────────────────────────────────────────

@router.get("/routing/ospf")
async def get_ospf(device_id: str, user=Depends(get_current_user)):
    """Get OSPF neighbors and instances from MikroTik."""
    if not device_id:
        return {"neighbors": [], "instances": []}
    try:
        mt, _ = await _get_mt(device_id)
        neighbors, instances = await asyncio.gather(
            mt.list_ospf_neighbors(),
            mt.list_ospf_instances(),
            return_exceptions=True,
        )
        neighbors = neighbors if isinstance(neighbors, list) else []
        instances = instances if isinstance(instances, list) else []

        normalized = []
        for n in neighbors:
            state = (n.get("state") or n.get("status") or "").lower()
            is_full = "full" in state
            normalized.append({**n, "_state": state, "_is_full": is_full})

        return {"neighbors": normalized, "instances": instances}
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")


# ── IP Routes ────────────────────────────────────────────────

@router.get("/routing/routes")
async def get_routes(device_id: str, search: str = "", limit: int = 100, user=Depends(get_current_user)):
    """Get IP routing table from MikroTik (ROS 6 & ROS 7 compatible)."""
    if not device_id:
        return []
    try:
        mt, _ = await _get_mt(device_id)
        routes = await mt.list_ip_routes(limit=limit)

        result = []
        for r in routes:
            # ── Protocol detection (ROS 7 vs ROS 6) ──────────
            # ROS 7: "bgp" key contains "true", "ospf" key, "static" key, "connected" key
            # ROS 6: "type" key or flags
            is_bgp = r.get("bgp") in ("true", True) or "bgp" in (r.get("routing-mark", "") or "").lower()
            is_ospf = r.get("ospf") in ("true", True)
            is_static = r.get("static") in ("true", True) or r.get("type") == "S"
            is_connected = r.get("connect") in ("true", True) or r.get("type") == "C"

            if is_bgp:
                proto = "bgp"
            elif is_ospf:
                proto = "ospf"
            elif is_connected:
                proto = "connected"
            elif is_static:
                proto = "static"
            else:
                proto = r.get("protocol", r.get("routing-mark", "unknown")) or "unknown"

            # ── Active detection ──────────────────────────────
            active_raw = r.get("active", r.get("dst-active", "false"))
            active = active_raw in ("true", True)

            # ── Destination & Gateway ─────────────────────────
            dst = r.get("dst-address") or r.get("dst_address") or ""
            gw = r.get("gateway") or r.get("nexthop") or ""

            entry = {
                **r,
                "_dst": dst,
                "_gateway": gw,
                "_protocol": proto,
                "_active": active,
                "_distance": r.get("distance", ""),
            }

            if search and search.lower() not in str(entry).lower():
                continue
            result.append(entry)

        return result
    except Exception as e:
        raise HTTPException(502, f"MikroTik API error: {e}")
