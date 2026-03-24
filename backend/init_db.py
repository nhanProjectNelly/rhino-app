"""Create DB and default user (run once). Default admin account: username=admin, password=admin.
Also runs auto-migration from IndivAID/Rhino_photos/high_quality into assets (list + identities + images).

Fresh Re-ID test DB:
  python init_db.py --reset --no-high-quality
  python sync_reid_test_data.py --atrw-root ../../IndivAID/data/rhino_atrw_format ...
"""
import argparse
import asyncio
from app.database import engine, Base, AsyncSessionLocal
from app.models import User
from app.auth import get_password_hash
from app.services.init_high_quality import migrate_high_quality_to_assets


def _add_description_source(sync_conn):
    """Add description_source column if missing (SQLite or PostgreSQL)."""
    from sqlalchemy import text
    dialect = sync_conn.engine.dialect.name
    try:
        if dialect == "postgresql":
            sync_conn.execute(text("ALTER TABLE rhino_images ADD COLUMN IF NOT EXISTS description_source VARCHAR(16)"))
        else:
            sync_conn.execute(text("ALTER TABLE rhino_images ADD COLUMN description_source VARCHAR(16)"))
    except Exception:
        pass


def _add_is_active_columns(sync_conn):
    """Add is_active to rhino_identities and rhino_images if missing."""
    from sqlalchemy import text
    dialect = sync_conn.engine.dialect.name
    for table, col in [("rhino_identities", "is_active"), ("rhino_images", "is_active")]:
        try:
            if dialect == "postgresql":
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT true"))
            else:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} BOOLEAN DEFAULT 1"))
        except Exception:
            pass


async def init(*, reset: bool = False, no_high_quality: bool = False):
    async with engine.begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_description_source)
        await conn.run_sync(_add_is_active_columns)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        r = await db.execute(select(User).where(User.username == "admin"))
        existing = r.scalar_one_or_none()
        if existing is None:
            u = User(username="admin", hashed_password=get_password_hash("admin"), role="admin")
            db.add(u)
            await db.commit()
            print("Created user admin / admin")
        else:
            if getattr(existing, "role", "user") != "admin":
                existing.role = "admin"
                await db.commit()
                print("User admin existed; promoted role to admin")
            else:
                print("User admin already exists")

        if not no_high_quality:
            try:
                out = await migrate_high_quality_to_assets(db)
                await db.commit()
                if out.get("skipped"):
                    print("High-quality init:", out.get("reason", "skipped"))
                else:
                    print(
                        "High-quality init: list_id=%s, identities=%s, images=%s (source=%s)"
                        % (
                            out.get("list_id"),
                            out.get("identities", 0),
                            out.get("images", 0),
                            out.get("source", ""),
                        )
                    )
            except Exception as e:
                print("High-quality init failed:", e)
                await db.rollback()
        else:
            print("Skipped high-quality init (--no-high-quality)")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Init DB + default admin")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop all tables then recreate (wipes data; admin recreated)",
    )
    parser.add_argument(
        "--no-high-quality",
        action="store_true",
        help="Do not import IndivAID high_quality into DB",
    )
    a = parser.parse_args()
    asyncio.run(init(reset=a.reset, no_high_quality=a.no_high_quality))
