#!/bin/bash
# NOC Sentinel v3 — Create First Admin User
# Usage: sudo bash scripts/create-admin.sh

APP_DIR="/opt/noc-sentinel-v3"
cd "$APP_DIR/backend"
source venv/bin/activate

python3.11 - <<'PYEOF'
import asyncio, uuid, os, sys
from datetime import datetime, timezone

# Load .env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "backend" / ".env" if False else ".env")

from core.db import init_db, get_db
from passlib.context import CryptContext

init_db()
db = get_db()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

print("\n=== NOC Sentinel v3 — Buat Admin User ===\n")
username = input("Username [admin]: ").strip() or "admin"
password = input("Password: ").strip()
full_name = input("Full Name [Administrator]: ").strip() or "Administrator"

if not password:
    print("❌ Password tidak boleh kosong!")
    sys.exit(1)

async def run():
    existing = await db.users.find_one({"username": username})
    if existing:
        print(f"⚠  User '{username}' sudah ada!")
        overwrite = input("Overwrite password? (y/N): ").strip().lower()
        if overwrite == "y":
            await db.users.update_one(
                {"username": username},
                {"$set": {"password": pwd_ctx.hash(password), "role": "administrator"}}
            )
            print(f"✅ Password user '{username}' diperbarui.")
        return

    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "username": username,
        "password": pwd_ctx.hash(password),
        "full_name": full_name,
        "role": "administrator",
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    print(f"\n✅ Admin user '{username}' berhasil dibuat!")
    print(f"   → Login di: http://localhost/")

asyncio.run(run())
PYEOF

deactivate
