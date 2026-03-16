#!/bin/bash
# NOC-Sentinel Update Script
# Dijalankan otomatis oleh backend saat user klik "Update" di halaman Settings.
# Bisa juga dijalankan manual: bash /opt/noc-sentinel/update.sh

set -e

APP_DIR="/opt/noc-sentinel"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"
VENV_PIP="$BACKEND_DIR/venv/bin/pip"
SERVICE_NAME="noc-backend"

echo "[1/5] Git pull dari GitHub..."
cd "$APP_DIR"
git pull origin main

echo "[2/5] Install/update dependensi backend..."
"$VENV_PIP" install -r "$BACKEND_DIR/requirements.txt" -q --exists-action=i

echo "[3/5] Install/update dependensi frontend..."
cd "$FRONTEND_DIR"
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent

echo "[4/5] Build frontend..."
yarn build

echo "[5/5] Restart service $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME"

echo "=== Update selesai! ==="
