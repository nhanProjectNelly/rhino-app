#!/usr/bin/env python3
"""Sync IndivAID high_quality_cropped + high_quality_cropped_parts into rhino_app DB.

Creates one RhinoImage anchor per full-frame file in ``high_quality_cropped/<identity>/*.jpg``
(source_stem = filename stem). Part crops in ``high_quality_cropped_parts`` link via
``parent_image_id`` and share ``source_stem``. Optional ``descriptions_four_parts.json``
fills anchor descriptions and an initial active RhinoDescriptionVersion.

Usage (from rhino_app/backend):

  python migrate_sync_hq_cropped.py \\
    --cropped-root ../../IndivAID/Rhino_photos/high_quality_cropped \\
    --parts-root ../../IndivAID/Rhino_photos/high_quality_cropped_parts \\
    --descriptions ../../IndivAID/Rhino_photos/high_quality_cropped_parts/descriptions_four_parts.json

  python migrate_sync_hq_cropped.py --cropped-root /path/to/cropped --parts-root /path/to/parts --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import RhinoList, RhinoIdentity, RhinoImage, RhinoDescriptionVersion

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PART_STEM_RE = re.compile(r"^(.+)_(left_ear|right_ear|head|body)(?:_\d+|_fallback)?$", re.IGNORECASE)
PART_KEYS = ("left_ear", "right_ear", "head", "body")


def _rhino_name_from_folder(folder_name: str) -> str:
    s = folder_name.strip()
    if re.match(r"^\d+$", s):
        return f"ID{s}"
    return s


def _pid_from_folder(folder_name: str) -> int | None:
    m = re.search(r"\d+", folder_name)
    return int(m.group()) if m else None


def load_descriptions(path: Path | None) -> dict:
    if not path or not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dict_to_parts(v: dict) -> dict[str, str] | None:
    if not isinstance(v, dict):
        return None
    if not {*PART_KEYS} <= set(v.keys()):
        return None
    return {k: str(v.get(k) or "") for k in PART_KEYS}


def lookup_desc(desc_map: dict, identity_name: str, stem: str) -> dict[str, str] | None:
    for k in (f"{identity_name}/{stem}", stem):
        v = desc_map.get(k)
        if isinstance(v, dict):
            p = dict_to_parts(v)
            if p and any(p.values()):
                return p
    suffix = f"/{stem}"
    for key, v in desc_map.items():
        if isinstance(v, dict) and isinstance(key, str) and (key == stem or key.endswith(suffix)):
            p = dict_to_parts(v)
            if p and any(p.values()):
                return p
    return None


async def run(
    db: AsyncSession,
    cropped_root: Path,
    parts_root: Path,
    descriptions: dict,
    list_name: str,
    dry_run: bool,
    skip_existing: bool,
) -> dict:
    cropped_root = cropped_root.resolve()
    parts_root = parts_root.resolve()
    if not cropped_root.is_dir():
        raise SystemExit(f"cropped root not found: {cropped_root}")
    if not parts_root.is_dir():
        raise SystemExit(f"parts root not found: {parts_root}")

    q = select(RhinoList).where(RhinoList.name == list_name, RhinoList.list_type == "high_quality")
    rl = (await db.execute(q)).scalar_one_or_none()
    if not rl:
        rl = RhinoList(name=list_name, list_type="high_quality", source_path=str(cropped_root))
        db.add(rl)
        await db.flush()

    gallery_dir = settings.UPLOAD_DIR / "gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)

    anchors_created = parts_created = skipped = 0

    for subdir in sorted(cropped_root.iterdir()):
        if not subdir.is_dir():
            continue
        folder_name = subdir.name
        rhino_name = _rhino_name_from_folder(folder_name)
        pid = _pid_from_folder(folder_name)

        q = select(RhinoIdentity).where(RhinoIdentity.list_id == rl.id, RhinoIdentity.name == rhino_name)
        ident = (await db.execute(q)).scalar_one_or_none()
        if not ident:
            ident = RhinoIdentity(list_id=rl.id, name=rhino_name, pid=pid, is_active=True)
            db.add(ident)
            await db.flush()

        stem_to_anchor: dict[str, RhinoImage] = {}

        for f in sorted(subdir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXT:
                continue
            stem = f.stem
            base, ptype = stem, None
            m = PART_STEM_RE.match(stem)
            if m:
                base, ptype = m.group(1), m.group(2).lower()
            if ptype:
                continue
            q_img = await db.execute(
                select(RhinoImage).where(
                    RhinoImage.identity_id == ident.id,
                    RhinoImage.source_stem == stem,
                    RhinoImage.part_type.is_(None),
                )
            )
            existing = q_img.scalar_one_or_none()
            if existing and skip_existing:
                stem_to_anchor[stem] = existing
                skipped += 1
                continue
            if existing:
                stem_to_anchor[stem] = existing
                continue

            ext = f.suffix or ".jpg"
            dest_name = f"sync_{ident.id}_{uuid.uuid4().hex}{ext}"
            dest_path = gallery_dir / dest_name
            if dry_run:
                stem_to_anchor[stem] = True  # type: ignore
                anchors_created += 1
                continue
            shutil.copy2(f, dest_path)
            rel = f"gallery/{dest_name}"
            desc_parts = lookup_desc(descriptions, rhino_name, stem)
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
                description_parts=desc_parts,
                description_schema=schema,
                description_source="import" if desc_parts else None,
            )
            db.add(img)
            await db.flush()
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
            stem_to_anchor[stem] = img
            anchors_created += 1

        parts_sub = parts_root / folder_name
        if not parts_sub.is_dir():
            continue

        for f in sorted(parts_sub.iterdir()):
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXT:
                continue
            stem_full = f.stem
            m = PART_STEM_RE.match(stem_full)
            if not m:
                continue
            base_stem, ptype = m.group(1), m.group(2).lower()
            anchor = stem_to_anchor.get(base_stem)
            anchor_id = None
            if anchor is True:
                anchor_id = 0
            elif anchor is not None and getattr(anchor, "id", None):
                anchor_id = anchor.id
            if anchor_id is None:
                q2 = await db.execute(
                    select(RhinoImage).where(
                        RhinoImage.identity_id == ident.id,
                        RhinoImage.source_stem == base_stem,
                        RhinoImage.part_type.is_(None),
                    )
                )
                anchor = q2.scalar_one_or_none()
                if anchor:
                    anchor_id = anchor.id
            if anchor_id is None:
                continue

            if not dry_run and anchor is not None and getattr(anchor, "id", None):
                ex = (
                    await db.execute(
                        select(RhinoImage).where(
                            RhinoImage.identity_id == ident.id,
                            RhinoImage.source_stem == base_stem,
                            RhinoImage.part_type == ptype,
                            RhinoImage.parent_image_id == anchor.id,
                        )
                    )
                ).scalar_one_or_none()
                if ex and skip_existing:
                    skipped += 1
                    continue
                if ex:
                    continue

            ext = f.suffix or ".jpg"
            dest_name = f"sync_{ident.id}_{uuid.uuid4().hex}{ext}"
            dest_path = gallery_dir / dest_name
            if dry_run:
                parts_created += 1
                continue
            assert anchor is not None and getattr(anchor, "id", None)
            shutil.copy2(f, dest_path)
            rel = f"gallery/{dest_name}"
            part_img = RhinoImage(
                identity_id=ident.id,
                file_path=rel,
                part_type=ptype,
                parent_image_id=anchor.id,
                source_stem=base_stem,
                confirmed=True,
            )
            db.add(part_img)
            parts_created += 1

    if dry_run:
        await db.rollback()
    return {
        "list_id": rl.id,
        "anchors_created": anchors_created,
        "parts_created": parts_created,
        "skipped": skipped,
        "dry_run": dry_run,
    }


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cropped-root", type=Path, required=True)
    ap.add_argument("--parts-root", type=Path, required=True)
    ap.add_argument("--descriptions", type=Path, default=None)
    ap.add_argument("--list-name", default="high_quality_cropped_sync")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
    desc = load_descriptions(args.descriptions)
    async with AsyncSessionLocal() as db:
        try:
            out = await run(
                db,
                args.cropped_root,
                args.parts_root,
                desc,
                args.list_name,
                args.dry_run,
                args.skip_existing,
            )
            if not args.dry_run:
                await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
