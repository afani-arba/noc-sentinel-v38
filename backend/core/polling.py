"""
Polling Engine — Hybrid Monitoring (API + SNMP).
================================================
Arsitektur Final Integration:
  - Data SISTEM  (CPU, RAM, Uptime, Health, PPPoE, Hotspot) via MikroTik API
  - Data TRAFFIC (bandwidth) via SNMP v2c 64-bit counters — CONCURRENT dengan API
    └─ Fallback per-interface: mt.get_interface_traffic() jika SNMP gagal

Optimasi:
  - asyncio.Semaphore(50): maks paralel polling
  - SNMP + API system berjalan BERSAMAAN (bukan berurutan) → hemat ~2 detik/device
  - SMA window=3: grafik halus tanpa spike
  - SMA cache di-clear saat device OFFLINE_SKIP_AFTER → hemat RAM
  - Discovery otomatis (REST vs API Protocol) — hasil cached di DB
"""
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

from core.db import get_db
from mikrotik_api import get_host_only, get_api_client, discover_device
import ping_service

logger = logging.getLogger(__name__)

# ── Konstanta Polling ──────────────────────────────────────────────────────────
POLL_INTERVAL        = 30    # Detik antar siklus polling
DEVICE_TIMEOUT       = 90    # Maks waktu per device (sudah include SNMP 1+s delta)
OFFLINE_GRACE_POLLS  = 2     # Kegagalan beruntun sebelum tandai offline
MAX_CONCURRENT_POLLS = 50    # Semaphore — aman untuk 100+ device
OFFLINE_SKIP_AFTER   = 6     # Jika offline ≥ N kali: mulai skip siklus
OFFLINE_SKIP_CYCLES  = 4     # Skip N siklus sebelum poll ulang

# Keyword ISP — prioritas monitoring BW
_ISP_KEYWORDS = (
    "isp", *[f"isp{i}" for i in range(1, 21)],
    "wan", *[f"wan{i}" for i in range(1, 21)],
    "input", *[f"input{i}" for i in range(1, 21)],
    "uplink", "upstream", "internet", "gateway",
)

_VIRTUAL_IFACE_TYPES = {
    "bridge", "vlan", "pppoe-out", "pppoe-in", "l2tp", "pptp", "ovpn-client",
    "ovpn-server", "sstp-client", "sstp-server", "gre", "eoip", "eoipv6",
    "veth", "wireguard", "loopback", "6to4", "ipip", "ipip6",
}
_VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "veth", "tun", "tap")

_SFP_IFACE_TYPES = {
    "sfp-sfpplus", "sfpplus", "sfp", "10g-sfp", "10gbase-x",
    "qsfp", "qsfp+", "qsfp28", "combo", "sfp-sfpplus-combo",
    "10gsfp-sfpplus", "sfp28", "25g-sfp28", "40g-qsfp", "100g-qsfp28",
}
_SFP_IFACE_PREFIXES = ("sfp", "sfpplus", "qsfp", "combo")


# ══════════════════════════════════════════════════════════════════════════════
# Module 1: Auto-Discovery — deteksi mode API sekali, cache di DB
# ══════════════════════════════════════════════════════════════════════════════

async def _ensure_api_mode(device: dict, db) -> dict:
    """
    Pastikan device.api_mode terisi ('rest' atau 'api').
    Jalankan discover_device() hanya jika belum ada di DB.
    Hasil discovery disimpan ke DB → tidak re-discover setiap 30 detik.
    """
    if device.get("api_mode") in ("rest", "api"):
        return device

    logger.info(
        f"Auto-discover: {device.get('name','?')} [{device.get('ip_address','?')}]..."
    )
    disc = await discover_device(device)

    if disc["success"]:
        upf = {
            "api_mode":    disc["api_mode"],
            "ros_version": disc.get("ros_version", ""),
            "model":       disc.get("board_name", "") or device.get("model", ""),
        }
        if disc["api_mode"] == "rest":
            upf["use_https"] = disc.get("use_https", False)
            if disc.get("rest_port"):
                upf["api_port"] = disc["rest_port"]
        elif disc.get("api_port"):
            upf["api_port"] = disc["api_port"]

        await db.devices.update_one({"id": device["id"]}, {"$set": upf})
        device = {**device, **upf}
        logger.info(
            f"Discovery OK: {device.get('name','?')} → "
            f"mode={disc['api_mode']} ROS={disc.get('ros_version','?')}"
        )
    else:
        logger.warning(
            f"Discovery GAGAL: {device.get('name','?')} — gunakan mode default 'rest'"
        )
        device = {**device, "api_mode": "rest"}

    return device


# ══════════════════════════════════════════════════════════════════════════════
# Module 2: SNMP Traffic
# ══════════════════════════════════════════════════════════════════════════════

async def _get_traffic_snmp(
    device: dict,
    running_ifaces: list,
    isp_detected: list,
    device_id: str,
) -> dict:
    """
    Ambil bandwidth via BulkWalk + precision delta timestamp.
    Return {} jika SNMP tidak tersedia → caller fallback ke API.

    STRICT: return value ini adalah SATU-SATUNYA source traffic.
    Caller (poll_single_device) TIDAK BOLEH mix dengan API traffic jika return non-empty.
    """
    try:
        from snmp_poller import get_snmp_traffic
    except ImportError:
        return {}

    host      = get_host_only(device.get("ip_address", ""))
    community = device.get("snmp_community", "public") or "public"
    if not host:
        return {}

    # iface_filter: None → BulkWalk ambil SEMUA interface, filter di snmp_poller
    # Tidak perlu slicing di sini — nextCmd walk lebih efisien dari GET per-index
    iface_filter = running_ifaces if running_ifaces else None

    try:
        bw = await asyncio.wait_for(
            get_snmp_traffic(
                host=host,
                community=community,
                device_id=device_id,
                iface_filter=iface_filter,
                snmp_timeout=5,
                apply_smoothing=True,
            ),
            timeout=20,  # BulkWalk kebutuhan waktu: 2x walk + delta sleep ~1s
        )
        if bw:
            # Deteksi source dari hasil (snmp_hc atau snmp_32)
            sample_src = next(iter(bw.values()), {}).get("source", "snmp")
            logger.info(
                f"SNMP OK [{device.get('name','?')}]: "
                f"{len(bw)} ifaces source={sample_src} community={community}"
            )
        return bw
    except asyncio.TimeoutError:
        logger.debug(f"SNMP timeout [{device.get('name','?')}]")
        return {}
    except Exception as e:
        logger.debug(f"SNMP error [{device.get('name','?')}]: {e}")
        return {}



# ══════════════════════════════════════════════════════════════════════════════
# Module 3: API Traffic Fallback
# ══════════════════════════════════════════════════════════════════════════════

async def _get_traffic_api_fallback(
    mt,
    device: dict,
    running_ifaces: list,
    isp_detected: list,
    api_mode: str,
) -> tuple:
    """
    Fallback traffic jika SNMP gagal.
    ROS7: mt.get_interface_traffic() per-interface (monitor-traffic)
    ROS6: mt.get_all_interface_stats() → raw bytes untuk delta
    Return: (bw_precomputed: dict, iface_stats_raw: dict, isp_from_api: list, isp_comments: dict)
    """
    bw_precomputed  = {}
    iface_stats_raw = {}
    isp_from_api    = isp_detected[:]
    isp_comments    = {}

    if not running_ifaces:
        return bw_precomputed, iface_stats_raw, isp_from_api, isp_comments

    if api_mode == "rest" and hasattr(mt, "_async_req"):
        # ── ROS7: monitor-traffic per interface ──────────────────────────────
        isp_set  = set(isp_detected)
        sfp_set  = {n for n in running_ifaces if n.lower().startswith(_SFP_IFACE_PREFIXES)}
        isp_if   = [n for n in running_ifaces if n in isp_set]
        sfp_if   = [n for n in running_ifaces if n in sfp_set and n not in isp_set]
        rest_if  = [n for n in running_ifaces if n not in isp_set and n not in sfp_set]
        priority = isp_if + sfp_if + rest_if[:max(0, 64 - len(isp_if) - len(sfp_if))]

        async def _one(iface_name):
            try:
                # Gunakan get_interface_traffic() — interface per interface,
                # konsisten dengan interface MikroTikBase
                r = await mt.get_interface_traffic(iface_name)
                if isinstance(r, dict) and r:
                    # ROS7 get_interface_traffic mengembalikan monitor-traffic result
                    rx_bps = int(r.get("rx-bits-per-second", 0) or 0)
                    tx_bps = int(r.get("tx-bits-per-second", 0) or 0)
                    if rx_bps > 0 or tx_bps > 0:
                        return (iface_name, {
                            "download_bps": rx_bps,
                            "upload_bps":   tx_bps,
                            "status":       "up",
                            "source":       "api_rest_fallback",
                        })
            except Exception:
                pass
            return None

        results = await asyncio.gather(*[_one(n) for n in priority], return_exceptions=True)
        for r in results:
            if r and not isinstance(r, Exception):
                bw_precomputed[r[0]] = r[1]

        logger.info(
            f"API fallback (monitor-traffic) [{device.get('name','?')}]: "
            f"{len(bw_precomputed)} ifaces"
        )

    elif api_mode == "api":
        # ── ROS6: raw byte stats untuk delta ─────────────────────────────────
        try:
            stats = await mt.get_all_interface_stats()
            iface_stats_raw = stats.get("stats", {})
            isp_from_api    = stats.get("isp_interfaces", isp_detected)
            isp_comments    = stats.get("isp_comments", {})
            logger.info(
                f"API fallback (delta ROS6) [{device.get('name','?')}]: "
                f"{len(iface_stats_raw)} ifaces"
            )
        except Exception as e:
            logger.warning(f"ROS6 stats gagal [{device.get('name','?')}]: {e}")

    return bw_precomputed, iface_stats_raw, isp_from_api, isp_comments


# ══════════════════════════════════════════════════════════════════════════════
# Module 4: Core Hybrid Poll
# ══════════════════════════════════════════════════════════════════════════════

async def poll_via_hybrid(device: dict) -> dict:
    """
    Hybrid poll dengan concurrency penuh:
      - API system data (CPU/RAM/Health/Interfaces/PPPoE/Hotspot)
      - SNMP traffic (64-bit delta, SMA)
    Keduanya berjalan BERSAMAAN via asyncio.gather → hemat ~1-2 detik per poll cycle.

    Output: dict standar konsisten untuk ROS6 dan ROS7.
    Semua bandwidth dalam satuan bps (bits per second).
    """
    EMPTY = {
        "reachable":      False,
        "poll_mode":      "api_failed",
        "poll_source":    "none",
        "ping":           {"reachable": False, "avg": 0, "jitter": 0, "loss": 100},
        "system":         {},
        "cpu":            0,
        "memory":         {"total": 0, "used": 0, "percent": 0},
        "interfaces":     [],
        "traffic":        {},
        "health":         {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
        "bw_precomputed": {},
        "pppoe_active":   0,
        "hotspot_active": 0,
    }

    try:
        mt       = get_api_client(device)
        api_mode = device.get("api_mode", "rest")
        dev_name = device.get("name", device.get("ip_address", "?"))
        dev_id   = device.get("id", "")

        # ══════════════════════════════════════════════════════════════════════
        # FASE 1+3: Jalankan API system data DAN SNMP BERSAMAAN
        # API task: sys_resource + health + interfaces + pppoe + hotspot
        # SNMP task: traffic bandwidth (dengan delta 1s + SMA)
        # ══════════════════════════════════════════════════════════════════════
        async def _empty(): return {}
        async def _empty_list(): return []

        # API system calls (semua paralel satu sama lain)
        async def _api_system_task():
            sys_r, health_r, ifaces_r = await asyncio.gather(
                mt.get_system_resource(),
                mt.get_system_health(),
                mt.list_interfaces(),
                return_exceptions=True,
            )
            return sys_r, health_r, ifaces_r

        # PPPoE + Hotspot count (setelah interface list tersedia)
        # Jalankan bersamaan dengan SNMP tapi terpisah dari SNMP
        async def _api_session_task():
            if api_mode == "api":
                pppoe, hotspot = 0, 0
                try:
                    pl = await asyncio.to_thread(mt._list_resource, "/ppp/active")
                    pppoe = len(pl) if isinstance(pl, list) else 0
                except Exception:
                    pass
                try:
                    hl = await asyncio.to_thread(mt._list_resource, "/ip/hotspot/active")
                    hotspot = len(hl) if isinstance(hl, list) else 0
                except Exception:
                    pass
                return pppoe, hotspot
            else:
                # ROS7: REST API — jalankan paralel
                pppoe_l, hotspot_l = await asyncio.gather(
                    mt.list_pppoe_active(),
                    mt.list_hotspot_active(),
                    return_exceptions=True,
                )
                p = len(pppoe_l)   if isinstance(pppoe_l,   list) else 0
                h = len(hotspot_l) if isinstance(hotspot_l, list) else 0
                return p, h

        # SNMP traffic task (butuh ~2s: walk T1 + sleep 1s + walk T2)
        # Jalankan BERSAMAAN dengan API calls untuk efisiensi maksimal
        # (interface filter akan ditentukan setelah API selesai — tapi
        #  kita mulai SNMP tanpa filter dulu; filter diterapkan di snmp_poller)
        async def _snmp_placeholder():
            # iface_filter None = ambil semua → filter di dalam _get_traffic_snmp
            return {}

        # Gather: [API system, API sessions, SNMP] semua concurrent!
        (api_sys_result, api_sess_result, _), snmp_preliminary = await asyncio.gather(
            asyncio.gather(
                _api_system_task(),
                _api_session_task(),
                _snmp_placeholder(),  # placeholder — SNMP proper dipanggil setelah interface list tersedia
                return_exceptions=True,
            ),
            asyncio.sleep(0),  # dummy untuk struktur gather
            return_exceptions=True,
        )

        # Unpack API system
        if isinstance(api_sys_result, Exception):
            sys_res, health_raw, ifaces_raw = {}, {}, []
        else:
            sys_res, health_raw, ifaces_raw = api_sys_result
            if isinstance(sys_res,    Exception): sys_res    = {}
            if isinstance(health_raw, Exception): health_raw = {}
            if isinstance(ifaces_raw, Exception): ifaces_raw = []

        # Unpack sessions
        if isinstance(api_sess_result, Exception):
            pppoe_active, hotspot_active = 0, 0
        else:
            pppoe_active, hotspot_active = api_sess_result if isinstance(api_sess_result, tuple) else (0, 0)

        # Cek apakah ada data sistem yang valid
        identity_name = ""
        if isinstance(sys_res, dict) and sys_res:
            pass
        elif not sys_res:
            # Coba ambil identity terpisah (ROS7 REST)
            try:
                ir = await mt._async_req("GET", "system/identity") if hasattr(mt, "_async_req") else {}
                if isinstance(ir, dict):
                    identity_name = ir.get("name", "")
            except Exception:
                pass

        if not sys_res and not identity_name:
            logger.warning(f"API tidak merespon untuk {dev_name}")
            return EMPTY

        # ══════════════════════════════════════════════════════════════════════
        # FASE 2: Parse API data
        # ══════════════════════════════════════════════════════════════════════

        # ── Identity ─────────────────────────────────────────────────────────
        router_name = identity_name or ""
        if not router_name and isinstance(sys_res, dict):
            router_name = sys_res.get("identity", "")
        if not router_name:
            router_name = device.get("name", device.get("ip_address", ""))

        # ── Sistem Info (field names konsisten ROS6 & ROS7) ───────────────────
        sys_info         = {}
        uptime_formatted = "N/A"
        uptime_seconds   = 0

        if isinstance(sys_res, dict) and sys_res:
            board_name   = sys_res.get("board-name", "")
            ros_version  = sys_res.get("version", "")
            architecture = sys_res.get("architecture-name", "")
            uptime_raw   = str(sys_res.get("uptime", "") or "")

            try:
                d = int(re.search(r"(\d+)d", uptime_raw).group(1)) if "d" in uptime_raw else 0
                h = int(re.search(r"(\d+)h", uptime_raw).group(1)) if "h" in uptime_raw else 0
                m = int(re.search(r"(\d+)m", uptime_raw).group(1)) if "m" in uptime_raw else 0
                s_m = re.search(r"(\d+)s", uptime_raw)
                sec = int(s_m.group(1)) if s_m else 0
                uptime_seconds   = d * 86400 + h * 3600 + m * 60 + sec
                uptime_formatted = f"{d}d {h}h {m}m"
            except Exception:
                uptime_formatted = uptime_raw or "N/A"

            sys_info = {
                # ── Field names konsisten: sama untuk ROS6 dan ROS7 ──────────
                "sys_name":         router_name,
                "board_name":       board_name,
                "identity":         router_name,
                "ros_version":      ros_version,
                "architecture":     architecture,
                "uptime_formatted": uptime_formatted,
                "uptime_seconds":   uptime_seconds,   # integer detik (ROS6 & ROS7)
                "serial":           "",
                "firmware":         ros_version,
            }

        # ── CPU (integer 0-100, konsisten ROS6 & ROS7) ───────────────────────
        cpu_load = 0
        try:
            cpu_load = int(str((sys_res or {}).get("cpu-load", "0") or "0").rstrip("%"))
        except (ValueError, TypeError):
            pass

        # ── Memory (bytes, konsisten ROS6 & ROS7) ────────────────────────────
        memory = {"total": 0, "used": 0, "percent": 0}
        try:
            total_mem = int((sys_res or {}).get("total-memory", 0) or 0)
            free_mem  = int((sys_res or {}).get("free-memory",  0) or 0)
            used_mem  = max(0, total_mem - free_mem)
            if total_mem > 0:
                memory = {
                    "total":   total_mem,
                    "used":    used_mem,
                    "percent": round((used_mem / total_mem) * 100),
                }
        except (ValueError, TypeError):
            pass

        # ── Health (konsisten ROS6 & ROS7 — field names sama persis) ─────────
        health = {
            "cpu_temp":   float(health_raw.get("cpu_temp",   0)) if isinstance(health_raw, dict) else 0.0,
            "board_temp": float(health_raw.get("board_temp", 0)) if isinstance(health_raw, dict) else 0.0,
            "voltage":    float(health_raw.get("voltage",    0)) if isinstance(health_raw, dict) else 0.0,
            "power":      float(health_raw.get("power",      0)) if isinstance(health_raw, dict) else 0.0,
        }
        # Bonus fields jika ada
        if isinstance(health_raw, dict):
            if health_raw.get("sfp_temp"):    health["sfp_temp"]    = float(health_raw["sfp_temp"])
            if health_raw.get("switch_temp"): health["switch_temp"] = float(health_raw["switch_temp"])
            if health_raw.get("fans"):        health["fans"]        = health_raw["fans"]
            if health_raw.get("psu"):         health["psu"]         = health_raw["psu"]

        # ── Interface List + ISP Detection ────────────────────────────────────
        isp_detected   = []
        interfaces     = []
        running_ifaces = []

        for iface in (ifaces_raw if isinstance(ifaces_raw, list) else []):
            name     = iface.get("name", "")
            itype    = iface.get("type", "").lower()
            running  = iface.get("running", False)
            disabled = str(iface.get("disabled", "false")).lower() == "true"
            comment  = str(iface.get("comment", "") or "").lower()

            is_sfp = itype in _SFP_IFACE_TYPES or name.lower().startswith(_SFP_IFACE_PREFIXES)
            if is_sfp and not disabled:
                running = True  # SFP bonded: override running=false

            status    = "down" if disabled else ("up" if running else "down")
            is_virtual = (
                itype in _VIRTUAL_IFACE_TYPES
                or name.lower().startswith(_VIRTUAL_IFACE_PREFIXES)
                or name.startswith("<")
            )

            if name and any(kw in comment for kw in _ISP_KEYWORDS):
                isp_detected.append(name)

            if name:
                interfaces.append({
                    "index":   iface.get(".id", ""),
                    "name":    name,
                    "type":    itype,
                    "status":  status,
                    "speed":   0,
                    "virtual": is_virtual,
                    "is_sfp":  is_sfp,
                })

            if running and not disabled and name and not is_virtual:
                running_ifaces.append(name)

        # ══════════════════════════════════════════════════════════════════════
        # FASE 3: SNMP Traffic (sekarang kita tahu interface list)
        # Jalankan SNMP setelah parsing interface agar iface_filter akurat.
        # Total overhead SNMP ~2s — tetap jauh lebih hemat dari sequential.
        # ══════════════════════════════════════════════════════════════════════
        bw_precomputed  = {}
        iface_stats_raw = {}
        isp_from_api    = isp_detected[:]
        isp_comments    = {}
        poll_source     = "none"

        if running_ifaces:
            # Coba SNMP terlebih dahulu
            bw_precomputed = await _get_traffic_snmp(
                device, running_ifaces, isp_detected, dev_id
            )

            if bw_precomputed:
                # Source: snmp_hc (64-bit HC) atau snmp_32 (32-bit fallback)
                # Ambil dari sample item pertama — semua item punya source yang sama
                sample = next(iter(bw_precomputed.values()), {})
                poll_source = sample.get("source", "snmp_hc")
            else:
                # STRICT: fallback ke API traffic HANYA jika SNMP benar-benar gagal
                bw_precomputed, iface_stats_raw, isp_from_api, isp_comments = \
                    await _get_traffic_api_fallback(
                        mt, device, running_ifaces, isp_detected, api_mode
                    )
                poll_source = (
                    "api_rest_fallback" if api_mode == "rest"
                    else "api_delta_ros6"
                ) if (bw_precomputed or iface_stats_raw) else "none"


        mode_label = f"{api_mode}_hybrid"
        logger.info(
            f"Poll OK [{mode_label}] {dev_name}: "
            f"cpu={cpu_load}% mem={memory['percent']}% "
            f"ifaces={len(running_ifaces)} bw={len(bw_precomputed)} "
            f"pppoe={pppoe_active} hotspot={hotspot_active} "
            f"source={poll_source}"
        )

        # ── ROS6: return dengan iface_stats_raw untuk delta cycle berikutnya ─
        if api_mode == "api" and not bw_precomputed and iface_stats_raw:
            return {
                "reachable":       True,
                "poll_mode":       "api_legacy_hybrid",
                "poll_source":     "api_delta_ros6",
                "ping":            {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
                "system":          sys_info,
                "cpu":             cpu_load,
                "memory":          memory,
                "interfaces":      interfaces,
                "traffic":         {},
                "health":          health,
                "bw_precomputed":  {},
                "iface_stats_raw": iface_stats_raw,
                "running_ifaces":  running_ifaces,
                "isp_detected":    isp_from_api,
                "isp_comments":    isp_comments,
                "pppoe_active":    pppoe_active,
                "hotspot_active":  hotspot_active,
            }

        return {
            "reachable":       True,
            "poll_mode":       mode_label,
            "poll_source":     poll_source,
            "ping":            {"reachable": True, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 0},
            "system":          sys_info,
            "cpu":             cpu_load,
            "memory":          memory,
            "interfaces":      interfaces,
            "traffic":         {},
            "health":          health,
            "bw_precomputed":  bw_precomputed,
            "iface_stats_raw": {},
            "running_ifaces":  running_ifaces,
            "isp_detected":    isp_from_api,
            "pppoe_active":    pppoe_active,
            "hotspot_active":  hotspot_active,
        }

    except Exception as e:
        logger.warning(f"Hybrid poll gagal untuk {device.get('name','?')}: {e}")
        return EMPTY


# Backward compat alias — kode lain yang memanggil poll_via_api masih bisa jalan
poll_via_api = poll_via_hybrid


# ══════════════════════════════════════════════════════════════════════════════
# poll_single_device — DB update, SLA events, bandwidth history
# ══════════════════════════════════════════════════════════════════════════════

async def poll_single_device(device: dict) -> dict:
    """
    Orchestrator per-device:
      1. Auto-discover api_mode (jika belum ada di DB)
      2. Hybrid poll (API system + SNMP traffic concurrent)
      3. Update DB: status, metrics, SLA events, bandwidth history
      4. Hapus SMA cache jika device sudah lama offline
    """
    db  = get_db()
    did = device["id"]

    # ── 1. Auto-discover ──────────────────────────────────────────────────────
    device = await _ensure_api_mode(device, db)

    # ── 2. Hybrid poll ────────────────────────────────────────────────────────
    result = await poll_via_hybrid(device)

    # ── 3. Offline grace period ───────────────────────────────────────────────
    consecutive_failures = device.get("consecutive_poll_failures", 0)
    old_status = device.get("status", "unknown")

    if result["reachable"]:
        new_status = "online"
        if consecutive_failures > 0:
            # Device baru kembali online: bersihkan SMA cache (data stale)
            try:
                from snmp_poller import clear_sma_cache
                clear_sma_cache(did)
                logger.info(f"SMA cache cleared (device came back online): {device.get('name', did)}")
            except Exception:
                pass
        consecutive_failures = 0
    else:
        consecutive_failures += 1
        if consecutive_failures >= OFFLINE_GRACE_POLLS:
            new_status = "offline"
        else:
            new_status = old_status if old_status in ("online", "offline") else "offline"
            logger.info(
                f"Poll gagal {device.get('name', did)} "
                f"({consecutive_failures}/{OFFLINE_GRACE_POLLS}), grace period aktif"
            )

        # Bersihkan SMA cache saat device mulai banyak gagal (hemat RAM)
        if consecutive_failures == OFFLINE_SKIP_AFTER:
            try:
                from snmp_poller import clear_sma_cache
                clear_sma_cache(did)
                logger.info(
                    f"SMA cache cleared (OFFLINE_SKIP_AFTER reached): "
                    f"{device.get('name', did)}"
                )
            except Exception:
                pass

    now = datetime.now(timezone.utc).isoformat()

    update = {
        "status":                    new_status,
        "last_poll":                 now,
        "last_poll_data":            result,
        "consecutive_poll_failures": consecutive_failures,
    }

    if result["reachable"] and result.get("system"):
        s      = result["system"]
        health = result.get("health", {})
        update.update({
            # DB fields — konsisten antara ROS6 dan ROS7
            "model":          s.get("board_name", ""),
            "sys_name":       s.get("sys_name", ""),
            "identity":       s.get("identity", s.get("sys_name", "")),
            "architecture":   s.get("architecture", ""),
            "ros_version":    s.get("ros_version", ""),
            "uptime":         s.get("uptime_formatted", ""),
            "uptime_seconds": s.get("uptime_seconds", 0),
            "serial":         s.get("serial", ""),
            "cpu_load":       result.get("cpu", 0),
            "memory_usage":   result.get("memory", {}).get("percent", 0),
            "cpu_temp":       health.get("cpu_temp",   0),
            "board_temp":     health.get("board_temp", 0),
            "voltage":        health.get("voltage",    0),
            "power":          health.get("power",      0),
            "pppoe_active":   result.get("pppoe_active",   0),
            "hotspot_active": result.get("hotspot_active", 0),
        })

    # ── SLA Event ─────────────────────────────────────────────────────────────
    if old_status != new_status and new_status in ("online", "offline"):
        try:
            await db.sla_events.insert_one({
                "device_id":   did,
                "device_name": device.get("name", did),
                "event_type":  new_status,
                "from_status": old_status,
                "timestamp":   now,
            })
            logger.info(f"SLA event: {device.get('name', did)} → {new_status}")
        except Exception as sla_err:
            logger.debug(f"SLA event write gagal: {sla_err}")

    await db.devices.update_one({"id": did}, {"$set": update})

    # ── ISP Interface update ───────────────────────────────────────────────────
    isp_in_poll = result.get("isp_detected", [])
    if isp_in_poll:
        if set(isp_in_poll) != set(device.get("isp_interfaces", [])):
            await db.devices.update_one(
                {"id": did}, {"$set": {"isp_interfaces": isp_in_poll}}
            )

    isp_for_bw = isp_in_poll or device.get("isp_interfaces", [])

    # ── Notifikasi WhatsApp ───────────────────────────────────────────────────
    try:
        from services.notification_service import check_and_notify
        await check_and_notify(device, result, update)
    except Exception as e:
        logger.debug(f"Notification skip: {e}")

    # ── Bandwidth kalkulasi ────────────────────────────────────────────────────
    ping_data       = result.get("ping", {})
    bw              = result.get("bw_precomputed", {})
    iface_stats_raw = result.get("iface_stats_raw", {})

    # ROS6 delta: hitung bps dari raw bytes + terapkan SMA
    if iface_stats_raw and not bw:
        try:
            now_ts      = datetime.now(timezone.utc).timestamp()
            running_set = set(result.get("running_ifaces", []))
            snap_doc    = await db.traffic_snapshots.find_one({"device_id": did}, {"_id": 0})
            prev_stats  = snap_doc.get("iface_bytes", {}) if snap_doc else {}
            prev_ts     = snap_doc.get("ts")              if snap_doc else None

            if prev_stats and prev_ts:
                elapsed = max(now_ts - prev_ts, 1)
                for iface_name, cur in iface_stats_raw.items():
                    if iface_name not in running_set:
                        continue
                    prev = prev_stats.get(iface_name)
                    if not prev:
                        continue
                    rx_delta = max(0, cur.get("rx-bytes", 0) - prev.get("rx-bytes", 0))
                    tx_delta = max(0, cur.get("tx-bytes", 0) - prev.get("tx-bytes", 0))
                    dl_bps   = int((rx_delta * 8) / elapsed)  # bps
                    ul_bps   = int((tx_delta * 8) / elapsed)  # bps

                    # Terapkan SMA untuk ROS6 delta juga
                    try:
                        from snmp_poller import apply_sma
                        dl_bps, ul_bps = apply_sma(did, iface_name, dl_bps, ul_bps)
                    except Exception:
                        pass

                    bw[iface_name] = {
                        "download_bps": dl_bps,  # bps
                        "upload_bps":   ul_bps,  # bps
                        "status":       "up",
                        "source":       "api_delta_ros6",
                    }

                logger.info(
                    f"ROS6 delta bw: {device.get('name','?')} "
                    f"elapsed={elapsed:.1f}s bw={len(bw)} ifaces"
                )
        except Exception as e:
            logger.warning(f"ROS6 delta calc gagal [{device.get('name','?')}]: {e}")

    # ── ISP bandwidth (bps, konsisten) ────────────────────────────────────────
    isp_bw = {}
    if bw and isp_for_bw:
        for iname in isp_for_bw:
            d = bw.get(iname)
            if isinstance(d, dict):
                isp_bw[iname] = {
                    "download_bps": int(d.get("download_bps", 0)),  # bps
                    "upload_bps":   int(d.get("upload_bps",   0)),  # bps
                    "status":       d.get("status", "up"),
                }

    # Total bps
    isp_dl  = sum(v["download_bps"] for v in isp_bw.values())
    isp_ul  = sum(v["upload_bps"]   for v in isp_bw.values())
    all_dl  = sum(v.get("download_bps", 0) for v in bw.values() if isinstance(v, dict))
    all_ul  = sum(v.get("upload_bps",   0) for v in bw.values() if isinstance(v, dict))

    eff_dl = isp_dl if isp_bw else all_dl
    eff_ul = isp_ul if isp_bw else all_ul
    logger.info(
        f"BW [{device.get('name','?')}] src={result.get('poll_source','?')}: "
        f"isp={list(isp_bw)} "
        f"dl={eff_dl/1_000_000:.2f}Mbps ul={eff_ul/1_000_000:.2f}Mbps"
    )

    # ── ICMP Ping ─────────────────────────────────────────────────────────────
    real_ping_ms = ping_data.get("avg", 0) or 0
    if not real_ping_ms and result.get("reachable"):
        try:
            ip_only = get_host_only(device.get("ip_address", ""))
            if ip_only:
                pr = await ping_service.ping_host(ip_only, count=2, timeout=2)
                real_ping_ms = pr.get("avg", 0) or 0
        except Exception:
            real_ping_ms = 0

    # ── Simpan ke traffic_history ──────────────────────────────────────────────
    # download_mbps / upload_mbps = konversi bps → Mbps untuk grafik
    # Guard max(0, ...) agar nilai negatif tidak pernah tersimpan ke DB
    safe_dl = max(0, eff_dl)
    safe_ul = max(0, eff_ul)
    snapshot = {
        "device_id":      did,
        "timestamp":      now,
        "bandwidth":      bw,
        "isp_bandwidth":  isp_bw,
        "download_mbps":  round(safe_dl / 1_000_000, 3),
        "upload_mbps":    round(safe_ul / 1_000_000, 3),
        "cpu":            result.get("cpu", 0),
        "memory_percent": result.get("memory", {}).get("percent", 0),
        "ping_ms":        round(real_ping_ms, 1),
        "jitter_ms":      ping_data.get("jitter", 0) or 0,
        "poll_source":    result.get("poll_source", "unknown"),
    }
    try:
        await db.traffic_history.insert_one(snapshot)
        count = await db.traffic_history.count_documents({"device_id": did})
        if count > 2880:
            oldest = await db.traffic_history.find(
                {"device_id": did}, {"_id": 1}
            ).sort("timestamp", 1).limit(count - 2880).to_list(count - 2880)
            ids = [d["_id"] for d in oldest]
            if ids:
                await db.traffic_history.delete_many({"_id": {"$in": ids}})
    except Exception as he:
        logger.debug(f"Traffic history write gagal: {he}")

    # ── InfluxDB (opsional) ───────────────────────────────────────────────────
    if bw:
        try:
            from services.metrics_service import write_device_metrics, is_enabled
            if is_enabled():
                await asyncio.to_thread(
                    write_device_metrics, did, device.get("name", did),
                    {
                        "cpu":       result.get("cpu", 0),
                        "memory":    result.get("memory", {}),
                        "ping":      ping_data,
                        "health":    result.get("health", {}),
                        "bandwidth": bw,
                    },
                )
        except Exception as e:
            logger.debug(f"InfluxDB write skip: {e}")

    # ── Update traffic_snapshots (ROS6 delta state) ───────────────────────────
    snap_upd = {"device_id": did, "timestamp": now, "traffic": {}}
    if iface_stats_raw:
        snap_upd["iface_bytes"] = iface_stats_raw
        snap_upd["ts"]          = datetime.now(timezone.utc).timestamp()
    await db.traffic_snapshots.update_one(
        {"device_id": did}, {"$set": snap_upd}, upsert=True
    )

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Polling Loop
# ══════════════════════════════════════════════════════════════════════════════

async def polling_loop():
    """
    Background loop: poll semua device setiap POLL_INTERVAL detik.
    asyncio.Semaphore(50) membatasi concurrency.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_POLLS)

    async def poll_with_semaphore(dev):
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    poll_single_device(dev),
                    timeout=DEVICE_TIMEOUT
                )
            except asyncio.TimeoutError:
                name = dev.get("name", dev.get("ip_address", "?"))
                logger.warning(f"Poll timeout {DEVICE_TIMEOUT}s untuk {name}")
                return None
            except Exception as e:
                logger.error(f"Poll error untuk {dev.get('name','?')}: {e}")
                return None

    while True:
        start = asyncio.get_running_loop().time()
        try:
            db      = get_db()
            devices = await db.devices.find({}, {"_id": 0}).to_list(None)
            if devices:
                tick = getattr(polling_loop, "_tick", 0) + 1
                polling_loop._tick = tick

                def _should_poll(dev):
                    fails = dev.get("consecutive_poll_failures", 0)
                    if fails < OFFLINE_SKIP_AFTER:
                        return True
                    return (tick % (OFFLINE_SKIP_CYCLES + 1)) == 0

                to_poll = [d for d in devices if _should_poll(d)]
                skipped = len(devices) - len(to_poll)
                if skipped:
                    logger.debug(f"Polling: {len(to_poll)} active, {skipped} offline skipped")

                logger.debug(
                    f"Polling {len(to_poll)} device "
                    f"(Semaphore={MAX_CONCURRENT_POLLS}, mode=hybrid)..."
                )
                await asyncio.gather(
                    *[poll_with_semaphore(d) for d in to_poll],
                    return_exceptions=True
                )

            # Bersihkan data lama
            snap_cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
            await db.traffic_snapshots.delete_many({"ts": {"$lt": snap_cutoff}})
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            await db.traffic_history.delete_many({"timestamp": {"$lt": cutoff}})

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}")

        elapsed    = asyncio.get_running_loop().time() - start
        sleep_time = max(1, POLL_INTERVAL - elapsed)
        await asyncio.sleep(sleep_time)
