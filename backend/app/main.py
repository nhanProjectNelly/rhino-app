from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.routers import auth_router, lists_router, gallery_router, predict_router, crop_router


def _add_missing_columns(sync_conn):
    """Add columns that may be missing on existing DBs."""
    from sqlalchemy import text
    dialect = sync_conn.engine.dialect.name
    # description_source on rhino_images
    try:
        if dialect == "postgresql":
            sync_conn.execute(text("ALTER TABLE rhino_images ADD COLUMN IF NOT EXISTS description_source VARCHAR(16)"))
        else:
            sync_conn.execute(text("ALTER TABLE rhino_images ADD COLUMN description_source VARCHAR(16)"))
    except Exception:
        pass
    for col_sql in (
        "ALTER TABLE rhino_images ADD COLUMN review_status VARCHAR(32) DEFAULT 'draft'",
        "ALTER TABLE rhino_images ADD COLUMN review_reason VARCHAR(64)",
        "ALTER TABLE prediction_records ADD COLUMN source_image_id INTEGER REFERENCES rhino_images(id)",
        "ALTER TABLE prediction_records ADD COLUMN review_status VARCHAR(32)",
        "ALTER TABLE prediction_records ADD COLUMN review_reason VARCHAR(64)",
    ):
        try:
            if dialect == "postgresql" and "ADD COLUMN" in col_sql:
                col_sql = col_sql.replace("ADD COLUMN ", "ADD COLUMN IF NOT EXISTS ")
            sync_conn.execute(text(col_sql))
        except Exception:
            pass
    # is_active on rhino_identities and rhino_images
    for table in ("rhino_identities", "rhino_images"):
        try:
            if dialect == "postgresql":
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true"))
            else:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN is_active BOOLEAN DEFAULT 1"))
        except Exception:
            pass
    # rhino_images: parent_image_id, source_stem (capture grouping + re-crop)
    for col_sql in (
        "ALTER TABLE rhino_images ADD COLUMN parent_image_id INTEGER REFERENCES rhino_images(id)",
        "ALTER TABLE rhino_images ADD COLUMN source_stem VARCHAR(256)",
    ):
        try:
            sync_conn.execute(text(col_sql))
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
    yield
    await engine.dispose()


app = FastAPI(
    title="Rhino ReID App",
    description="Rhino gallery management, image description (o4-mini), re-identify and confirm identities",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(lists_router.router)
app.include_router(gallery_router.router)
app.include_router(predict_router.router)
app.include_router(crop_router.router)

if settings.UPLOAD_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="uploads")


@app.get("/")
def root():
    return {"app": "Rhino ReID", "docs": "/docs"}
