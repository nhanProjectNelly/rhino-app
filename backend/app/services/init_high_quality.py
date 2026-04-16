"""Init-time migrations from IndivAID data into rhino_app DB.

We support two sources under ``IndivAID/Rhino_photos``:
- ``high_quality_cropped`` + ``high_quality_cropped_parts`` (preferred): already-cropped anchors + 4 part crops.
  If a four-part description JSON exists, we seed description fields + an active version.
- ``high_quality`` (fallback): full-frame images only (no part crops).

All migrations are designed to be idempotent: if a matching list/source already exists, we skip.
"""
import re
import shutil
import uuid
from pathlib import Path

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RhinoList, RhinoIdentity, RhinoImage, RhinoDescriptionVersion

# Under IndivAID root: Rhino_photos/high_quality/
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

PART_KEYS = ("left_ear", "right_ear", "head", "body")
PART_STEM_RE = re.compile(r"^(.+)_(left_ear|right_ear|head|body)(?:_\d+|_fallback)?$", re.IGNORECASE)


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


def _high_quality_cropped_root() -> Path:
    return settings.indivaid_root / "Rhino_photos" / "high_quality_cropped"


def _high_quality_cropped_parts_root() -> Path:
    return settings.indivaid_root / "Rhino_photos" / "high_quality_cropped_parts"


def _load_four_parts_descriptions(path: Path | None) -> dict:
    """Load IndivAID-style descriptions_four_parts.json if present."""
    if not path or not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dict_to_parts(v: dict) -> dict[str, str] | None:
    if not isinstance(v, dict):
        return None
    if not {*PART_KEYS} <= set(v.keys()):
        return None
    out = {k: str(v.get(k) or "") for k in PART_KEYS}
    return out if any(x.strip() for x in out.values()) else None


def _lookup_desc(desc_map: dict, identity_name: str, stem: str) -> dict[str, str] | None:
    """Try {Identity/stem}, then {stem}, then any key ending with /stem."""
    for k in (f"{identity_name}/{stem}", stem):
        v = desc_map.get(k)
        if isinstance(v, dict):
            p = _dict_to_parts(v)
            if p:
                return p
    suffix = f"/{stem}"
    for key, v in desc_map.items():
        if isinstance(key, str) and key.endswith(suffix) and isinstance(v, dict):
            p = _dict_to_parts(v)
            if p:
                return p
    return None


async def migrate_high_quality_cropped_to_assets(
    db: AsyncSession,
    *,
    list_name: str = "high_quality_cropped",
    skip_existing: bool = True,
) -> dict:
    """
    Preferred init migration:
    - Source: IndivAID/Rhino_photos/high_quality_cropped/<identity>/*.jpg
    - Parts:  IndivAID/Rhino_photos/high_quality_cropped_parts/<identity>/*_{part}.jpg
    - Optional: descriptions_four_parts.json under parts root
    """
    cropped_root = _high_quality_cropped_root()
    parts_root = _high_quality_cropped_parts_root()
    if not cropped_root.is_dir() or not parts_root.is_dir():
        return {
            "skipped": True,
            "reason": f"cropped source missing: {cropped_root} or parts missing: {parts_root}",
        }

    # Already initialized for this cropped_root?
    q = select(RhinoList).where(
        RhinoList.list_type == "high_quality",
        RhinoList.source_path == str(cropped_root),
    )
    existing = (await db.execute(q)).scalar_one_or_none()
    if existing:
        return {"skipped": True, "reason": "high_quality_cropped already initialized", "list_id": existing.id}

    desc_path = parts_root / "descriptions_four_parts.json"
    descriptions = _load_four_parts_descriptions(desc_path if desc_path.exists() else None)

    gallery_dir = settings.UPLOAD_DIR / "gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)

    rl = RhinoList(name=list_name, list_type="high_quality", source_path=str(cropped_root))
    db.add(rl)
    await db.flush()

    identities_created = 0
    anchors_created = 0
    parts_created = 0
    rows_skipped = 0
    versions_created = 0

    # Map stem -> anchor row id (for linking part crops)
    for subdir in sorted(cropped_root.iterdir()):
        if not subdir.is_dir():
            continue
        folder_name = subdir.name
        rhino_name = _rhino_name_from_folder(folder_name)
        pid = _pid_from_folder(folder_name)

        qid = select(RhinoIdentity).where(RhinoIdentity.list_id == rl.id, RhinoIdentity.name == rhino_name)
        ident = (await db.execute(qid)).scalar_one_or_none()
        if not ident:
            ident = RhinoIdentity(list_id=rl.id, name=rhino_name, pid=pid, is_active=True)
            db.add(ident)
            await db.flush()
            identities_created += 1

        stem_to_anchor: dict[str, RhinoImage] = {}

        for f in sorted(subdir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = f.stem
            base, ptype = stem, None
            m = PART_STEM_RE.match(stem)
            if m:
                base, ptype = m.group(1), m.group(2).lower()
            if ptype:
                # Ignore part crops accidentally present in cropped_root
                continue

            q_img = select(RhinoImage).where(
                RhinoImage.identity_id == ident.id,
                RhinoImage.source_stem == stem,
                RhinoImage.part_type.is_(None),
            )
            existing_img = (await db.execute(q_img)).scalar_one_or_none()
            if existing_img:
                stem_to_anchor[stem] = existing_img
                if skip_existing:
                    rows_skipped += 1
                continue

            ext = f.suffix or ".jpg"
            dest_name = f"hqcrop_{ident.id}_{uuid.uuid4().hex}{ext}"
            dest_path = gallery_dir / dest_name
            shutil.copy2(f, dest_path)
            rel = f"gallery/{dest_name}"

            desc_parts = _lookup_desc(descriptions, rhino_name, stem)
            schema = None
            if desc_parts:
                schema = {"descriptions_four_parts": {k: {"text": desc_parts[k]} for k in PART_KEYS}}

            img = RhinoImage(
                identity_id=ident.id,
                file_path=rel,
                part_type=None,
                parent_image_id=None,
                source_stem=stem,
                confirmed=True,
                is_active=True,
                description_parts=desc_parts,
                description_schema=schema,
                description_source="import" if desc_parts else None,
            )
            db.add(img)
            await db.flush()
            stem_to_anchor[stem] = img
            anchors_created += 1

            if desc_parts:
                ver = RhinoDescriptionVersion(
                    anchor_image_id=img.id,
                    description_parts=desc_parts,
                    description_schema=schema,
                    label="import",
                    is_active=True,
                    created_from_version_id=None,
                )
                db.add(ver)
                versions_created += 1

        # Parts for this identity
        # IndivAID layout is usually: high_quality_cropped_parts/<part_type>/<identity>/*.jpg
        for ptype in ("left_ear", "right_ear", "head", "body"):
            parts_sub = parts_root / ptype / folder_name
            if not parts_sub.is_dir():
                continue
            for f in sorted(parts_sub.iterdir()):
                if not f.is_file() or f.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                m = PART_STEM_RE.match(f.stem)
                if not m:
                    continue
                base_stem, ptype_from_name = m.group(1), m.group(2).lower()
                # Prefer filename part type (more reliable than folder name)
                ptype_eff = ptype_from_name or ptype

                anchor = stem_to_anchor.get(base_stem)
                if not anchor:
                    # Anchor existed before this run: fetch it
                    q_anchor = select(RhinoImage).where(
                        RhinoImage.identity_id == ident.id,
                        RhinoImage.source_stem == base_stem,
                        RhinoImage.part_type.is_(None),
                    )
                    anchor = (await db.execute(q_anchor)).scalar_one_or_none()
                    if not anchor:
                        continue

                # Skip if part row already exists
                q_part = select(RhinoImage).where(
                    RhinoImage.identity_id == ident.id,
                    RhinoImage.source_stem == base_stem,
                    RhinoImage.part_type == ptype_eff,
                    RhinoImage.parent_image_id == anchor.id,
                )
                existing_part = (await db.execute(q_part)).scalar_one_or_none()
                if existing_part:
                    if skip_existing:
                        rows_skipped += 1
                    continue

                ext = f.suffix or ".jpg"
                dest_name = f"hqcrop_{ident.id}_{uuid.uuid4().hex}{ext}"
                dest_path = gallery_dir / dest_name
                shutil.copy2(f, dest_path)
                rel = f"gallery/{dest_name}"
                part_img = RhinoImage(
                    identity_id=ident.id,
                    file_path=rel,
                    part_type=ptype_eff,
                    parent_image_id=anchor.id,
                    source_stem=base_stem,
                    confirmed=True,
                    is_active=True,
                )
                db.add(part_img)
                parts_created += 1

    return {
        "list_id": rl.id,
        "identities": identities_created,
        "images": int(anchors_created + parts_created),
        "anchors_created": anchors_created,
        "parts_created": parts_created,
        "description_versions_created": versions_created,
        "skipped_rows": rows_skipped,
        "source": str(cropped_root),
        "parts_source": str(parts_root),
        "descriptions_path": str(desc_path) if desc_path.exists() else None,
    }


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
