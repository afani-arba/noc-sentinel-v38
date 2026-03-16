"""
SNMP Service for MikroTik device monitoring.
Uses GET-based scanning instead of WALK for better compatibility.
"""
import asyncio
import subprocess
import re
import logging
from pysnmp.hlapi.asyncio import (
    getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity,
)

logger = logging.getLogger(__name__)

# Standard MIB-2 OIDs
OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'
OID_SYS_UPTIME = '1.3.6.1.2.1.1.3.0'
OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'
OID_IF_DESCR = '1.3.6.1.2.1.2.2.1.2'
OID_IF_SPEED = '1.3.6.1.2.1.2.2.1.5'
OID_IF_OPER_STATUS = '1.3.6.1.2.1.2.2.1.8'
OID_IF_IN_OCTETS = '1.3.6.1.2.1.2.2.1.10'
OID_IF_OUT_OCTETS = '1.3.6.1.2.1.2.2.1.16'
OID_IF_HC_IN_OCTETS = '1.3.6.1.2.1.31.1.1.1.6'
OID_IF_HC_OUT_OCTETS = '1.3.6.1.2.1.31.1.1.1.10'
OID_HR_PROCESSOR_LOAD = '1.3.6.1.2.1.25.3.3.1.2'
OID_HR_STORAGE_DESCR = '1.3.6.1.2.1.25.2.3.1.3'
OID_HR_STORAGE_UNITS = '1.3.6.1.2.1.25.2.3.1.4'
OID_HR_STORAGE_SIZE = '1.3.6.1.2.1.25.2.3.1.5'
OID_HR_STORAGE_USED = '1.3.6.1.2.1.25.2.3.1.6'
OID_MT_BOARD = '1.3.6.1.4.1.14988.1.1.7.3.0'
OID_MT_SERIAL = '1.3.6.1.4.1.14988.1.1.7.1.0'
OID_MT_FIRMWARE = '1.3.6.1.4.1.14988.1.1.7.4.0'

# MikroTik Specific OIDs for extended health monitoring
OID_MT_CPU_TEMP = '1.3.6.1.4.1.14988.1.1.3.10.0'  # CPU Temperature
OID_MT_BOARD_TEMP = '1.3.6.1.4.1.14988.1.1.3.11.0'  # Board Temperature
OID_MT_VOLTAGE = '1.3.6.1.4.1.14988.1.1.3.8.0'  # Voltage
OID_MT_CURRENT = '1.3.6.1.4.1.14988.1.1.3.9.0'  # Current (for power calculation)
OID_MT_POWER = '1.3.6.1.4.1.14988.1.1.3.12.0'  # Power consumption
OID_MT_ARCHITECTURE = '1.3.6.1.4.1.14988.1.1.4.4.0'  # Architecture
OID_MT_IDENTITY = '1.3.6.1.4.1.14988.1.1.4.3.0'  # Identity

# MikroTik specific memory OIDs
OID_MT_TOTAL_MEMORY = '1.3.6.1.4.1.14988.1.1.3.13.0'  # Total memory (bytes)
OID_MT_FREE_MEMORY = '1.3.6.1.2.1.25.2.3.1.6.65536'  # Free memory index 65536 (MikroTik specific)
OID_MT_TOTAL_HDD = '1.3.6.1.4.1.14988.1.1.3.14.0'  # Total HDD space


async def snmp_get(host, port, community, oid, timeout=4, retries=1):
    try:
        engine = SnmpEngine()
        result = await getCmd(
            engine, CommunityData(community),
            UdpTransportTarget((host, port), timeout=timeout, retries=retries),
            ContextData(), ObjectType(ObjectIdentity(oid)),
        )
        errorIndication, errorStatus, _, varBinds = result
        engine.closeDispatcher()
        if errorIndication or errorStatus:
            return None
        for varBind in varBinds:
            val = str(varBind[1])
            if 'NoSuchInstance' in val or 'NoSuchObject' in val:
                return None
            return val
    except Exception as e:
        logger.debug(f"SNMP GET {host} {oid}: {e}")
        return None


async def snmp_get_indexed(host, port, community, base_oid, max_index=64, timeout=3, retries=1):
    """Get OID values by index (1 to max_index) - more reliable than WALK for some devices."""
    results = {}
    engine = SnmpEngine()
    
    async def get_one(idx):
        oid = f"{base_oid}.{idx}"
        try:
            result = await getCmd(
                engine, CommunityData(community),
                UdpTransportTarget((host, port), timeout=timeout, retries=retries),
                ContextData(), ObjectType(ObjectIdentity(oid)),
            )
            errorIndication, errorStatus, _, varBinds = result
            if errorIndication or errorStatus:
                return None
            for varBind in varBinds:
                val = str(varBind[1])
                if 'NoSuchInstance' in val or 'NoSuchObject' in val:
                    return None
                return (str(idx), val)
        except Exception:
            return None
    
    # Query in batches for better performance
    batch_size = 8
    for batch_start in range(1, max_index + 1, batch_size):
        batch_end = min(batch_start + batch_size, max_index + 1)
        tasks = [get_one(i) for i in range(batch_start, batch_end)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        found_any = False
        for r in batch_results:
            if r and not isinstance(r, Exception):
                results[r[0]] = r[1]
                found_any = True
        
        # If no results in batch and we already have some results, stop early
        if not found_any and results:
            break
    
    try:
        engine.closeDispatcher()
    except Exception:
        pass
    
    return results


async def snmp_walk(host, port, community, oid, timeout=4, retries=1):
    """Use index-based GET as fallback since WALK may timeout on some devices."""
    return await snmp_get_indexed(host, port, community, oid, max_index=64, timeout=timeout, retries=retries)


async def test_connection(host, port, community):
    result = await snmp_get(host, port, community, OID_SYS_NAME)
    if result is not None:
        return {"success": True, "sys_name": result}
    return {"success": False, "error": "SNMP timeout or unreachable"}


async def get_system_info(host, port, community):
    info = {}
    keys = ["sys_name", "sys_descr", "sys_uptime", "board_name", "serial", "firmware", "identity", "ros_version_alt"]
    oids = [OID_SYS_NAME, OID_SYS_DESCR, OID_SYS_UPTIME, OID_MT_BOARD, OID_MT_SERIAL, OID_MT_FIRMWARE, OID_MT_IDENTITY, OID_MT_ARCHITECTURE]
    results = await asyncio.gather(*[snmp_get(host, port, community, o) for o in oids], return_exceptions=True)
    for key, val in zip(keys, results):
        info[key] = str(val) if val and not isinstance(val, Exception) else ""
    try:
        ticks = int(info.get("sys_uptime", "0"))
        s = ticks // 100
        info["uptime_formatted"] = f"{s // 86400}d {(s % 86400) // 3600}h {(s % 3600) // 60}m"
        info["uptime_seconds"] = s
    except (ValueError, TypeError):
        info["uptime_formatted"] = "N/A"
        info["uptime_seconds"] = 0
    
    # Parse ROS version and architecture from sys_descr
    # Example: "RouterOS CCR1009-7G-1C-1S+" or "RouterOS 6.49.10 (x86)"
    descr = info.get("sys_descr", "")
    
    # Try to find version like "6.49.10" or "7.14.2"
    m = re.search(r'(\d+\.\d+\.?\d*)', descr)
    info["ros_version"] = m.group(1) if m else info.get("ros_version_alt", "")
    
    # Extract architecture from sys_descr if present
    arch_match = re.search(r'\(([\w]+)\)', descr)
    info["architecture"] = arch_match.group(1) if arch_match else ""
    
    # Identity fallback to sys_name if empty or just a number
    identity = info.get("identity", "")
    if not identity or identity.isdigit():
        info["identity"] = info.get("sys_name", "")
    
    # Clean up - use firmware version if ros_version empty
    if not info["ros_version"] and info.get("firmware"):
        info["ros_version"] = info["firmware"]
    
    return info


async def get_health_metrics(host, port, community):
    """Get extended health metrics: temperature, voltage, power."""
    metrics = {}
    oid_map = {
        "cpu_temp": OID_MT_CPU_TEMP,
        "board_temp": OID_MT_BOARD_TEMP,
        "voltage": OID_MT_VOLTAGE,
        "current": OID_MT_CURRENT,
        "power": OID_MT_POWER,
    }
    results = await asyncio.gather(*[snmp_get(host, port, community, oid) for oid in oid_map.values()], return_exceptions=True)
    for (key, _), val in zip(oid_map.items(), results):
        if val and not isinstance(val, Exception):
            try:
                v = int(val)
                # MikroTik returns temperature in tenths of degrees
                if "temp" in key:
                    metrics[key] = v / 10.0
                # Voltage in tenths of volt
                elif key == "voltage":
                    metrics[key] = v / 10.0
                # Current in mA, Power in watts
                elif key == "current":
                    metrics[key] = v
                elif key == "power":
                    metrics[key] = v / 10.0
                else:
                    metrics[key] = v
            except (ValueError, TypeError):
                metrics[key] = 0
        else:
            metrics[key] = 0
    return metrics


async def get_interfaces(host, port, community):
    names = await snmp_walk(host, port, community, OID_IF_DESCR)
    statuses = await snmp_walk(host, port, community, OID_IF_OPER_STATUS)
    speeds = await snmp_walk(host, port, community, OID_IF_SPEED)
    interfaces = []
    for idx, name in names.items():
        try:
            speed_val = speeds.get(idx, "0")
            speed = int(speed_val) if speed_val and speed_val.isdigit() else 0
        except (ValueError, TypeError):
            speed = 0
        interfaces.append({
            "index": idx, "name": name,
            "status": "up" if statuses.get(idx, "2") == "1" else "down",
            "speed": speed,
        })
    return interfaces


async def get_interface_traffic(host, port, community):
    names = await snmp_walk(host, port, community, OID_IF_DESCR)
    in_octets = await snmp_walk(host, port, community, OID_IF_HC_IN_OCTETS)
    if not in_octets:
        in_octets = await snmp_walk(host, port, community, OID_IF_IN_OCTETS)
    out_octets = await snmp_walk(host, port, community, OID_IF_HC_OUT_OCTETS)
    if not out_octets:
        out_octets = await snmp_walk(host, port, community, OID_IF_OUT_OCTETS)
    statuses = await snmp_walk(host, port, community, OID_IF_OPER_STATUS)
    traffic = {}
    for idx, name in names.items():
        try:
            traffic[name] = {
                "index": idx,
                "in_octets": int(in_octets.get(idx, "0")),
                "out_octets": int(out_octets.get(idx, "0")),
                "status": "up" if statuses.get(idx, "2") == "1" else "down",
            }
        except (ValueError, TypeError):
            pass
    return traffic


async def get_cpu_load(host, port, community):
    loads = await snmp_walk(host, port, community, OID_HR_PROCESSOR_LOAD)
    if not loads:
        return 0
    values = [int(v) for v in loads.values() if v.isdigit()]
    return round(sum(values) / len(values)) if values else 0


async def get_memory_usage(host, port, community):
    """Get memory usage from MikroTik via SNMP.
    Tries multiple methods: HR-MIB and MikroTik private OIDs.
    """
    memory = {"total": 0, "used": 0, "percent": 0}
    
    # Method 1: Try standard HR-MIB (Host Resources)
    descrs = await snmp_walk(host, port, community, OID_HR_STORAGE_DESCR)
    units = await snmp_walk(host, port, community, OID_HR_STORAGE_UNITS)
    sizes = await snmp_walk(host, port, community, OID_HR_STORAGE_SIZE)
    useds = await snmp_walk(host, port, community, OID_HR_STORAGE_USED)
    
    for idx, descr in descrs.items():
        descr_lower = descr.lower()
        # Look for memory-related entries
        if any(kw in descr_lower for kw in ["memory", "ram", "real memory", "main memory"]):
            try:
                unit = int(units.get(idx, "1"))
                total = int(sizes.get(idx, "0")) * unit
                used = int(useds.get(idx, "0")) * unit
                if total > memory["total"]:
                    memory = {"total": total, "used": used, "percent": round((used / total) * 100) if total > 0 else 0}
            except (ValueError, TypeError, ZeroDivisionError):
                pass
    
    # Method 2: If HR-MIB didn't work, try MikroTik private OID
    if memory["percent"] == 0:
        try:
            # MikroTik total memory in kB (OID .1.3.6.1.2.1.25.2.3.1.5.65536)
            total_kb = await snmp_get(host, port, community, '1.3.6.1.2.1.25.2.3.1.5.65536')
            used_kb = await snmp_get(host, port, community, '1.3.6.1.2.1.25.2.3.1.6.65536')
            
            if total_kb and used_kb:
                total = int(total_kb) * 1024  # Convert KB to bytes
                used = int(used_kb) * 1024
                if total > 0:
                    memory = {"total": total, "used": used, "percent": round((used / total) * 100)}
        except (ValueError, TypeError):
            pass
    
    # Method 3: Alternative MikroTik memory OIDs
    if memory["percent"] == 0:
        try:
            # Try hrStorageIndex 1 (often used for main memory)
            total_units = await snmp_get(host, port, community, '1.3.6.1.2.1.25.2.3.1.5.1')
            used_units = await snmp_get(host, port, community, '1.3.6.1.2.1.25.2.3.1.6.1')
            unit_size = await snmp_get(host, port, community, '1.3.6.1.2.1.25.2.3.1.4.1')
            
            if total_units and used_units and unit_size:
                unit = int(unit_size)
                total = int(total_units) * unit
                used = int(used_units) * unit
                if total > 0:
                    memory = {"total": total, "used": used, "percent": round((used / total) * 100)}
        except (ValueError, TypeError):
            pass
    
    return memory


async def ping_host(host, count=4, timeout=5):
    """
    Real ICMP ping to 8.8.8.8 (Google) and 1.1.1.1 (Cloudflare).
    Returns the best (lowest latency) result from both targets.
    host parameter is kept for API compatibility but not used for ping targets.
    """
    results = await asyncio.gather(
        _icmp_ping("8.8.8.8", count=count, timeout=timeout),
        _icmp_ping("1.1.1.1", count=count, timeout=timeout),
        return_exceptions=True
    )

    # Filter valid results
    valid = [r for r in results if isinstance(r, dict) and r.get("reachable")]

    if not valid:
        # Both failed — return unreachable
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}

    # Return the result with lowest average ping (best internet path)
    best = min(valid, key=lambda r: r.get("avg", 9999))
    return best


async def _icmp_ping(target: str, count: int = 4, timeout: int = 5) -> dict:
    """
    Real ICMP ping using system ping command.
    Works on Linux (server) with standard ping binary.
    """
    import time
    import re

    try:
        # Linux ping: -c count, -W timeout per packet (seconds), -q quiet summary
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", str(timeout), "-q", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout * count + 5
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="ignore")

        # Parse packet loss
        loss = 100
        loss_match = re.search(r"(\d+)%\s+packet\s+loss", output)
        if loss_match:
            loss = int(loss_match.group(1))

        # Parse rtt min/avg/max/mdev line
        # Example: rtt min/avg/max/mdev = 1.234/2.567/3.891/1.023 ms
        rtt_match = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
        if rtt_match:
            min_ms = float(rtt_match.group(1))
            avg_ms = float(rtt_match.group(2))
            max_ms = float(rtt_match.group(3))
            mdev_ms = float(rtt_match.group(4))  # mdev = jitter
            return {
                "reachable": loss < 100,
                "min": round(min_ms, 2),
                "avg": round(avg_ms, 2),
                "max": round(max_ms, 2),
                "jitter": round(mdev_ms, 2),
                "loss": loss,
                "target": target,
            }

        # If no rtt line, all packets lost
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100, "target": target}

    except Exception as e:
        logger.debug(f"ICMP ping to {target} failed: {e}")
        return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100, "target": target}


async def tcp_ping(host, ports, count=3, timeout=2):
    """Fallback TCP ping — kept for compatibility but not used for dashboard metrics."""
    import time
    latencies = []

    for _ in range(count):
        for port in ports:
            try:
                start = time.time()
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout
                )
                latency = (time.time() - start) * 1000
                latencies.append(latency)
                writer.close()
                await writer.wait_closed()
                break
            except Exception:
                continue

    if latencies:
        avg = sum(latencies) / len(latencies)
        min_lat = min(latencies)
        max_lat = max(latencies)
        jitter = sum(abs(l - avg) for l in latencies) / len(latencies) if len(latencies) > 1 else 0
        return {
            "reachable": True,
            "min": round(min_lat, 2),
            "avg": round(avg, 2),
            "max": round(max_lat, 2),
            "jitter": round(jitter, 2),
            "loss": round((count - len(latencies)) / count * 100)
        }

    return {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}



async def poll_device(host, port, community):
    # Run ping and SNMP checks in parallel - don't skip SNMP if ping fails
    # Many routers block ICMP but allow SNMP
    ping_task = ping_host(host)
    snmp_test_task = snmp_get(host, port, community, OID_SYS_NAME, timeout=5, retries=2)
    
    ping, snmp_test = await asyncio.gather(ping_task, snmp_test_task, return_exceptions=True)
    
    if isinstance(ping, Exception):
        ping = {"reachable": False, "min": 0, "avg": 0, "max": 0, "jitter": 0, "loss": 100}
    
    # Check if SNMP is reachable (even if ping fails)
    snmp_reachable = snmp_test is not None and not isinstance(snmp_test, Exception)
    
    if not snmp_reachable:
        return {"reachable": False, "ping": ping, "system": {}, "cpu": 0,
                "memory": {"total": 0, "used": 0, "percent": 0}, "interfaces": [], "traffic": {},
                "health": {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0}}
    
    # SNMP is reachable, fetch all data including health metrics
    sys_info, cpu, memory, ifaces, traffic, health = await asyncio.gather(
        get_system_info(host, port, community),
        get_cpu_load(host, port, community),
        get_memory_usage(host, port, community),
        get_interfaces(host, port, community),
        get_interface_traffic(host, port, community),
        get_health_metrics(host, port, community),
        return_exceptions=True,
    )
    return {
        "reachable": True, "ping": ping,
        "system": sys_info if not isinstance(sys_info, Exception) else {},
        "cpu": cpu if not isinstance(cpu, Exception) else 0,
        "memory": memory if not isinstance(memory, Exception) else {"total": 0, "used": 0, "percent": 0},
        "interfaces": ifaces if not isinstance(ifaces, Exception) else [],
        "traffic": traffic if not isinstance(traffic, Exception) else {},
        "health": health if not isinstance(health, Exception) else {"cpu_temp": 0, "board_temp": 0, "voltage": 0, "power": 0},
    }
