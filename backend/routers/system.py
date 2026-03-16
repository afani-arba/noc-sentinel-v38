"""
System update router: check and perform application updates.
"""
import os
import asyncio
import subprocess
import logging
import threading
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from core.auth import require_admin

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(__name__)

# Project root: /opt/noc-sentinel  (parent of backend/)
APP_DIR = str(Path(__file__).parent.parent.parent)
BACKEND_DIR = str(Path(__file__).parent.parent)
FRONTEND_DIR = str(Path(__file__).parent.parent.parent / "frontend")

# Candidate paths — support both venv/ and .venv/
BACKEND_DIR_PATH = Path(BACKEND_DIR)
_venv_candidates = [BACKEND_DIR_PATH / "venv" / "bin" / "pip", BACKEND_DIR_PATH / ".venv" / "bin" / "pip"]
VENV_PIP = str(next((p for p in _venv_candidates if p.exists()), _venv_candidates[0]))
_uvicorn_candidates = [BACKEND_DIR_PATH / "venv" / "bin" / "uvicorn", BACKEND_DIR_PATH / ".venv" / "bin" / "uvicorn"]
VENV_UVICORN = str(next((u for u in _uvicorn_candidates if u.exists()), _uvicorn_candidates[0]))
UPDATE_SH = str(Path(APP_DIR) / "update.sh")
# Baca dari env agar bisa dikonfigurasi tanpa edit kode
SERVICE_NAME = os.environ.get("NOC_SERVICE_NAME", "noc-backend")

# ── Background Update State ───────────────────────────────────────────────────
_update_state = {
    "running": False,
    "done": False,
    "success": None,
    "log": [],
    "error": "",
    "started_at": None,
}


@router.get("/check-update")
async def check_update(user=Depends(require_admin)):
    """Check if there are updates available from GitHub."""
    try:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
        )
        current_commit = current.stdout.strip() if current.returncode == 0 else None

        # Get current commit message
        current_msg = ""
        if current_commit:
            msg_result = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            current_msg = msg_result.stdout.strip() if msg_result.returncode == 0 else ""

        fetch = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True, cwd=APP_DIR, timeout=30
        )
        if fetch.returncode != 0:
            return {
                "has_update": False, "current_commit": current_commit,
                "current_message": current_msg,
                "message": "Tidak dapat terhubung ke repository.", "error": fetch.stderr
            }

        # Try main, then master
        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
        )
        if remote.returncode != 0:
            remote = subprocess.run(
                ["git", "rev-parse", "origin/master"], capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
        if remote.returncode != 0:
            return {"has_update": False, "current_commit": current_commit, "current_message": current_msg, "message": "Branch remote tidak ditemukan."}

        latest_commit = remote.stdout.strip()
        has_update = current_commit != latest_commit

        commits_behind = 0
        latest_message = ""
        latest_date = ""

        if has_update:
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..origin/main"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            if count.returncode == 0:
                try:
                    commits_behind = int(count.stdout.strip())
                except ValueError:
                    commits_behind = 0

            # Get latest commit message on remote
            msg_r = subprocess.run(
                ["git", "log", "origin/main", "-1", "--pretty=%s"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            latest_message = msg_r.stdout.strip() if msg_r.returncode == 0 else ""

            date_r = subprocess.run(
                ["git", "log", "origin/main", "-1", "--pretty=%ci"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=10
            )
            latest_date = date_r.stdout.strip()[:19] if date_r.returncode == 0 else ""

        return {
            "has_update": has_update,
            "current_commit": current_commit,
            "current_message": current_msg,
            "latest_commit": latest_commit,
            "latest_message": latest_message,
            "latest_date": latest_date,
            "commits_behind": commits_behind,
            "message": "Update tersedia!" if has_update else "Aplikasi sudah versi terbaru."
        }
    except subprocess.TimeoutExpired:
        return {"has_update": False, "message": "Timeout saat mengecek update.", "error": "timeout"}
    except Exception as e:
        logger.error(f"Check update error: {e}")
        return {"has_update": False, "message": f"Error: {str(e)}", "error": str(e)}


@router.post("/perform-update")
async def perform_update(user=Depends(require_admin)):
    """Jalankan update di background thread, langsung return job id untuk polling."""
    global _update_state

    if _update_state["running"]:
        return {"started": False, "message": "Update sudah berjalan, cek /system/update-status"}

    svc_name = os.environ.get("NOC_SERVICE_NAME", "noc-backend")

    # Reset state
    _update_state = {
        "running": True,
        "done": False,
        "success": None,
        "log": ["🚀 Memulai proses update..."],
        "error": "",
        "started_at": time.time(),
    }

    def _run():
        log = _update_state["log"]

        def _append(msg):
            log.append(msg)
            logger.info(msg)

        try:
            # ── cek sudo ──────────────────────────────────────────────
            sudo_ok = subprocess.run(
                ["sudo", "-n", "systemctl", "status", svc_name],
                capture_output=True, text=True, timeout=5
            ).returncode == 0

            if not sudo_ok:
                _append("⚠️  sudo belum dikonfigurasi — restart service akan dilewati")

            # ── coba update.sh ────────────────────────────────────────
            if Path(UPDATE_SH).exists():
                _append("[1/1] Menjalankan update.sh...")
                proc = subprocess.Popen(
                    ["bash", UPDATE_SH],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=APP_DIR
                )
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        _append(line)
                proc.wait(timeout=600)
                if proc.returncode == 0:
                    _append("✅ Update selesai via update.sh!")
                    _update_state.update({"running": False, "done": True, "success": True})
                    return
                else:
                    _append(f"❌ update.sh gagal (exit {proc.returncode}), fallback ke metode manual...")

            # ── fallback: manual steps ────────────────────────────────
            _append("[1/4] Git pull...")
            pull = subprocess.run(
                ["git", "pull", "origin", "main"],
                capture_output=True, text=True, cwd=APP_DIR, timeout=60
            )
            if pull.returncode != 0:
                pull = subprocess.run(
                    ["git", "pull", "origin", "master"],
                    capture_output=True, text=True, cwd=APP_DIR, timeout=60
                )
            if pull.returncode != 0:
                err = pull.stderr.strip() or pull.stdout.strip()
                _append(f"❌ Git pull GAGAL: {err}")
                _update_state.update({"running": False, "done": True, "success": False, "error": err})
                return
            _append(f"✅ {pull.stdout.strip() or 'Git pull berhasil'}")

            _append("[2/4] Install dependensi backend...")
            pip_cmd = VENV_PIP if Path(VENV_PIP).exists() else "pip3"
            pip = subprocess.run(
                [pip_cmd, "install", "-r", "requirements.txt", "-q"],
                capture_output=True, text=True, cwd=BACKEND_DIR, timeout=180
            )
            _append("✅ Backend deps OK" if pip.returncode == 0 else f"⚠️ pip: {pip.stderr[:200]}")

            _append("[3/4] Install + build frontend...")
            npm_path = subprocess.run(["which", "npm"], capture_output=True, text=True).stdout.strip() or "npm"
            subprocess.run(
                [npm_path, "install", "--legacy-peer-deps", "--prefer-offline"],
                capture_output=True, cwd=FRONTEND_DIR, timeout=240
            )

            build_env = {**dict(os.environ), "CI": "false", "DISABLE_ESLINT_PLUGIN": "true"}
            build_proc = subprocess.Popen(
                [npm_path, "run", "build"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=FRONTEND_DIR, env=build_env
            )
            for line in build_proc.stdout:
                line = line.rstrip()
                if line:
                    _append(line)
            build_proc.wait(timeout=600)

            if build_proc.returncode != 0:
                _append("❌ Frontend build GAGAL")
                _update_state.update({"running": False, "done": True, "success": False, "error": "Frontend build failed"})
                return
            _append("✅ Frontend build berhasil")

            _append(f"[4/4] Restart service {svc_name}...")
            if sudo_ok:
                restart = subprocess.run(
                    ["sudo", "systemctl", "restart", svc_name],
                    capture_output=True, text=True, timeout=30
                )
                if restart.returncode == 0:
                    _append(f"✅ Service {svc_name} berhasil di-restart!")
                else:
                    _append(f"⚠️ Restart gagal: {restart.stderr.strip()}")
                    _append(f"   Jalankan manual: sudo systemctl restart {svc_name}")
            else:
                _append(f"⚠️ Jalankan manual: sudo systemctl restart {svc_name}")

            _append("\n=== ✅ Update selesai! ===")
            _update_state.update({"running": False, "done": True, "success": True})

        except Exception as e:
            _append(f"❌ Exception: {e}")
            _update_state.update({"running": False, "done": True, "success": False, "error": str(e)})

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "message": "Update dimulai di background. Poll /system/update-status untuk progress."}


@router.get("/update-status")
async def update_status(user=Depends(require_admin)):
    """Polling endpoint untuk status update yang berjalan di background."""
    return {
        "running": _update_state["running"],
        "done": _update_state["done"],
        "success": _update_state["success"],
        "log": _update_state["log"],
        "error": _update_state["error"],
        "elapsed": round(time.time() - _update_state["started_at"], 1) if _update_state["started_at"] else 0,
    }


@router.get("/debug-bw")
async def debug_bw(user=Depends(require_admin)):
    """
    Debug endpoint: lihat data bandwidth terakhir dari traffic_history.
    Berguna untuk diagnosa kenapa DL/UL = 0.
    """
    from core.db import get_db
    db = get_db()
    devs = await db.devices.find({}, {"_id": 0, "id": 1, "name": 1, "isp_interfaces": 1,
                                      "api_mode": 1, "ros_version": 1}).to_list(50)
    results = []
    for d in devs:
        last = await db.traffic_history.find_one(
            {"device_id": d["id"]},
            {"_id": 0, "timestamp": 1, "bandwidth": 1, "isp_bandwidth": 1,
             "download_mbps": 1, "upload_mbps": 1},
            sort=[("timestamp", -1)]
        )
        bw_keys = list((last.get("bandwidth") or {}).keys()) if last else []
        isp_bw_keys = list((last.get("isp_bandwidth") or {}).keys()) if last else []
        results.append({
            "name": d.get("name"),
            "api_mode": d.get("api_mode"),
            "ros_version": d.get("ros_version"),
            "isp_interfaces": d.get("isp_interfaces", []),
            "last_ts": (last or {}).get("timestamp"),
            "dl_mbps": (last or {}).get("download_mbps", 0),
            "ul_mbps": (last or {}).get("upload_mbps", 0),
            "bw_iface_count": len(bw_keys),
            "bw_iface_names": bw_keys[:10],   # max 10 for readability
            "isp_bw_names": isp_bw_keys,
        })
    return {"debug_bw": results}



@router.get("/app-info")
async def app_info():
    """Return current app version info (commit hash, message, date)."""
    svc_name = os.environ.get("NOC_SERVICE_NAME", "noc-backend")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=APP_DIR, timeout=5
        )
        msg = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True, cwd=APP_DIR, timeout=5
        )
        date = subprocess.run(
            ["git", "log", "-1", "--pretty=%ci"], capture_output=True, text=True, cwd=APP_DIR, timeout=5
        )
        return {
            "commit": commit.stdout.strip() if commit.returncode == 0 else "unknown",
            "message": msg.stdout.strip() if msg.returncode == 0 else "",
            "date": date.stdout.strip()[:19] if date.returncode == 0 else "",
            "version": "v3.0",
            "service_name": svc_name,
        }
    except Exception:
        return {"commit": "unknown", "message": "", "date": "", "version": "v3.0", "service_name": svc_name}


@router.get("/service-name")
async def get_service_name(user=Depends(require_admin)):
    """Return nama service systemd yang digunakan."""
    return {"service_name": os.environ.get("NOC_SERVICE_NAME", "noc-backend")}


@router.post("/save-service-name")
async def save_service_name(data: dict, user=Depends(require_admin)):
    """Simpan nama service ke .env agar persisten."""
    svc = (data.get("service_name") or "").strip()
    if not svc:
        raise HTTPException(400, "Nama service tidak boleh kosong")

    backend_dir = Path(__file__).parent.parent
    env_path = backend_dir / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("NOC_SERVICE_NAME="):
            new_lines.append(f"NOC_SERVICE_NAME={svc}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"NOC_SERVICE_NAME={svc}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["NOC_SERVICE_NAME"] = svc
    logger.info(f"Service name saved: {svc}")
    return {"message": f"Nama service disimpan: {svc}"}


@router.post("/save-influxdb-config")
async def save_influxdb_config(data: dict, user=Depends(require_admin)):
    """
    Save InfluxDB configuration to the backend .env file.
    Updates INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET.
    """
    backend_dir = Path(__file__).parent.parent
    env_path = backend_dir / ".env"

    url = (data.get("url") or "").strip()
    token = (data.get("token") or "").strip()
    org = (data.get("org") or "").strip()
    bucket = (data.get("bucket") or "noc-sentinel").strip()

    if not url or not token or not org:
        from fastapi import HTTPException
        raise HTTPException(400, "URL, token, dan org wajib diisi")

    # Read existing .env
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # Keys to update
    new_values = {
        "INFLUXDB_URL": url,
        "INFLUXDB_TOKEN": token,
        "INFLUXDB_ORG": org,
        "INFLUXDB_BUCKET": bucket,
    }

    updated = set()
    new_lines = []
    for line in lines:
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in new_values:
            new_lines.append(f'{key}={new_values[key]}')
            updated.add(key)
        else:
            new_lines.append(line)

    # Append any missing keys
    for key, val in new_values.items():
        if key not in updated:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Also set in current process env so test-connection works immediately
    import os as _os
    _os.environ["INFLUXDB_URL"] = url
    _os.environ["INFLUXDB_TOKEN"] = token
    _os.environ["INFLUXDB_ORG"] = org
    _os.environ["INFLUXDB_BUCKET"] = bucket

    # Reset cached client so next test uses new config
    try:
        import services.metrics_service as _ms
        _ms._influx_enabled = None
        _ms._write_client = None
        _ms._query_client = None
        _ms._write_api = None
        _ms._error_logged = False
    except Exception:
        pass

    logger.info(f"InfluxDB config saved: {url}, org={org}, bucket={bucket}")
    return {"message": "Konfigurasi InfluxDB disimpan. Restart backend tidak diperlukan — sudah aktif."}


@router.get("/health")
async def health():
    """
    Health check endpoint.
    Mengembalikan status sistem termasuk:
    - snmp_enabled: True jika pysnmp-lextudio terinstall dan bisa di-import
    - app_version:  git commit hash pendek (7 karakter)
    - syslog_port:  port UDP syslog yang aktif
    """
    # Cek pysnmp secara live menggunakan snmp_compat bridge
    # (kompatibel dengan pysnmp 7.x baru maupun pysnmp-lextudio lama)
    try:
        from snmp_compat import PYSNMP_AVAILABLE
        snmp_enabled = PYSNMP_AVAILABLE
    except Exception:
        snmp_enabled = False

    # Ambil git commit hash pendek
    app_version = "unknown"
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=APP_DIR, timeout=3
        )
        if commit.returncode == 0:
            app_version = commit.stdout.strip()
    except Exception:
        pass

    return {
        "status": "ok",
        "snmp_enabled": snmp_enabled,
        "app_version": app_version,
        "syslog_port": int(os.environ.get("SYSLOG_PORT", "5140")),
    }


@router.post("/save-genieacs-config")
async def save_genieacs_config(data: dict, user=Depends(require_admin)):
    """
    Save GenieACS NBI configuration to the backend .env file.
    Updates GENIEACS_URL, GENIEACS_USERNAME, GENIEACS_PASSWORD.
    """
    backend_dir = Path(__file__).parent.parent
    env_path = backend_dir / ".env"

    url = (data.get("url") or "").strip()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not url:
        from fastapi import HTTPException
        raise HTTPException(400, "GENIEACS_URL wajib diisi")

    # Read existing .env
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    new_values = {
        "GENIEACS_URL": url,
        "GENIEACS_USERNAME": username,
        "GENIEACS_PASSWORD": password,
    }

    updated = set()
    new_lines = []
    for line in lines:
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in new_values:
            new_lines.append(f"{key}={new_values[key]}")
            updated.add(key)
        else:
            new_lines.append(line)

    for key, val in new_values.items():
        if key not in updated:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Apply to current process immediately (no restart needed)
    import os as _os
    _os.environ["GENIEACS_URL"] = url
    _os.environ["GENIEACS_USERNAME"] = username
    _os.environ["GENIEACS_PASSWORD"] = password

    # Refresh genieacs_service module globals
    try:
        import services.genieacs_service as _gs
        _gs.GENIEACS_URL = url
        _gs.GENIEACS_USER = username
        _gs.GENIEACS_PASS = password
    except Exception:
        pass

    logger.info(f"GenieACS config saved: {url}, user={username}")
    return {"message": "Konfigurasi GenieACS disimpan dan langsung aktif. Tidak perlu restart."}


@router.get("/genieacs-config")
async def get_genieacs_config(user=Depends(require_admin)):
    """Return current GenieACS config (URL only, password masked)."""
    import os as _os
    return {
        "url": _os.environ.get("GENIEACS_URL", ""),
        "username": _os.environ.get("GENIEACS_USERNAME", ""),
        "password_set": bool(_os.environ.get("GENIEACS_PASSWORD", "")),
    }


# ── Winbox Path Configuration ─────────────────────────────────────────────────

@router.get("/winbox-config")
async def get_winbox_config(user=Depends(require_admin)):
    """Return configured Winbox executable path."""
    import os as _os
    return {
        "winbox_path": _os.environ.get("WINBOX_PATH", ""),
    }


@router.post("/save-winbox-config")
async def save_winbox_config(data: dict, user=Depends(require_admin)):
    """
    Simpan path executable Winbox ke .env agar bisa dipakai saat generate URL.
    Contoh path: C:\\Users\\user\\Desktop\\winbox64.exe
    """
    winbox_path = (data.get("winbox_path") or "").strip()
    # Path boleh kosong (artinya gunakan default URI scheme winbox://)

    backend_dir = Path(__file__).parent.parent
    env_path = backend_dir / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("WINBOX_PATH="):
            new_lines.append(f"WINBOX_PATH={winbox_path}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"WINBOX_PATH={winbox_path}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["WINBOX_PATH"] = winbox_path
    logger.info(f"Winbox path saved: {winbox_path!r}")
    return {"message": "Path Winbox disimpan.", "winbox_path": winbox_path}

