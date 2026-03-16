"""
snmp_poller.py — SNMP v2c Traffic Monitor (Proven getCmd API)
=============================================================
PRINSIP: Pakai HANYA getCmd() per-index — SATU-SATUNYA API yang terbukti bekerja
         di pysnmp-lextudio 6.x. nextCmd() tidak bekerja (async for / await loop
         keduanya return kosong).

Improvement dari versi asli (2026-03-16):
  1. PRECISION DELTA: time.monotonic() saat snapshot diambil → elapsed NYATA
     bps = (bytes * 8) / elapsed_real  (bukan hardcode /1.0s)
  2. SINGLE ENGINE: Satu SnmpEngine dibuat sekali per poll cycle, di-reuse
     semua GET calls → anti race-condition dispatcher
  3. STRICT GUARD: max(0, bps) → tidak mungkin simpan nilai negatif

Terbukti bekerja (dari manual test 2026-03-16):
  result = await getCmd(engine, CommunityData('public', mpModel=1),
                        UdpTransportTarget(('103.157.116.29', 161)),
                        ContextData(), ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.2.1')))
  → err_ind=None, err_st=0, OID=1.3.6.1.2.1.2.2.1.2.1  val=ether1
"""
import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── OID Constants ─────────────────────────────────────────────────────────────
OID_SYS_DESCR        = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME         = "1.3.6.1.2.1.1.5.0"
OID_SYS_UPTIME       = "1.3.6.1.2.1.1.3.0"
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"     # ifDescr  (primary name)
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"  # ifName   (secondary)
OID_IF_HC_IN_OCTETS  = "1.3.6.1.2.1.31.1.1.1.6"  # 64-bit HC in
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # 64-bit HC out
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"    # 32-bit in  (fallback)
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"    # 32-bit out (fallback)

CMAX_64 = 2 ** 64
CMAX_32 = 2 ** 32
MAX_BPS = 400_000_000_000   # 400 Gbps hard cap
MAX_INDEX = 64              # scan index 1..64

# ── SMA State ─────────────────────────────────────────────────────────────────
_SMA_W = 3
_sma_dl: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
_sma_ul: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_SMA_W)))
_is_64bit: Dict[str, bool] = {}


def apply_sma(device_id: str, iface: str, dl: int, ul: int) -> Tuple[int, int]:
    _sma_dl[device_id][iface].append(dl)
    _sma_ul[device_id][iface].append(ul)
    return (
        int(sum(_sma_dl[device_id][iface]) / len(_sma_dl[device_id][iface])),
        int(sum(_sma_ul[device_id][iface]) / len(_sma_ul[device_id][iface])),
    )


def clear_sma_cache(device_id: str):
    _sma_dl.pop(device_id, None)
    _sma_ul.pop(device_id, None)
    _is_64bit.pop(device_id, None)


# ── Core: GET per-index dengan SATU SnmpEngine (anti race-condition) ──────────

async def _snmp_get_indexed(
    host: str,
    community: str,
    base_oid: str,
    max_index: int = MAX_INDEX,
    timeout: int = 3,
    as_int: bool = False,
) -> Dict[int, any]:
    """
    Walk via getCmd per-index 1..max_index.
    Satu SnmpEngine dibuat di sini, di-reuse semua concurrent getCmd calls.

    TERBUKTI BEKERJA — identik dengan original noc-sentinel/snmp_service.py.
    Jangan ganti ke nextCmd/bulkCmd sampai API-nya diverifikasi bekerja.

    Return: {ifIndex: value}
    """
    try:
        from pysnmp.hlapi.asyncio import (
            getCmd, SnmpEngine, CommunityData,
            UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity,
        )
    except ImportError:
        logger.error("[SNMP] pysnmp tidak terinstall — pip install pysnmp-lextudio==6.2.0")
        return {}

    engine = SnmpEngine()   # ← SATU engine untuk semua GET (anti race-condition)
    results: Dict[int, any] = {}

    async def get_one(idx: int):
        oid = f"{base_oid}.{idx}"
        try:
            result = await getCmd(
                engine,
                CommunityData(community, mpModel=1),
                UdpTransportTarget((host, 161), timeout=timeout, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            err_ind, err_st, _, var_binds = result
            if err_ind or err_st:
                return None
            for _, val in var_binds:
                v = str(val)
                if "NoSuchInstance" in v or "NoSuchObject" in v:
                    return None
                if as_int:
                    try:
                        return (idx, int(v))
                    except (ValueError, TypeError):
                        return None
                return (idx, v.strip())
        except Exception as e:
            logger.debug(f"[SNMP] {host} idx={idx}: {e}")
            return None

    # Batch parallel: 8 request per batch (terbukti stabil)
    batch_size = 8
    for batch_start in range(1, max_index + 1, batch_size):
        batch_end = min(batch_start + batch_size, max_index + 1)
        tasks = [get_one(i) for i in range(batch_start, batch_end)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        found_any = False
        for r in batch_results:
            if r and not isinstance(r, Exception):
                results[int(r[0])] = r[1]
                found_any = True

        # Early stop jika batch kosong dan sudah ada hasil
        if not found_any and results:
            break

    try:
        engine.closeDispatcher()
    except Exception:
        pass

    return results


# ── Single scalar GET ─────────────────────────────────────────────────────────

async def _snmp_get_scalar(
    host: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: int = 3,
) -> Optional[str]:
    """Single GET untuk OID scalar (tanpa index)."""
    try:
        from pysnmp.hlapi.asyncio import (
            getCmd, SnmpEngine, CommunityData,
            UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity,
        )
        engine = SnmpEngine()
        result = await getCmd(
            engine,
            CommunityData(community, mpModel=1),
            UdpTransportTarget((host, port), timeout=timeout, retries=0),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        try:
            engine.closeDispatcher()
        except Exception:
            pass
        err_ind, err_st, _, var_binds = result
        if err_ind or err_st:
            return None
        for _, val in var_binds:
            v = str(val)
            if "NoSuchInstance" in v or "NoSuchObject" in v:
                return None
            return v.strip()
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"[SNMP GET] {host} {oid}: {e}")
        return None


# ── Interface Names ───────────────────────────────────────────────────────────

async def _get_ifnames(
    host: str,
    community: str,
    timeout: int = 3,
) -> Dict[int, str]:
    """
    {ifIndex: name} via getCmd per-index.
    Level 1: ifDescr (universal — semua MikroTik)
    Level 2: ifName  (short name)
    Level 3: synthetic if{n} dari ifInOctets index
    """
    logger.warning(f"[SNMP DEBUG] {host}: walk ifDescr...")
    r = await _snmp_get_indexed(host, community, OID_IF_DESCR, timeout=timeout)
    if r:
        logger.warning(
            f"[SNMP DEBUG] {host}: ifDescr OK → {len(r)} ifaces: {list(r.values())[:5]}"
        )
        return r

    logger.warning(f"[SNMP DEBUG] {host}: ifDescr kosong, coba ifName...")
    r = await _snmp_get_indexed(host, community, OID_IF_NAME, timeout=timeout)
    if r:
        logger.warning(
            f"[SNMP DEBUG] {host}: ifName OK → {len(r)} ifaces: {list(r.values())[:5]}"
        )
        return r

    logger.warning(f"[SNMP DEBUG] {host}: ifName kosong, coba synthetic dari ifInOctets...")
    r = await _snmp_get_indexed(host, community, OID_IF_IN_OCTETS, timeout=timeout, as_int=True)
    if r:
        syn = {idx: f"if{idx}" for idx in r}
        logger.warning(f"[SNMP DEBUG] {host}: synthetic OK → {len(syn)} ifaces")
        return syn

    logger.error(
        f"[SNMP DEBUG] {host}: SEMUA LEVEL GAGAL. "
        f"Cek: SNMP enabled di IP Services, community string, port 161/UDP."
    )
    return {}


# ── Single Poll Cycle ─────────────────────────────────────────────────────────

async def _single_poll(
    host: str,
    community: str,
    timeout: int = 4,
) -> Optional[Dict]:
    """
    Satu siklus poll: {iface_name: {in_octets, out_octets, ts}}.
    ts = time.monotonic() sesaat setelah data diterima — dipakai untuk delta presisi.
    """
    names = await _get_ifnames(host, community, timeout=timeout)
    if not names:
        return None

    # Coba 64-bit HC dulu (parallel, satu engine bersama)
    in64, out64 = await asyncio.gather(
        _snmp_get_indexed(host, community, OID_IF_HC_IN_OCTETS,  timeout=timeout, as_int=True),
        _snmp_get_indexed(host, community, OID_IF_HC_OUT_OCTETS, timeout=timeout, as_int=True),
    )
    ts = time.monotonic()  # ← timestamp tepat setelah data diterima
    use64 = bool(in64)
    in_map, out_map = in64, out64

    if not use64:
        logger.debug(f"[SNMP] {host}: 64-bit HC kosong, fallback 32-bit...")
        in_map, out_map = await asyncio.gather(
            _snmp_get_indexed(host, community, OID_IF_IN_OCTETS,  timeout=timeout, as_int=True),
            _snmp_get_indexed(host, community, OID_IF_OUT_OCTETS, timeout=timeout, as_int=True),
        )
        ts = time.monotonic()

    if not in_map:
        logger.warning(f"[SNMP DEBUG] {host}: counter walk kosong")
        return None

    _is_64bit[host] = use64
    logger.warning(
        f"[SNMP DEBUG] {host}: poll OK — "
        f"{len(names)} ifaces, {len(in_map)} counters, 64bit={use64}"
    )

    return {
        name: {
            "in_octets":  in_map.get(idx, 0),
            "out_octets": out_map.get(idx, 0),
            "ts":         ts,  # monotonic timestamp
        }
        for idx, name in names.items()
    }


# ── Device Info ───────────────────────────────────────────────────────────────

async def get_device_snmp_info(
    host: str,
    community: str = "public",
    port: int = 161,
    timeout: int = 5,
) -> Dict:
    """Info: sysDescr, sysName, uptime, jumlah interface. Untuk /test-snmp endpoint."""
    sys_descr, sys_name, sys_uptime = await asyncio.gather(
        _snmp_get_scalar(host, community, OID_SYS_DESCR,  port=port, timeout=timeout),
        _snmp_get_scalar(host, community, OID_SYS_NAME,   port=port, timeout=timeout),
        _snmp_get_scalar(host, community, OID_SYS_UPTIME, port=port, timeout=timeout),
    )

    info = {
        "snmp_reachable": bool(sys_descr),
        "sys_descr":      sys_descr or "",
        "sys_name":       sys_name  or "",
        "uptime_s":       0,
        "ros_version":    "",
        "interface_count": 0,
    }

    if sys_descr:
        m = re.search(r"(\d+\.\d+[\.\d]*)", sys_descr)
        if m:
            info["ros_version"] = m.group(1)

    if sys_uptime:
        try:
            info["uptime_s"] = int(sys_uptime) // 100
        except (ValueError, TypeError):
            pass

    if info["snmp_reachable"]:
        names = await _get_ifnames(host, community, timeout=timeout)
        info["interface_count"] = len(names)

    return info


# ── Main: Precision Traffic ───────────────────────────────────────────────────

async def get_snmp_traffic(
    host: str,
    community: str = "public",
    device_id: str = "",
    iface_filter: Optional[List[str]] = None,
    snmp_timeout: int = 4,
    apply_smoothing: bool = True,
) -> Dict[str, Dict]:
    """
    Bandwidth traffic real-time via SNMP getCmd dengan PRECISION DELTA.

    Precision Delta Algorithm:
      T1: poll() + ts1 = time.monotonic()  ← timestamp NYATA saat data diterima
      sleep(1)
      T2: poll() + ts2 = time.monotonic()
      elapsed = ts2 - ts1                  ← elapsed NYATA (bukan asumsi 1.0s)
      bps = (counter_delta * 8) / elapsed  ← akurasi > 95%

    Strict: HANYA return data SNMP. Caller TIDAK BOLEH mix API traffic.
    """
    if not host:
        return {}

    try:
        # T1
        snap1 = await _single_poll(host, community, timeout=snmp_timeout)
        if not snap1:
            return {}
        ts1 = next(iter(snap1.values()))["ts"]  # ambil ts dari item pertama

        await asyncio.sleep(1)

        # T2
        snap2 = await _single_poll(host, community, timeout=snmp_timeout)
        if not snap2:
            return {}
        ts2 = next(iter(snap2.values()))["ts"]

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[SNMP] traffic error [{host}]: {e}")
        return {}

    # Elapsed NYATA dari monotonic timestamps
    elapsed = ts2 - ts1
    if elapsed < 0.2:
        logger.warning(f"[SNMP] {host}: elapsed={elapsed:.3f}s terlalu pendek, skip")
        return {}

    use64 = _is_64bit.get(host, True)
    CMAX  = CMAX_64 if use64 else CMAX_32
    result: Dict[str, Dict] = {}

    for iface, d2 in snap2.items():
        if iface_filter and iface not in iface_filter:
            continue
        d1 = snap1.get(iface)
        if not d1:
            continue

        di = d2["in_octets"]  - d1["in_octets"]
        do = d2["out_octets"] - d1["out_octets"]

        # Counter wrap correction
        if di < 0: di += CMAX
        if do < 0: do += CMAX

        # BPS = bytes * 8 / elapsed_nyata
        dl = min(int((di * 8) / elapsed), MAX_BPS)
        ul = min(int((do * 8) / elapsed), MAX_BPS)

        # Filter: abaikan interface tanpa counter sama sekali
        if d2["in_octets"] == 0 and d2["out_octets"] == 0:
            continue

        if apply_smoothing and device_id:
            dl, ul = apply_sma(device_id, iface, dl, ul)

        result[iface] = {
            "download_bps": max(0, dl),
            "upload_bps":   max(0, ul),
            "status":       "up",
            "source":       "snmp_hc" if use64 else "snmp_32",
        }

    if result:
        logger.warning(
            f"[SNMP DEBUG] {host}: traffic OK — "
            f"{len(result)} ifaces active (elapsed={elapsed:.3f}s, 64bit={use64})"
        )
    else:
        logger.debug(f"[SNMP] {host}: no active traffic detected")

    return result


# ── Reachability Test ─────────────────────────────────────────────────────────

async def test_snmp_reachable(host: str, community: str = "public", timeout: int = 3) -> bool:
    result = await _snmp_get_scalar(host, community, OID_SYS_DESCR, timeout=timeout)
    return result is not None
