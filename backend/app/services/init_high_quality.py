"""Migrate IndivAID/Rhino_photos/high_quality into app: copy to uploads/gallery, create list + identities + images.
Subfolder name = identity id/name (e.g. "Boma ID5301" or "5301" -> "ID5301"). pid = numeric part if any.
"""
import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RhinoList, RhinoIdentity, RhinoImage

# Under IndivAID root: Rhino_photos/high_quality/
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _high_quality_source_root() -> Path:
    return settings.indivaid_root / "Rhino_photos" / "high_quality"


def _rhino_name_from_folder(folder_name: str) -> str:
    """Use subfolder name as rhino name. If purely numeric, format as 'ID{id}' (e.g. ID5301)."""
    s = folder_name.strip()
    if re.match(r"^\d+$", s):
        return f"ID{s}"
    return s


def _pid_from_folder(folder_name: str) -> int | None:
    """Extract numeric id from folder name (e.g. 5301 from 'Boma ID5301' or '5301')."""
    m = re.search(r"\d+", folder_name)
    return int(m.group()) if m else None


async def migrate_high_quality_to_assets(db: AsyncSession) -> dict:
    """
    If IndivAID/Rhino_photos/high_quality exists:
    - Create RhinoList 'high_quality' with source_path if not exists
    - For each subfolder: create RhinoIdentity (name e.g. "Boma ID5301", pid from folder)
    - Copy each image to uploads/gallery and create RhinoImage
    Returns { "list_id", "identities": N, "images": N } or {} if source missing/skip.
    """
    source = _high_quality_source_root()
    if not source.is_dir():
        return {"skipped": True, "reason": f"source not found: {source}"}

    # Already have a high_quality list with this source?
    result = await db.execute(
        select(RhinoList).where(
            RhinoList.list_type == "high_quality",
            RhinoList.source_path == str(source),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {"skipped": True, "reason": "high_quality list already initialized", "list_id": existing.id}

    gallery_dir = settings.UPLOAD_DIR / "gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)

    rl = RhinoList(
        name="high_quality",
        list_type="high_quality",
        source_path=str(source),
    )
    db.add(rl)
    await db.flush()

    identities_created = 0
    images_created = 0

    for subdir in sorted(source.iterdir()):
        if not subdir.is_dir():
            continue
        folder_name = subdir.name
        rhino_name = _rhino_name_from_folder(folder_name)
        pid = _pid_from_folder(folder_name)

        ident = RhinoIdentity(list_id=rl.id, name=rhino_name, pid=pid)
        db.add(ident)
        await db.flush()
        identities_created += 1

        for f in subdir.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                ext = f.suffix or ".jpg"
                dest_name = f"{ident.id}_{uuid.uuid4().hex}{ext}"
                dest_path = gallery_dir / dest_name
                shutil.copy2(f, dest_path)
                rel = f"gallery/{dest_name}"
                img = RhinoImage(
                    identity_id=ident.id,
                    file_path=rel,
                    part_type=None,
                    confirmed=True,
                )
                db.add(img)
                images_created += 1

    return {
        "list_id": rl.id,
        "identities": identities_created,
        "images": images_created,
        "source": str(source),
    }
