"""
NOC-Sentinel Backend - Modular Entry Point (v3.0)
v3: Added Wall Display, SLA Monitoring, Incident Management, Audit Log,
    Top Talkers, Heatmap features.

Structure:
  core/       - db singleton, auth helpers, polling loop
  routers/    - one file per feature domain
  services/   - business logic (notifications, backups)
  syslog_server.py - UDP syslog receiver
"""
import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

# ── Bootstrap ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ── DB must init before routers import ────────────────────────────────────
from core.db import init_db
init_db()

# ── Import routers ─────────────────────────────────────────────────────────
from fastapi import APIRouter
from routers.auth import router as auth_router
from routers.devices import router as devices_router
from routers.pppoe import router as pppoe_router
from routers.hotspot import router as hotspot_router
from routers.reports import router as reports_router
from routers.admin import router as admin_router
from routers.system import router as system_router
from routers.notifications import router as notifications_router
from routers.backups import router as backups_router
from routers.syslog import router as syslog_router
from routers.metrics import router as metrics_router
from routers.routing import router as routing_router
from routers.firewall import router as firewall_router
from routers.genieacs import router as genieacs_router
from routers.customers import router as customers_router
from routers.billing import router as billing_router
from routers.wallboard import router as wallboard_router
from routers.sla import router as sla_router
from routers.incidents import router as incidents_router
from routers.audit import router as audit_router

# ── App factory ────────────────────────────────────────────────────────────
app = FastAPI(title="NOC-Sentinel API", version="3.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers under /api prefix
api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(devices_router)
api.include_router(pppoe_router)
api.include_router(hotspot_router)
api.include_router(reports_router)
api.include_router(admin_router)
api.include_router(system_router)
api.include_router(notifications_router)
api.include_router(backups_router)
api.include_router(syslog_router)
api.include_router(metrics_router)
api.include_router(routing_router)
api.include_router(firewall_router)
api.include_router(genieacs_router)
api.include_router(customers_router)
api.include_router(billing_router)
api.include_router(wallboard_router)
api.include_router(sla_router)
api.include_router(incidents_router)
api.include_router(audit_router)
app.include_router(api)

# ── Lifecycle ──────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("NOC-Sentinel v3.0 starting up...")

    # Start device polling background task
    from core.polling import polling_loop
    asyncio.create_task(polling_loop())
    logger.info("Polling loop started")

    # Start UDP syslog server
    loop = asyncio.get_event_loop()
    from syslog_server import start_syslog_server
    await start_syslog_server(loop)

    logger.info("NOC-Sentinel ready!")


@app.on_event("shutdown")
async def shutdown():
    from core.db import close_db
    close_db()
    logger.info("NOC-Sentinel shutdown")


@app.get("/")
async def root():
    return {"status": "ok", "service": "NOC-Sentinel", "version": "3.0.0"}
