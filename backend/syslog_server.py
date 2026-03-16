"""
UDP Syslog server for receiving syslog messages from MikroTik devices.
Listens on port 5140 (configurable via SYSLOG_PORT env var).
Parses RFC3164 syslog format and stores in MongoDB.

MikroTik config: System → Logging → Actions → Add Remote Logging
  Remote Address: <server IP>
  Remote Port: 5140 (or 514 if using iptables redirect)
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from core.db import get_db

logger = logging.getLogger(__name__)
SYSLOG_PORT = int(os.environ.get("SYSLOG_PORT", "5140"))

# RFC5424 / RFC3164 severity names
SEVERITY = ["emergency", "alert", "critical", "error", "warning", "notice", "info", "debug"]
FACILITY = ["kern", "user", "mail", "system", "security", "syslogd", "lpd", "news",
            "uucp", "clockd", "security2", "ftp", "ntp", "logaudit", "logalert", "cron",
            "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7"]

# RFC3164 example: <134>Mar 10 12:00:00 routerOS_identity firewall,info forward: in:ether1 ...
RFC3164_RE = re.compile(
    r"^<(\d+)>"
    r"(?:(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+)?"  # optional timestamp
    r"(?:(\S+)\s+)?"                                  # optional hostname
    r"(.+)$",                                          # message
    re.DOTALL,
)


def parse_syslog(data: bytes, addr: tuple) -> dict:
    """Parse a syslog UDP packet into a structured dict."""
    try:
        raw = data.decode("utf-8", errors="replace").strip()
    except Exception:
        raw = str(data)

    now = datetime.now(timezone.utc).isoformat()
    source_ip = addr[0]

    m = RFC3164_RE.match(raw)
    if m:
        pri_str, ts_str, hostname, message = m.groups()
        pri = int(pri_str)
        facility_num = pri >> 3
        severity_num = pri & 7
        severity = SEVERITY[severity_num] if severity_num < len(SEVERITY) else "unknown"
        facility = FACILITY[facility_num] if facility_num < len(FACILITY) else "local"
        hostname = hostname or source_ip
        message = (message or "").strip()
    else:
        severity = "info"
        facility = "local"
        hostname = source_ip
        message = raw

    return {
        "timestamp": now,
        "source_ip": source_ip,
        "hostname": hostname or source_ip,
        "facility": facility,
        "severity": severity,
        "message": message,
        "raw": raw[:500],  # Store first 500 chars of raw for debugging
    }


class SyslogProtocol(asyncio.DatagramProtocol):
    def __init__(self, db_queue: asyncio.Queue):
        self.queue = db_queue

    def datagram_received(self, data: bytes, addr: tuple):
        entry = parse_syslog(data, addr)
        self.queue.put_nowait(entry)

    def error_received(self, exc):
        logger.warning(f"Syslog UDP error: {exc}")


async def _db_writer(queue: asyncio.Queue):
    """Consumer: reads from queue and inserts into MongoDB."""
    while True:
        entry = await queue.get()
        try:
            db = get_db()
            await db.syslog_entries.insert_one(entry)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Syslog DB write error: {e}")
        finally:
            queue.task_done()


async def _cleanup_old_logs():
    """Periodically delete syslog entries older than 30 days."""
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            db = get_db()
            r = await db.syslog_entries.delete_many({"timestamp": {"$lt": cutoff}})
            if r.deleted_count > 0:
                logger.info(f"Cleaned {r.deleted_count} old syslog entries")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Syslog cleanup error: {e}")
        await asyncio.sleep(3600)  # Run every hour


async def start_syslog_server(loop: asyncio.AbstractEventLoop):
    """Start the UDP syslog server and background writer. Returns coroutine to await."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: SyslogProtocol(queue),
            local_addr=("0.0.0.0", SYSLOG_PORT),
            family=2,  # AF_INET
        )
        logger.info(f"Syslog UDP server listening on port {SYSLOG_PORT}")
    except OSError as e:
        logger.error(f"Failed to start syslog server on port {SYSLOG_PORT}: {e}")
        logger.warning("Syslog server will be disabled. Try SYSLOG_PORT=5140 (non-privileged).")
        return

    asyncio.create_task(_db_writer(queue))
    asyncio.create_task(_cleanup_old_logs())
