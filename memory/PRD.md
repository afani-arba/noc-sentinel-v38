# NOC-SENTINEL - MikroTik Monitoring Tool v2.4

## Problem Statement
MikroTik monitoring tool for Ubuntu server with real SNMP monitoring and MikroTik API integration supporting both RouterOS v6 (legacy API) and RouterOS v7 (REST API).

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn/UI + Recharts
- **Backend**: FastAPI + pysnmp (SNMP monitoring) + MikroTik API (REST & Legacy)
- **Database**: MongoDB (traffic history, device config, user management)
- **PDF Export**: jsPDF + jspdf-autotable
- **MikroTik API Factory**: Supports both RouterOS v6 (port 8728/8729) and v7 (port 443/80)
- **Ping**: ICMP with TCP fallback to port 161/8728/443

## What's Implemented (March 8, 2026)
- [x] Login page (JWT auth, 3 roles: administrator/viewer/user)
- [x] Dashboard: device selector, interface selector, real-time traffic/ping/jitter charts
- [x] PPPoE Users: CRUD via MikroTik API, device selector, search, online status, **password display**
- [x] Hotspot Users: CRUD via MikroTik API, device selector, search, online status, **password display**
- [x] Reports: daily/weekly/monthly from SNMP history, PDF export
- [x] Devices: SNMP + API config, test connection buttons, auto-polling, **scrollable dialog**, **custom port field**
- [x] Admin: user management with 3 roles
- [x] SNMP polling: background task every 30s, traffic history stored in MongoDB
- [x] All mock data REMOVED - 100% real data from MikroTik
- [x] **RouterOS v6/v7 Support**: API mode selector with flexible port configuration
- [x] **System Health Extended**: CPU/Memory Load, CPU Temp, Board Temp, Voltage, Power
- [x] **Device Info**: Identity, Board Name, ROS Version, Architecture
- [x] **Traffic History**: Time in WIB (UTC+7) timezone
- [x] **Ping & Jitter**: ICMP ping with TCP fallback, real-time graph
- [x] **Settings Page**: System settings and application update feature
- [x] **Update Feature**: Check and pull updates from GitHub repository

## Recent Changes (March 8, 2026)
### v2.4 Updates
1. **Device Port Configuration**: 
   - API Port field is now empty by default (not auto-filled)
   - Users can freely set custom port for REST API (RouterOS 7.1+)
   - Placeholder shows default port (443 for REST, 8728 for API)
   - SSL/TLS selection independent from port

2. **Memory Detection Enhancement**:
   - Added multiple methods to detect memory via SNMP
   - Method 1: Standard HR-MIB (Host Resources)
   - Method 2: MikroTik specific OID for memory index 65536
   - Method 3: Alternative hrStorageIndex 1

3. **Settings Page (New)**:
   - New "Pengaturan" menu item in navigation
   - Check for updates from GitHub
   - One-click update button (git pull + dependencies + rebuild)
   - System information display

## MikroTik Requirements
### RouterOS v7.1+ (REST API mode)
- REST API enabled (IP > Services > www-ssl atau www)
- **Port configurable**: Default 443 (HTTPS) or 80 (HTTP)
- User can set any custom port

### RouterOS v6.x+ (API Protocol mode)
- API enabled (IP > Services > api atau api-ssl)
- **Port configurable**: Default 8728 (tanpa SSL) atau 8729 (dengan SSL)
- User can set any custom port

### SNMP Requirements
- SNMP v2c enabled
- Extended SNMP OIDs for health metrics (temperature, voltage, power) require MikroTik-specific MIB

## Default Credentials
- Username: admin / Password: admin123

## Key Files
- `/app/frontend/src/pages/DevicesPage.jsx` - Device management with custom port
- `/app/frontend/src/pages/SettingsPage.jsx` - Settings & update page
- `/app/frontend/src/pages/DashboardPage.jsx` - Main dashboard
- `/app/backend/server.py` - Backend API including update endpoints
- `/app/backend/snmp_service.py` - SNMP polling with enhanced memory detection

## Backlog
### P0 (Critical)
- None

### P1 (High Priority)
- WebSocket for real-time dashboard updates
- Pagination for large user lists
- Automated installation script (install.sh) for self-hosted deployment

### P2 (Medium Priority)
- User activity audit logs
- Batch user import/export CSV
- Verify PDF report generation with real data
- Test user role permissions (Viewer, User restrictions)

### P3 (Low Priority)
- Email/Telegram alert notifications
