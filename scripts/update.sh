#!/bin/bash
# NOC Sentinel v3 — Update Script
# Usage (after uploading new files): sudo bash scripts/update.sh

set -e
APP_DIR="/opt/noc-sentinel-v3"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'

echo -e "${BOLD}🔄 Updating NOC Sentinel v3...${NC}"

# Rebuild frontend
echo -e "${YELLOW}→ Building frontend...${NC}"
cd "$APP_DIR/frontend"
npm install --silent
npm run build
echo -e "${GREEN}✓ Frontend built${NC}"

# Update Python packages
echo -e "${YELLOW}→ Updating Python packages...${NC}"
cd "$APP_DIR/backend"
source venv/bin/activate
pip install -r requirements.txt -q
deactivate
echo -e "${GREEN}✓ Python packages updated${NC}"

# Fix permissions
chown -R www-data:www-data "$APP_DIR/backend"
chmod -R 755 "$APP_DIR/frontend/build"

# Reload systemd dan restart service
systemctl daemon-reload
systemctl restart nocsentinel
sleep 2

echo -e "${GREEN}${BOLD}✅ Update selesai!${NC}"
systemctl status nocsentinel --no-pager -l
