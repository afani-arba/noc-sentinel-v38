"""
Auto-backup service for MikroTik configurations.
Export strategy (in order):
  1. SSH /export terse  (works for both RouterOS 6 and 7, most reliable)
  2. REST API /export   (RouterOS 7+ REST API fallback)
Backups stored in /backups/ directory relative to backend folder.
"""
import asyncio
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from core.db import get_db
from mikrotik_api import get_api_client

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).parent.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

SSH_PORT = 42
SSH_TIMEOUT = 20


async def _get_device(device_id: str) -> Optional[dict]:
    db = get_db()
    return await db.devices.find_one({"id": device_id}, {"_id": 0})


def _safe_filename(name: str) -> str:
    """Sanitize device name for use in filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _export_via_ssh(host: str, username: str, password: str, port: int = SSH_PORT) -> Optional[str]:
    """Run /export terse on MikroTik via SSH. Works for RouterOS 6 and 7."""
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=SSH_TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )
        _, stdout, _ = client.exec_command("/export terse", timeout=60)
        output = stdout.read().decode("utf-8", errors="replace")
        client.close()
        if output and len(output.strip()) > 10:
            return output
        logger.warning(f"SSH export returned empty output for {host}")
        return None
    except ImportError:
        logger.warning("paramiko not installed — SSH export unavailable")
        return None
    except Exception as e:
        logger.warning(f"SSH export failed for {host}: {e}")
        return None


def _export_via_rest(mt_client) -> Optional[str]:
    """Fetch RSC config via REST API /export endpoint (RouterOS 7+)."""
    if not hasattr(mt_client, "base_url"):
        return None
    try:
        import requests
        resp = requests.get(
            f"{mt_client.base_url}/export",
            auth=mt_client.auth,
            verify=False,
            timeout=60,
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text
        logger.warning(f"REST /export returned HTTP {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"REST export failed: {e}")
        return None


def _get_rsc_export(mt_client, device: dict) -> Optional[str]:
    """Try SSH export first, then REST API."""
    host = getattr(mt_client, "host", None) or device.get("ip_address", "")
    username = device.get("api_username", "admin")
    password = device.get("api_password", "")

    # Method 1: SSH — most reliable, works for ROS6 and ROS7
    if host and username:
        content = _export_via_ssh(host, username, password, port=SSH_PORT)
        if content:
            logger.info(f"RSC export via SSH successful for {host}")
            return content

    # Method 2: REST API — ROS7 fallback
    content = _export_via_rest(mt_client)
    if content:
        logger.info(f"RSC export via REST successful")
        return content

    return None


async def backup_device_api(device: dict) -> dict:
    """
    Backup MikroTik config via SSH export (primary) or REST API (fallback).
    Returns: {"success": bool, "filename": str, "size": int, "type": str}
    """
    device_name = _safe_filename(device.get("name", device["id"]))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{device_name}_{timestamp}"

    try:
        mt = get_api_client(device)

        rsc_content = await asyncio.to_thread(_get_rsc_export, mt, device)
        if rsc_content:
            rsc_filename = f"{backup_name}.rsc"
            rsc_path = BACKUP_DIR / rsc_filename
            rsc_path.write_text(rsc_content, encoding="utf-8")
            logger.info(f"RSC backup saved: {rsc_filename} ({len(rsc_content)} bytes)")

            db = get_db()
            await db.backups.insert_one({
                "device_id": device["id"],
                "device_name": device.get("name", ""),
                "ip_address": device.get("ip_address", ""),
                "filename": rsc_filename,
                "type": "rsc",
                "size": len(rsc_content.encode()),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            return {
                "success": True,
                "filename": rsc_filename,
                "size": len(rsc_content.encode()),
                "type": "rsc",
            }

        return {
            "success": False,
            "error": (
                "Tidak dapat mengambil konfigurasi dari device. "
                f"Pastikan SSH (port {SSH_PORT}) aktif di MikroTik: /ip service set ssh port={SSH_PORT} disabled=no"
            ),
        }

    except Exception as e:
        logger.error(f"Backup failed for {device.get('name', device['id'])}: {e}")
        return {"success": False, "error": str(e)}


def list_backup_files() -> list:
    """List all backup files in the backup directory."""
    files = []
    for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if f.is_file() and f.suffix in (".rsc", ".backup"):
            files.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                "type": f.suffix[1:],
            })
    return files


def get_backup_path(filename: str) -> Optional[Path]:
    """Get safe path for a backup file, ensuring no path traversal."""
    if not re.match(r"^[a-zA-Z0-9_.\-]+$", filename):
        return None
    path = BACKUP_DIR / filename
    if path.exists() and path.is_file():
        return path
    return None


def delete_backup_file(filename: str) -> bool:
    """Delete a backup file."""
    path = get_backup_path(filename)
    if path:
        path.unlink()
        return True
    return False
