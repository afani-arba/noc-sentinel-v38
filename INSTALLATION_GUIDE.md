# NOC-SENTINEL - Panduan Instalasi & Deployment

## MikroTik Monitoring Tool v2.3

---

## Daftar Isi

1. [Persyaratan Sistem](#1-persyaratan-sistem)
2. [Persyaratan MikroTik](#2-persyaratan-mikrotik)
3. [Instalasi di Ubuntu Server](#3-instalasi-di-ubuntu-server)
4. [Konfigurasi Backend](#4-konfigurasi-backend)
5. [Konfigurasi Frontend](#5-konfigurasi-frontend)
6. [Setup MongoDB](#6-setup-mongodb)
7. [Menjalankan Aplikasi](#7-menjalankan-aplikasi)
8. [Setup Nginx Reverse Proxy](#8-setup-nginx-reverse-proxy)
9. [Setup SSL dengan Let's Encrypt](#9-setup-ssl-dengan-lets-encrypt)
10. [Setup Systemd Service](#10-setup-systemd-service)
11. [Kredensial Default](#11-kredensial-default)
12. [Troubleshooting](#12-troubleshooting)
13. [Struktur Proyek](#13-struktur-proyek)

---

## 1. Persyaratan Sistem

### Hardware Minimum
- CPU: 2 Core
- RAM: 2 GB
- Disk: 20 GB SSD
- Network: Koneksi internet stabil

### Software
- Ubuntu 20.04 / 22.04 / 24.04 LTS
- Python 3.11+
- Node.js 18+ & Yarn
- MongoDB 6.0+
- Nginx (untuk reverse proxy)

---

## 2. Persyaratan MikroTik

### SNMP (Wajib untuk Monitoring)

Aplikasi ini menggunakan SNMP untuk monitoring real-time. Aktifkan SNMP di MikroTik:

```routeros
/snmp community
add name=public addresses=0.0.0.0/0 read-access=yes write-access=no

/snmp
set enabled=yes contact="" location="" trap-community=public
```

**Data yang diambil via SNMP:**
- CPU Load
- Memory Usage
- CPU Temperature
- Board Temperature
- Voltage
- Power Consumption
- Interface Traffic (Bandwidth)
- System Info (Identity, Model, ROS Version)

### RouterOS v7.1+ (REST API Mode)

Untuk RouterOS versi 7.1 ke atas, aktifkan REST API:

```routeros
/ip service
set www-ssl disabled=no port=443 certificate=*default
# ATAU tanpa SSL:
set www disabled=no port=80
```

**Konfigurasi di aplikasi:**
- API Mode: `REST API (RouterOS 7.1+)`
- Port: 443 (HTTPS) atau 80 (HTTP)
- SSL: Ya (untuk port 443)

### RouterOS v6.x (API Protocol Mode)

Untuk RouterOS versi 6.x, aktifkan API Protocol:

```routeros
/ip service
set api disabled=no port=8728
# ATAU dengan SSL:
set api-ssl disabled=no port=8729 certificate=*default
```

**Konfigurasi di aplikasi:**
- API Mode: `API Protocol (RouterOS 6.x+)`
- Port: 8728 (tanpa SSL) atau 8729 (dengan SSL)
- SSL: Tidak (untuk port 8728)

### Firewall (Opsional tapi Disarankan)

Izinkan akses dari server monitoring:

```routeros
/ip firewall filter
add chain=input src-address=IP_SERVER_MONITORING protocol=udp dst-port=161 action=accept comment="Allow SNMP"
add chain=input src-address=IP_SERVER_MONITORING protocol=tcp dst-port=8728,8729,443,80 action=accept comment="Allow API"
```

---

## 3. Instalasi di Ubuntu Server

### 3.1 Update Sistem

```bash
sudo apt update && sudo apt upgrade -y
```

### 3.2 Install Dependencies

```bash
# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip git curl wget

# Install Node.js 18 LTS
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install Yarn
npm install -g yarn

# Install Nginx
sudo apt install -y nginx
```

### 3.3 Install MongoDB

```bash
# Import MongoDB GPG key
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

# Add repository (Ubuntu 22.04)
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
  https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Install
sudo apt update
sudo apt install -y mongodb-org

# Start & Enable MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod

# Verifikasi
mongosh --eval "db.runCommand({ping:1})"
```

### 3.4 Clone / Upload Proyek

```bash
# Buat direktori aplikasi
sudo mkdir -p /opt/noc-sentinel
sudo chown $USER:$USER /opt/noc-sentinel

# Clone dari GitHub
git clone https://github.com/YOUR_USERNAME/noc-sentinel.git /opt/noc-sentinel

# ATAU upload manual via SCP
# scp -r ./app/* user@server:/opt/noc-sentinel/
```

---

## 4. Konfigurasi Backend

### 4.1 Setup Python Virtual Environment

```bash
cd /opt/noc-sentinel/backend

# Buat virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 4.2 Konfigurasi Environment Variables

```bash
# Edit file .env
nano /opt/noc-sentinel/backend/.env
```

Isi file `.env`:

```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=noc_sentinel
CORS_ORIGINS=https://yourdomain.com,http://localhost:3000
JWT_SECRET=GANTI_DENGAN_SECRET_KEY_YANG_KUAT_DAN_RANDOM
```

> **PENTING**: Ganti `JWT_SECRET` dengan string random yang kuat.
> Generate dengan: `openssl rand -hex 32`

### 4.3 Verifikasi Backend

```bash
cd /opt/noc-sentinel/backend
source venv/bin/activate

# Test jalankan
uvicorn server:app --host 0.0.0.0 --port 8001

# Buka browser: http://SERVER_IP:8001/api/health
# Harus menampilkan: {"status":"ok"}
# Tekan Ctrl+C untuk stop
```

---

## 5. Konfigurasi Frontend

### 5.1 Install Dependencies

```bash
cd /opt/noc-sentinel/frontend

# Install packages
yarn install
```

### 5.2 Konfigurasi Environment Variables

```bash
nano /opt/noc-sentinel/frontend/.env
```

Isi file `.env`:

```env
REACT_APP_BACKEND_URL=https://yourdomain.com
```

> Ganti `yourdomain.com` dengan domain atau IP server Anda.
> Jika belum ada domain, gunakan: `http://SERVER_IP`

### 5.3 Build Frontend untuk Production

```bash
cd /opt/noc-sentinel/frontend
yarn build
```

Hasil build akan tersimpan di folder `build/`.

---

## 6. Setup MongoDB

### 6.1 Buat Database & User (Opsional tapi Disarankan)

```bash
mongosh
```

```javascript
use noc_sentinel

db.createUser({
  user: "noc_admin",
  pwd: "PASSWORD_YANG_KUAT",
  roles: [{ role: "readWrite", db: "noc_sentinel" }]
})

exit
```

Jika menggunakan auth, update `.env` backend:

```env
MONGO_URL=mongodb://noc_admin:PASSWORD_YANG_KUAT@localhost:27017/noc_sentinel?authSource=noc_sentinel
```

### 6.2 Enable MongoDB Authentication (Opsional)

```bash
sudo nano /etc/mongod.conf
```

Tambahkan:

```yaml
security:
  authorization: enabled
```

```bash
sudo systemctl restart mongod
```

---

## 7. Menjalankan Aplikasi

### Quick Start (Development)

```bash
# Terminal 1 - Backend
cd /opt/noc-sentinel/backend
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2 - Frontend (development mode)
cd /opt/noc-sentinel/frontend
yarn start
```

### Production (lihat Section 8-10 untuk setup lengkap)

---

## 8. Setup Nginx Reverse Proxy

### 8.1 Buat Konfigurasi Nginx

```bash
sudo nano /etc/nginx/sites-available/noc-sentinel
```

Isi konfigurasi:

```nginx
server {
    listen 80;
    server_name yourdomain.com;  # Ganti dengan domain Anda

    # Frontend - serve static build
    root /opt/noc-sentinel/frontend/build;
    index index.html;

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    gzip_min_length 1000;

    # Backend API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 90;
    }

    # Frontend SPA routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 8.2 Aktifkan Konfigurasi

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/noc-sentinel /etc/nginx/sites-enabled/

# Hapus default site (opsional)
sudo rm /etc/nginx/sites-enabled/default

# Test konfigurasi
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## 9. Setup SSL dengan Let's Encrypt

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Generate SSL certificate
sudo certbot --nginx -d yourdomain.com

# Auto-renewal test
sudo certbot renew --dry-run
```

> SSL certificate akan di-renew otomatis oleh Certbot.

---

## 10. Setup Systemd Service

### 10.1 Backend Service

```bash
sudo nano /etc/systemd/system/noc-sentinel-backend.service
```

```ini
[Unit]
Description=NOC-Sentinel Backend API
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/noc-sentinel/backend
Environment=PATH=/opt/noc-sentinel/backend/venv/bin:/usr/bin
ExecStart=/opt/noc-sentinel/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --workers 4
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 10.2 Aktifkan Service

```bash
# Set permissions
sudo chown -R www-data:www-data /opt/noc-sentinel

# Reload systemd
sudo systemctl daemon-reload

# Start & enable backend
sudo systemctl start noc-sentinel-backend
sudo systemctl enable noc-sentinel-backend

# Cek status
sudo systemctl status noc-sentinel-backend
```

### 10.3 Perintah Manajemen

```bash
# Restart backend
sudo systemctl restart noc-sentinel-backend

# Lihat logs
sudo journalctl -u noc-sentinel-backend -f

# Stop
sudo systemctl stop noc-sentinel-backend
```

---

## 11. Kredensial Default

| Field    | Value      |
|----------|------------|
| Username | `admin`    |
| Password | `admin123` |
| Role     | Administrator |

> **PENTING**: Segera ganti password default setelah login pertama kali!
> Buka menu **Admin** > Edit user **admin** > Ganti password.

### Role & Hak Akses

| Role          | Dashboard | PPPoE | Hotspot | Reports | Devices | Admin |
|---------------|-----------|-------|---------|---------|---------|-------|
| Administrator | Lihat     | CRUD  | CRUD    | Generate| CRUD    | CRUD  |
| User          | Lihat     | CRU   | CRU     | Generate| Lihat   | -     |
| Viewer        | Lihat     | Lihat | Lihat   | Generate| Lihat   | -     |

---

## 12. Troubleshooting

### Backend tidak bisa start

```bash
# Cek logs
sudo journalctl -u noc-sentinel-backend -n 50

# Cek MongoDB running
sudo systemctl status mongod

# Cek port 8001 sudah digunakan
sudo lsof -i :8001

# Test koneksi MongoDB
mongosh --eval "db.runCommand({ping:1})"
```

### Frontend tidak tampil

```bash
# Pastikan build berhasil
cd /opt/noc-sentinel/frontend
yarn build

# Cek Nginx error log
sudo tail -n 50 /var/log/nginx/error.log

# Cek konfigurasi nginx
sudo nginx -t
```

### Login gagal

```bash
# Cek apakah seed data sudah berjalan
mongosh noc_sentinel --eval "db.admin_users.find().pretty()"

# Reset admin password (jalankan di server)
cd /opt/noc-sentinel/backend
source venv/bin/activate
python3 -c "
from passlib.context import CryptContext
pwd = CryptContext(schemes=['bcrypt'], deprecated='auto')
print(pwd.hash('admin123'))
"
# Copy hash lalu update di MongoDB:
# mongosh noc_sentinel --eval "db.admin_users.updateOne({username:'admin'}, {\$set:{password:'HASH_DISINI'}})"
```

### SNMP tidak dapat data

```bash
# Test SNMP dari server
snmpwalk -v2c -c public IP_MIKROTIK 1.3.6.1.2.1.1.1.0

# Pastikan SNMP enabled di MikroTik
/snmp print

# Cek firewall MikroTik
/ip firewall filter print where dst-port=161
```

### API MikroTik gagal koneksi

```bash
# Test koneksi API (RouterOS 7+)
curl -k -u admin:password https://IP_MIKROTIK/rest/system/resource

# Test koneksi API (RouterOS 6)
# Gunakan Winbox atau script Python dengan routeros-api library
```

### CORS Error

Pastikan `CORS_ORIGINS` di backend `.env` berisi domain frontend:

```env
CORS_ORIGINS=https://yourdomain.com,http://localhost:3000
```

### Port Firewall

```bash
# Buka port yang diperlukan
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 22/tcp    # SSH
sudo ufw enable
```

---

## 13. Struktur Proyek

```
noc-sentinel/
├── backend/
│   ├── server.py            # FastAPI application utama
│   ├── snmp_service.py      # SNMP polling & monitoring
│   ├── mikrotik_api.py      # MikroTik REST/API client
│   ├── requirements.txt     # Python dependencies
│   └── .env                 # Environment variables
│
├── frontend/
│   ├── src/
│   │   ├── App.js           # Router & Auth context
│   │   ├── lib/api.js       # Axios API helper
│   │   ├── components/
│   │   │   ├── Layout.jsx   # Sidebar & header layout
│   │   │   └── ui/          # Shadcn/UI components
│   │   └── pages/
│   │       ├── LoginPage.jsx       # Halaman login
│   │       ├── DashboardPage.jsx   # Dashboard monitoring
│   │       ├── PPPoEUsersPage.jsx  # Manajemen user PPPoE
│   │       ├── HotspotUsersPage.jsx# Manajemen user Hotspot
│   │       ├── ReportsPage.jsx     # Generate & export report
│   │       ├── DevicesPage.jsx     # Manajemen device
│   │       └── AdminPage.jsx       # Manajemen user admin
│   ├── package.json
│   └── .env
│
├── memory/
│   └── PRD.md              # Product Requirements Document
│
└── INSTALLATION_GUIDE.md   # Panduan ini
```

### Fitur Utama

| Fitur | Deskripsi |
|-------|-----------|
| Dashboard | Monitoring real-time: Traffic, Ping, Jitter, CPU, Memory, Temperature |
| PPPoE Users | CRUD user PPPoE via MikroTik API (dengan password) |
| Hotspot Users | CRUD user Hotspot via MikroTik API (dengan password) |
| Reports | Generate laporan harian/mingguan/bulanan, export PDF |
| Devices | Manajemen device MikroTik (SNMP + API) |
| Admin | Manajemen user aplikasi (3 role) |
| RouterOS Support | Mendukung RouterOS v6 (API) dan v7 (REST API) |

### API Endpoints

| Method | Endpoint                    | Deskripsi                      |
|--------|-----------------------------|--------------------------------|
| POST   | /api/auth/login             | Login & dapatkan JWT token     |
| GET    | /api/auth/me                | Info user yang sedang login    |
| GET    | /api/dashboard/stats        | Statistik dashboard            |
| GET    | /api/dashboard/interfaces   | Daftar interface per device    |
| GET    | /api/pppoe-users            | List PPPoE users               |
| POST   | /api/pppoe-users            | Tambah PPPoE user              |
| PUT    | /api/pppoe-users/:id        | Edit PPPoE user                |
| DELETE | /api/pppoe-users/:id        | Hapus PPPoE user               |
| GET    | /api/hotspot-users          | List Hotspot users             |
| POST   | /api/hotspot-users          | Tambah Hotspot user            |
| PUT    | /api/hotspot-users/:id      | Edit Hotspot user              |
| DELETE | /api/hotspot-users/:id      | Hapus Hotspot user             |
| GET    | /api/devices                | List devices                   |
| POST   | /api/devices                | Tambah device                  |
| PUT    | /api/devices/:id            | Edit device                    |
| DELETE | /api/devices/:id            | Hapus device                   |
| POST   | /api/devices/:id/poll       | Trigger SNMP poll              |
| POST   | /api/devices/test           | Test koneksi SNMP/API          |
| POST   | /api/reports/generate       | Generate report                |
| GET    | /api/admin/users            | List admin users               |
| POST   | /api/admin/users            | Tambah admin user              |
| PUT    | /api/admin/users/:id        | Edit admin user                |
| DELETE | /api/admin/users/:id        | Hapus admin user               |
| GET    | /api/health                 | Health check                   |

---

## Quick Start (TL;DR)

```bash
# 1. Clone repo
git clone https://github.com/YOUR_USERNAME/noc-sentinel.git
cd noc-sentinel

# 2. Setup backend
cd backend
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit sesuai kebutuhan

# 3. Setup frontend
cd ../frontend
yarn install
nano .env  # Set REACT_APP_BACKEND_URL
yarn build

# 4. Jalankan
cd ../backend
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8001

# 5. Buka browser: http://SERVER_IP:8001
#    Login: admin / admin123
```

---

## Changelog

### v2.3 (March 2026)
- Support RouterOS v6 (API Protocol) dan v7 (REST API)
- Extended System Health: CPU Temp, Board Temp, Voltage, Power
- Ping ke 8.8.8.8 untuk monitoring latency internet
- Password ditampilkan di tabel PPPoE & Hotspot
- Device dialog scrollable
- Interface selector dari SNMP data real
- Traffic History dengan timezone WIB

### v2.0 (March 2026)
- Migrasi dari mock data ke real SNMP monitoring
- Integrasi MikroTik REST API untuk CRUD users
- Dashboard dengan device & interface selector

### v1.0 (March 2026)
- Initial release dengan mock data
- UI Grafana-inspired dark theme

---

*NOC-SENTINEL v2.3 - MikroTik Monitoring Tool*
*Built with React + FastAPI + MongoDB*
