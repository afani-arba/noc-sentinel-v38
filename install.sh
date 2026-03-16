#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║   NOC Sentinel v3.8 — Install/Update Script                             ║
# ║   CARA PAKAI: sudo bash /opt/noc-sentinel-v38/install.sh               ║
# ╚══════════════════════════════════════════════════════════════════════════╝
set -e

APP_DIR="/opt/noc-sentinel-v38"
SERVICE="ARBAMonitoringV38"
VENV="$APP_DIR/backend/venv"
[ -d "$APP_DIR/backend/.venv" ] && VENV="$APP_DIR/backend/.venv"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'; BOLD='\033[1m'
ok()   { echo -e "  ${G}✔ $*${N}"; }
warn() { echo -e "  ${Y}⚠ $*${N}"; }
err()  { echo -e "\n${R}${BOLD}✗ ERROR: $*${N}\n"; exit 1; }
step() { echo -e "\n${BOLD}${B}▶ $*${N}"; }

[[ $EUID -ne 0 ]] && err "Jalankan sebagai root: sudo bash install.sh"
[[ ! -d "$APP_DIR/.git" ]] && err "Direktori $APP_DIR tidak ditemukan. Clone dulu:\n  git clone https://github.com/afani-arba/noc-sentinel-v38.git $APP_DIR"

echo -e "\n${BOLD}${B}╔════════════════════════════════════════════╗${N}"
echo -e "${BOLD}${B}║     NOC Sentinel v3.8 — Install/Update     ║${N}"
echo -e "${BOLD}${B}╚════════════════════════════════════════════╝${N}"
echo -e "  Waktu  : $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  Commit : $(git -C $APP_DIR rev-parse --short HEAD 2>/dev/null || echo '?')"

# ── STEP 1: Stop ─────────────────────────────────────────────────────────────
step "[1/5] Stop Backend..."
systemctl stop "$SERVICE" 2>/dev/null || true
sleep 2
set +e; fuser -k 8080/tcp 2>/dev/null; set -e
ok "Backend stopped"

# ── STEP 2: Git Pull ──────────────────────────────────────────────────────────
step "[2/5] Git Pull..."
cd "$APP_DIR"
BEFORE=$(git rev-parse --short HEAD)
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || warn "Git pull gagal"
AFTER=$(git rev-parse --short HEAD)
[[ "$BEFORE" != "$AFTER" ]] && ok "Updated: $BEFORE → $AFTER" || warn "Tidak ada update baru"

# ── STEP 3: Python packages ────────────────────────────────────────────────────
step "[3/5] Python packages..."

[[ ! -f "$VENV/bin/pip" ]] && python3 -m venv "$VENV" && ok "venv dibuat"

"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q

ok "Python packages selesai"

# ── STEP 4: Build Frontend ─────────────────────────────────────────────────────
step "[4/5] Build Frontend..."
cd "$APP_DIR/frontend"
npm install --legacy-peer-deps --prefer-offline -q 2>/dev/null || npm install --legacy-peer-deps -q
npm run build
[[ -f "build/index.html" ]] && ok "Frontend build OK" || err "Build failed"

# ── STEP 5: Systemd + Nginx ───────────────────────────────────────────────────
step "[5/5] Start Backend..."

# Buat service file jika belum ada
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
if [[ ! -f "$SERVICE_FILE" ]]; then
cat > "$SERVICE_FILE" <<SVCEOF
[Unit]
Description=NOC Sentinel v3.8 Backend (FastAPI)
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}/backend
Environment="PATH=${APP_DIR}/backend/venv/bin"
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8080 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE}
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
SVCEOF
ok "Service file dibuat: $SERVICE_FILE"
fi

# Buat nginx config jika belum ada
NGINX_CONF="/etc/nginx/sites-available/nocsentinel-v38"
if [[ ! -f "$NGINX_CONF" ]]; then
    SERVER_HOST=$(hostname -I | awk '{print $1}')
cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 1755;
    server_name _;

    gzip on;
    gzip_types text/plain application/json application/javascript text/css;

    root ${APP_DIR}/frontend/build;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }

    location ~* \.(js|css|png|jpg|ico|woff|woff2|ttf|svg)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    access_log /var/log/nginx/nocsentinel_v38_access.log;
    error_log  /var/log/nginx/nocsentinel_v38_error.log;
}
NGINXEOF
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/nocsentinel-v38
nginx -t && systemctl reload nginx
ok "Nginx v38 config dibuat (port 1755)"
fi

# .env check
ENV_FILE="$APP_DIR/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    [[ -f "$APP_DIR/backend/.env.example" ]] && cp "$APP_DIR/backend/.env.example" "$ENV_FILE" && warn ".env dibuat dari .env.example — edit sesuai kebutuhan"
fi

systemctl daemon-reload
systemctl enable "$SERVICE" --quiet
systemctl start "$SERVICE"
sleep 5

systemctl is-active --quiet "$SERVICE" \
    && ok "Backend '$SERVICE': RUNNING ✔" \
    || { journalctl -u "$SERVICE" -n 30 --no-pager; exit 1; }

systemctl reload nginx 2>/dev/null && ok "Nginx di-reload" || true
sleep 2
curl -sf http://localhost:8080/api/health 2>/dev/null | grep -q "ok" \
    && ok "API health: OK ✔" \
    || warn "API belum respond — cek: journalctl -u $SERVICE -n 20"

echo ""
echo -e "${G}${BOLD}╔════════════════════════════════════════════╗${N}"
echo -e "${G}${BOLD}║   ✅  NOC SENTINEL v3.8 SIAP!              ║${N}"
echo -e "${G}${BOLD}╚════════════════════════════════════════════╝${N}"
echo ""
echo -e "  Commit  : $(git -C $APP_DIR log -1 --format='%h — %s')"
echo -e "  Backend : port 8080 (service: $SERVICE)"
echo -e "  Frontend: port 1755 (nginx)"
echo -e "  Waktu   : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
