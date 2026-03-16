# NOC Sentinel v3 — Panduan Instalasi Ubuntu Server 20.04

> **Target Server:** Ubuntu Server 20.04 LTS (Focal Fossa)  
> **Nama Server:** `jimmy`  
> **Aplikasi:** NOC Sentinel v3 (FastAPI + React + MongoDB)

---

## 📋 Daftar Isi

1. [Persiapan Server](#1-persiapan-server)
2. [Instalasi Dependency Sistem](#2-instalasi-dependency-sistem)
3. [Instalasi MongoDB](#3-instalasi-mongodb)
4. [Instalasi Node.js (Frontend Build)](#4-instalasi-nodejs)
5. [Instalasi Python 3.11](#5-instalasi-python-311)
6. [Upload & Setup Aplikasi](#6-upload--setup-aplikasi)
7. [Konfigurasi Environment (.env)](#7-konfigurasi-environment-env)
8. [Build Frontend](#8-build-frontend)
9. [Konfigurasi Backend (Systemd Service)](#9-konfigurasi-backend-systemd-service)
10. [Konfigurasi Nginx (Reverse Proxy)](#10-konfigurasi-nginx)
11. [SSL dengan Let's Encrypt (Opsional)](#11-ssl-dengan-lets-encrypt-opsional)
12. [Firewall & Keamanan](#12-firewall--keamanan)
13. [Membuat Admin User](#13-membuat-admin-user)
14. [Update & Maintenance](#14-update--maintenance)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Persiapan Server

### Login ke server
```bash
ssh jimmy@<IP_SERVER_UBUNTU>
# Atau jika menggunakan password root:
ssh root@<IP_SERVER_UBUNTU>
```

### Update sistem dulu
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git unzip build-essential software-properties-common
```

### Buat user khusus aplikasi (opsional tapi direkomendasikan)
```bash
sudo useradd -m -s /bin/bash nocsentinel
sudo usermod -aG sudo nocsentinel
su - nocsentinel
```

---

## 2. Instalasi Dependency Sistem

```bash
# Tools SNMP
sudo apt install -y snmp snmpd net-tools iputils-ping

# Library Python
sudo apt install -y libssl-dev libffi-dev python3-dev
sudo apt install -y pkg-config

# Nginx
sudo apt install -y nginx

# Certbot (untuk HTTPS, opsional)
sudo apt install -y certbot python3-certbot-nginx
```

---

## 3. Instalasi MongoDB

MongoDB 6.x di Ubuntu 20.04:

```bash
# Import MongoDB GPG key
curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor

# Tambah repo
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
  https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/6.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list

# Install
sudo apt update
sudo apt install -y mongodb-org

# Enable & Start
sudo systemctl enable mongod
sudo systemctl start mongod

# Verifikasi
sudo systemctl status mongod
```

### Buat database dan user MongoDB
```bash
mongosh
```

Di dalam shell MongoDB:
```javascript
use nocsentinel

db.createUser({
  user: "nocsentinel",
  pwd: "GANTI_PASSWORD_KUAT",   // ← ganti ini
  roles: [{ role: "readWrite", db: "nocsentinel" }]
})

exit
```

### Aktifkan autentikasi MongoDB
```bash
sudo nano /etc/mongod.conf
```

Tambahkan/ubah bagian security:
```yaml
security:
  authorization: enabled
```

```bash
sudo systemctl restart mongod
```

---

## 4. Instalasi Node.js

Node.js v20 (untuk build frontend React):

```bash
# Install NVM (Node Version Manager)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Reload shell
source ~/.bashrc

# Install Node.js 20
nvm install 20
nvm use 20
nvm alias default 20

# Verifikasi
node --version   # v20.x.x
npm --version    # 10.x.x
```

---

## 5. Instalasi Python 3.11

Ubuntu 20.04 default Python adalah 3.8. Kita perlu Python 3.11:

```bash
# Tambah deadsnakes PPA
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils

# Install pip untuk Python 3.11
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

# Verifikasi
python3.11 --version   # Python 3.11.x
```

---

## 6. Upload & Setup Aplikasi

### Clone dari GitHub

```bash
# Clone repository ke direktori /opt
sudo git clone https://github.com/afani-arba/noc-sentinel.git /opt/noc-sentinel-v3

# Atur ownership ke user aktif
sudo chown -R $USER:$USER /opt/noc-sentinel-v3

cd /opt/noc-sentinel-v3
```

> **Update aplikasi di kemudian hari:**
> ```bash
> cd /opt/noc-sentinel-v3
> git pull origin main
> sudo bash scripts/update.sh
> ```

### Setup Python Virtual Environment (Backend)
```bash
cd /opt/noc-sentinel-v3/backend

# Buat virtual environment
python3.11 -m venv venv

# Aktifkan
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install semua dependency
pip install -r requirements.txt

# Deaktifkan venv
deactivate
```

---

## 7. Konfigurasi Environment (.env)

```bash
cd /opt/noc-sentinel-v3/backend
cp .env.example .env 2>/dev/null || touch .env
nano .env
```

Isi file `.env`:
```dotenv
# ============================================================
# NOC Sentinel v3 — Environment Configuration
# ============================================================

# --- Database ---
MONGO_URI=mongodb://nocsentinel:GANTI_PASSWORD_KUAT@localhost:27017/nocsentinel
MONGO_DB_NAME=nocsentinel

# --- Security ---
# Buat secret key kuat: python3.11 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=GANTI_DENGAN_SECRET_KEY_ACAK_PANJANG

# --- CORS (frontend URL) ---
# Jika menggunakan domain: CORS_ORIGINS=https://noc.domainanda.com
# Jika menggunakan IP:
CORS_ORIGINS=http://<IP_SERVER>

# --- Service Name ---
NOC_SERVICE_NAME=ARBA Monitoring

# --- Syslog Server (UDP receiver) ---
SYSLOG_HOST=0.0.0.0
SYSLOG_PORT=514

# --- InfluxDB (opsional, untuk time-series metrics) ---
INFLUXDB_URL=
INFLUXDB_TOKEN=
INFLUXDB_ORG=
INFLUXDB_BUCKET=

# --- GenieACS (opsional, untuk TR-069 CPE management) ---
GENIEACS_URL=
GENIEACS_USERNAME=
GENIEACS_PASSWORD=

# --- WhatsApp Notification (opsional) ---
WA_API_URL=
WA_API_TOKEN=
```

Simpan file (`Ctrl+X`, `Y`, `Enter`).

### Generate SECRET_KEY
```bash
python3.11 -c "import secrets; print(secrets.token_hex(32))"
# Salin output dan ganti di .env
```

---

## 8. Build Frontend

```bash
cd /opt/noc-sentinel-v3/frontend

# Install npm dependencies
npm install

# Build production
npm run build

# Hasil build ada di folder: /opt/noc-sentinel-v3/frontend/build
ls -la build/
```

---

## 9. Konfigurasi Backend (Systemd Service)

### Buat systemd service file
```bash
sudo nano /etc/systemd/system/nocsentinel.service
```

Isi:
```ini
[Unit]
Description=NOC Sentinel v3 Backend (FastAPI)
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/noc-sentinel-v3/backend
Environment="PATH=/opt/noc-sentinel-v3/backend/venv/bin"
ExecStart=/opt/noc-sentinel-v3/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nocsentinel

# Permissions untuk syslog UDP port 514 (butuh cap_net_bind_service)
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
```

### Atur ownership file
```bash
sudo chown -R www-data:www-data /opt/noc-sentinel-v3/backend
```

### Aktifkan dan start service
```bash
sudo systemctl daemon-reload
sudo systemctl enable nocsentinel
sudo systemctl start nocsentinel

# Cek status
sudo systemctl status nocsentinel

# Cek log
sudo journalctl -u nocsentinel -f
```

---

## 10. Konfigurasi Nginx

### Buat konfigurasi Nginx
```bash
sudo nano /etc/nginx/sites-available/nocsentinel
```

Isi (mode HTTP dulu, HTTPS bisa ditambah nanti):
```nginx
server {
    listen 80;
    server_name <IP_SERVER_ATAU_DOMAIN>;   # ← ganti ini

    # Gzip compression
    gzip on;
    gzip_types text/plain application/json application/javascript text/css;
    gzip_min_length 1000;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Frontend: serve static React build
    root /opt/noc-sentinel-v3/frontend/build;
    index index.html;

    # React SPA routing (semua route ke index.html)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Backend API reverse proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;

        # Upload size untuk backup files
        client_max_body_size 50M;
    }

    # Static file caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Logs
    access_log /var/log/nginx/nocsentinel_access.log;
    error_log  /var/log/nginx/nocsentinel_error.log;
}
```

### Aktifkan konfigurasi
```bash
# Enable site
sudo ln -sf /etc/nginx/sites-available/nocsentinel /etc/nginx/sites-enabled/

# Hapus default site bawaan Nginx
sudo rm -f /etc/nginx/sites-enabled/default

# Test konfigurasi
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## 11. SSL dengan Let's Encrypt (Opsional)

> Hanya berlaku jika server memiliki **domain name** yang mengarah ke IP server ini.

```bash
# Install certbot
sudo apt install -y certbot python3-certbot-nginx

# Request sertifikat SSL
sudo certbot --nginx -d noc.domainanda.com

# Certbot akan otomatis modifikasi nginx config
# Renewal otomatis — test renewal:
sudo certbot renew --dry-run
```

---

## 12. Firewall & Keamanan

```bash
# Aktifkan UFW
sudo ufw enable

# Allow SSH (wajib, jangan sampai terkunci!)
sudo ufw allow 22/tcp

# Allow HTTP & HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow Syslog UDP (dari MikroTik ke server)
sudo ufw allow 514/udp

# Cek status
sudo ufw status verbose
```

### Amankan MongoDB (jangan expose ke internet)
```bash
# Pastikan MongoDB hanya mendengarkan localhost
sudo grep bindIp /etc/mongod.conf
# Harus: bindIp: 127.0.0.1
```

---

## 13. Membuat Admin User Pertama

Setelah service berjalan, buat user admin via API:

```bash
curl -X POST http://localhost:8000/api/auth/setup \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "AdminPassword123!",
    "full_name": "Administrator",
    "role": "administrator"
  }'
```

> ⚠️ Endpoint `/api/auth/setup` biasanya hanya bisa dipakai saat belum ada user. Cek `routers/auth.py` untuk endpoint yang tersedia.

Alternatif — langsung via MongoDB shell:
```bash
mongosh "mongodb://nocsentinel:GANTI_PASSWORD_KUAT@localhost:27017/nocsentinel"
```

```javascript
// Di dalam mongosh
const bcrypt = require('crypto'); // tidak ada, pakai Python dibawah
```

Via Python langsung:
```bash
cd /opt/noc-sentinel-v3/backend
source venv/bin/activate

python3.11 - <<'EOF'
import asyncio
from core.db import init_db, get_db
from passlib.context import CryptContext
import uuid
from datetime import datetime, timezone

init_db()
db = get_db()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_admin():
    existing = await db.users.find_one({"username": "admin"})
    if existing:
        print("User admin sudah ada!")
        return
    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "username": "admin",
        "password": pwd_ctx.hash("AdminPassword123!"),
        "full_name": "Administrator",
        "role": "administrator",
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    print("✅ Admin user berhasil dibuat!")

asyncio.run(create_admin())
EOF

deactivate
```

---

## 14. Update & Maintenance

### Update kode dari Windows ke server
```powershell
# Di Windows — sinkron ulang file yang berubah
scp -r E:\NOC\noc-sentinel-v3\backend jimmy@<IP>:/opt/noc-sentinel-v3/
scp -r E:\NOC\noc-sentinel-v3\frontend jimmy@<IP>:/opt/noc-sentinel-v3/
```

### Script update otomatis di server
```bash
sudo nano /opt/update-nocsentinel.sh
```

Isi:
```bash
#!/bin/bash
set -e
echo "🔄 Updating NOC Sentinel v3..."

# Rebuild frontend
cd /opt/noc-sentinel-v3/frontend
npm install --silent
npm run build

# Update Python dependencies
cd /opt/noc-sentinel-v3/backend
source venv/bin/activate
pip install -r requirements.txt -q
deactivate

# Fix permissions
sudo chown -R www-data:www-data /opt/noc-sentinel-v3/backend

# Restart service
sudo systemctl restart nocsentinel

echo "✅ Update selesai!"
sudo systemctl status nocsentinel --no-pager
```

```bash
chmod +x /opt/update-nocsentinel.sh
```

### Perintah maintenance harian
```bash
# Cek status semua service
sudo systemctl status nocsentinel mongod nginx

# Lihat log backend real-time
sudo journalctl -u nocsentinel -f --lines=50

# Lihat log Nginx
sudo tail -f /var/log/nginx/nocsentinel_error.log

# Cek koneksi MongoDB
mongosh "mongodb://nocsentinel:PASSWORD@localhost:27017/nocsentinel" --eval "db.devices.countDocuments()"

# Backup database MongoDB
mongodump --uri="mongodb://nocsentinel:PASSWORD@localhost:27017/nocsentinel" \
  --out=/backup/nocsentinel_$(date +%Y%m%d)
```

---

## 15. Troubleshooting

### Backend tidak start
```bash
sudo journalctl -u nocsentinel -n 100 --no-pager
# Biasanya masalah: .env salah, MongoDB belum jalan, atau port 8000 sudah dipakai
```

### API tidak bisa diakses dari browser
```bash
# Cek apakah backend berjalan
curl http://localhost:8000/
# Expected: {"status":"ok","service":"NOC-Sentinel","version":"3.0.0"}

# Cek Nginx
sudo nginx -t
sudo systemctl status nginx
```

### MongoDB connection error
```bash
# Cek MongoDB jalan
sudo systemctl status mongod

# Test koneksi dengan credentials
mongosh "mongodb://nocsentinel:PASSWORD@localhost:27017/nocsentinel"

# Cek MONGO_URI di .env sudah benar
cat /opt/noc-sentinel-v3/backend/.env | grep MONGO
```

### Frontend tidak muncul (blank page)
```bash
# Pastikan build sudah ada
ls /opt/noc-sentinel-v3/frontend/build/

# Rebuild jika perlu
cd /opt/noc-sentinel-v3/frontend
npm run build

# Cek nginx root path
cat /etc/nginx/sites-available/nocsentinel | grep root
```

### SNMP tidak bisa poll device
```bash
# Test SNMP dari server ke device
snmpwalk -v2c -c public <IP_MIKROTIK> 1.3.6.1.2.1.1.1.0

# Pastikan port SNMP tidak diblokir firewall server
sudo ufw status | grep 161
```

### Port 514 (Syslog) belum bisa digunakan tanpa root
```bash
# Cek apakah service mendapat izin CAP_NET_BIND_SERVICE
sudo systemctl show nocsentinel | grep CapabilityBoundingSet

# Alternatif: ubah syslog ke port >1024 di .env
SYSLOG_PORT=5140

# Dan di ufw:
sudo ufw allow 5140/udp
```

---

## ✅ Verifikasi Instalasi

```bash
# 1. Backend API
curl http://localhost:8000/
# → {"status":"ok","version":"3.0.0"}

# 2. Nginx + Frontend
curl http://<IP_SERVER>/
# → HTML halaman React app

# 3. API via Nginx
curl http://<IP_SERVER>/api/
# → JSON response dari FastAPI

# 4. MongoDB
mongosh "mongodb://nocsentinel:PASSWORD@localhost:27017/nocsentinel" \
  --eval "db.runCommand({ping:1})"
# → { ok: 1 }

# 5. Semua service
sudo systemctl is-active nocsentinel mongod nginx
# → active active active
```

---

## 📁 Struktur Direktori di Server

```
/opt/noc-sentinel-v3/
├── backend/
│   ├── venv/               ← Python virtual environment
│   ├── .env                ← Konfigurasi (JANGAN share!)
│   ├── server.py
│   ├── requirements.txt
│   ├── core/
│   ├── routers/
│   └── services/
└── frontend/
    ├── build/              ← Hasil npm run build (di-serve Nginx)
    ├── src/
    └── package.json
```

---

## 🔗 URL Akses

| Service | URL |
|---------|-----|
| Dashboard | `http://<IP_SERVER>/` |
| API Docs | `http://<IP_SERVER>/api/docs` |
| API Root | `http://<IP_SERVER>/api/` |
| Wall Display | `http://<IP_SERVER>/wallboard` |

---

*Panduan ini dibuat untuk NOC Sentinel v3 — ARBA Monitoring System*
