#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║   NOC Sentinel v3.8 — In-Place Migration Script                             ║
# ║   Upgrade dari folder lama ke v38 TANPA menyentuh data MongoDB              ║
# ║                                                                              ║
# ║   CARA PAKAI (di server):                                                   ║
# ║     cd /opt/noc-sentinel-v38                                                ║
# ║     sudo bash migrate.sh                                                    ║
# ║                                                                              ║
# ║   ATURAN KETAT:                                                             ║
# ║   ✓ Data MongoDB TIDAK disentuh (no drop, no truncate)                     ║
# ║   ✓ .env lama di-copy → MONGO_URI + JWT_SECRET tetap sama                  ║
# ║   ✓ Library di folder lama TIDAK diubah (venv baru di v38)                 ║
# ║   ✓ Systemd ARBAMonitoring.service diarahkan ke /opt/noc-sentinel-v38       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
set -e

# ── Konfigurasi ───────────────────────────────────────────────────────────────
NEW_DIR="/opt/noc-sentinel-v38"
OLD_DIRS=(
    "/opt/noc-sentinel-v3"
    "/opt/noc-sentinel"
)
SERVICE="ARBAMonitoring"                   # Service name TETAP sama (tidak ganti)
NEW_VENV="$NEW_DIR/backend/venv"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'; BOLD='\033[1m'
ok()   { echo -e "  ${G}✔ $*${N}"; }
warn() { echo -e "  ${Y}⚠ $*${N}"; }
err()  { echo -e "\n${R}${BOLD}✗ ERROR: $*${N}\n"; exit 1; }
step() { echo -e "\n${BOLD}${B}▶ $*${N}"; }

[[ $EUID -ne 0 ]] && err "Jalankan sebagai root: sudo bash migrate.sh"
[[ ! -d "$NEW_DIR/.git" ]] && err "$NEW_DIR tidak ditemukan!\n  git clone https://github.com/afani-arba/noc-sentinel-v38.git $NEW_DIR"

echo -e "\n${BOLD}${B}╔═══════════════════════════════════════════════════════╗${N}"
echo -e "${BOLD}${B}║   NOC Sentinel v3.8 — In-Place Migration              ║${N}"
echo -e "${BOLD}${B}║   Aplikasi Baru — Data Tetap Lama                     ║${N}"
echo -e "${BOLD}${B}╚═══════════════════════════════════════════════════════╝${N}"
echo -e "  Waktu   : $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  New dir : $NEW_DIR"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# FASE 1: TEMUKAN FOLDER LAMA
# ══════════════════════════════════════════════════════════════════════════════
step "[1/7] Mencari folder instalasi lama..."

OLD_DIR=""
for d in "${OLD_DIRS[@]}"; do
    if [[ -d "$d" && -f "$d/backend/.env" ]]; then
        OLD_DIR="$d"
        ok "Folder lama ditemukan: $OLD_DIR"
        break
    fi
done

[[ -z "$OLD_DIR" ]] && err "Tidak menemukan folder lama dengan .env!\n  Cari manual: find /opt -name '.env' 2>/dev/null"

# ══════════════════════════════════════════════════════════════════════════════
# FASE 2: STOP SERVICE (SEBELUM APA PUN)
# ══════════════════════════════════════════════════════════════════════════════
step "[2/7] Stop service $SERVICE..."
systemctl stop "$SERVICE" 2>/dev/null || warn "Service $SERVICE tidak running, lanjut"

i=0
while systemctl is-active --quiet "$SERVICE" 2>/dev/null && [[ $i -lt 15 ]]; do
    sleep 1; i=$((i+1))
done
set +e; fuser -k 8000/tcp 2>/dev/null; set -e

ok "Service stopped"

# ══════════════════════════════════════════════════════════════════════════════
# FASE 3: ENVIRONMENT SYNC (copy .env lama, JANGAN edit MONGO_URI / JWT_SECRET)
# ══════════════════════════════════════════════════════════════════════════════
step "[3/7] Environment Sync — copy .env dari folder lama..."

OLD_ENV="$OLD_DIR/backend/.env"
NEW_ENV="$NEW_DIR/backend/.env"

# Backup .env.example di new folder jika overwrite
[[ -f "$NEW_ENV" ]] && cp "$NEW_ENV" "$NEW_ENV.bak.$(date +%s)" && warn ".env lama di-backup"

cp "$OLD_ENV" "$NEW_ENV"
chmod 600 "$NEW_ENV"
ok ".env berhasil di-copy dari $OLD_ENV"

# Tampilkan isi (masked) untuk konfirmasi
MONGO_URI=$(grep "^MONGO_URI=" "$NEW_ENV" | cut -d= -f2- | sed 's/:.*@/:***@/')
MONGO_DB=$(grep "^MONGO_DB_NAME=" "$NEW_ENV" | cut -d= -f2-)
ok "MONGO_URI : $MONGO_URI"
ok "MONGO_DB  : ${MONGO_DB:-nocsentinel}"

echo ""
echo -e "  ${Y}⚠  DATA MONGODB TIDAK AKAN DISENTUH — AMAN${N}"
echo -e "  ${Y}   Collection devices dan users lama tetap ada${N}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# FASE 4: GIT PULL (pastikan kode paling baru)
# ══════════════════════════════════════════════════════════════════════════════
step "[4/7] Git Pull kode terbaru..."
cd "$NEW_DIR"
BEFORE=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
git pull origin master 2>/dev/null || git pull origin main 2>/dev/null || warn "Git pull gagal — melanjutkan dengan kode lokal"
AFTER=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
[[ "$BEFORE" != "$AFTER" ]] && ok "Updated: $BEFORE → $AFTER" || ok "Kode sudah terbaru ($AFTER)"

# ══════════════════════════════════════════════════════════════════════════════
# FASE 5: CLEAN VENV (venv baru di v38, TIDAK menyentuh venv lama)
# ══════════════════════════════════════════════════════════════════════════════
step "[5/7] Setup Python virtual environment baru (tidak menyentuh venv lama)..."

# Pastikan Python tersedia
PYTHON_BIN=$(command -v python3.11 || command -v python3 || echo "")
[[ -z "$PYTHON_BIN" ]] && err "python3 tidak ditemukan!"
ok "Python : $($PYTHON_BIN --version)"

# Buat venv baru di v38
if [[ -d "$NEW_VENV" ]]; then
    warn "venv sudah ada di $NEW_VENV — hapus dan buat ulang untuk clean install"
    rm -rf "$NEW_VENV"
fi
$PYTHON_BIN -m venv "$NEW_VENV"
ok "venv baru dibuat: $NEW_VENV"

# Upgrade pip
"$NEW_VENV/bin/pip" install --upgrade pip -q
ok "pip upgraded"

# Install requirements (termasuk pysnmp-lextudio==6.2.0)
"$NEW_VENV/bin/pip" uninstall pysnmp pysnmp-lextudio pyasn1 pyasn1-modules pysmi pysmi-lextudio -y -q 2>/dev/null || true
"$NEW_VENV/bin/pip" install -r "$NEW_DIR/backend/requirements.txt" -q

# Verifikasi pysnmp async API
if "$NEW_VENV/bin/python" -c "from pysnmp.hlapi.asyncio import getCmd, SnmpEngine; print('OK')" 2>/dev/null | grep -q "OK"; then
    VER=$("$NEW_VENV/bin/python" -c "import pysnmp; print(getattr(pysnmp,'__version__','?'))" 2>/dev/null || echo "?")
    ok "pysnmp-lextudio $VER — import asyncio OK ✓"
else
    warn "pysnmp gagal — paksa install exact versions..."
    "$NEW_VENV/bin/pip" install pyasn1==0.5.1 pyasn1-modules==0.3.0 pysmi-lextudio==1.3.3 pysnmp-lextudio==6.2.0 -q \
        && ok "pysnmp-lextudio 6.2.0 berhasil ✓" \
        || warn "pysnmp gagal total — SNMP nonaktif"
fi
ok "Python packages selesai"

# ══════════════════════════════════════════════════════════════════════════════
# FASE 6: BUILD FRONTEND
# ══════════════════════════════════════════════════════════════════════════════
step "[6/7] Build Frontend React..."
cd "$NEW_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
npm run build
[[ -f "build/index.html" ]] && ok "Frontend build OK → $NEW_DIR/frontend/build/" || err "Build frontend gagal!"

# ══════════════════════════════════════════════════════════════════════════════
# FASE 7: UPDATE SYSTEMD SERVICE → ARAHKAN KE FOLDER BARU
# ══════════════════════════════════════════════════════════════════════════════
step "[7/7] Update systemd $SERVICE.service → $NEW_DIR..."

SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
[[ ! -f "$SERVICE_FILE" ]] && err "Service file $SERVICE_FILE tidak ditemukan!\n  Pastikan service sudah pernah di-install sebelumnya."

# Backup service file lama
cp "$SERVICE_FILE" "${SERVICE_FILE}.bak.$(date +%s)"
ok "Service file lama di-backup"

# Update ExecStart, WorkingDirectory, PYTHONPATH ke folder baru
sed -i "s|WorkingDirectory=.*|WorkingDirectory=${NEW_DIR}/backend|g" "$SERVICE_FILE"
sed -i "s|Environment=.*PATH=.*|Environment=\"PATH=${NEW_DIR}/backend/venv/bin\"|g" "$SERVICE_FILE"
sed -i "s|ExecStart=.*/uvicorn|ExecStart=${NEW_DIR}/backend/venv/bin/uvicorn|g" "$SERVICE_FILE"

# Update deskripsi
sed -i "s|Description=NOC Sentinel.*|Description=NOC Sentinel v3.8 Backend (FastAPI) — migrated $(date '+%Y-%m-%d')|g" "$SERVICE_FILE"

ok "Service file diupdate → $NEW_DIR"

# Reload dan start
systemctl daemon-reload
systemctl start "$SERVICE"
sleep 6

if systemctl is-active --quiet "$SERVICE"; then
    ok "Backend '$SERVICE': RUNNING ✔"
else
    echo -e "${R}✗ Backend gagal start! Log terakhir:${N}"
    journalctl -u "$SERVICE" -n 40 --no-pager
    echo ""
    echo -e "${Y}Cek env dan coba manual:${N}"
    echo "  sudo -u www-data $NEW_DIR/backend/venv/bin/python $NEW_DIR/backend/server.py"
    exit 1
fi

# Nginx — update root jika ada
NGINX_CONF="/etc/nginx/sites-available/nocsentinel"
if [[ -f "$NGINX_CONF" ]]; then
    sed -i "s|root .*frontend/build|root ${NEW_DIR}/frontend/build|g" "$NGINX_CONF"
    nginx -t && systemctl reload nginx && ok "Nginx root diupdate → $NEW_DIR/frontend/build"
fi

# Health check
sleep 2
curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q "ok" \
    && ok "API health: OK ✔" \
    || warn "API belum respond — cek: journalctl -u $SERVICE -f"

# ── Ringkasan ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${G}${BOLD}╔═══════════════════════════════════════════════════════╗${N}"
echo -e "${G}${BOLD}║   ✅  MIGRASI v3.8 SELESAI — DATA AMAN!               ║${N}"
echo -e "${G}${BOLD}╚═══════════════════════════════════════════════════════╝${N}"
echo ""
echo -e "  Folder baru   : $NEW_DIR"
echo -e "  Folder lama   : $OLD_DIR (TIDAK dimodifikasi, backup aman)"
echo -e "  Service       : $SERVICE (menunjuk ke $NEW_DIR)"
echo -e "  MongoDB       : TIDAK DISENTUH — data devices & users aman"
echo -e "  Commit        : $(git -C $NEW_DIR log -1 --format='%h — %s' 2>/dev/null || echo '?')"
echo -e "  Waktu         : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo -e "  ${Y}Update berikutnya: sudo noc-update${N}"
echo -e "  ${Y}Monitor log      : journalctl -u $SERVICE -f${N}"
echo ""
