#!/usr/bin/env python3
"""Import rhino_split (identity folders per split) + descriptions_four_parts.json into DB.

No ATRW rename. Keys in JSON match merge_four_part_descriptions.py:
  "IdentityFolder/image_stem" -> { body, head, left_ear, right_ear }

Usage:
  python migrate_split_four_parts.py \\
    --split-root ../../IndivAID/data/rhino_split \\
    --descriptions ../../IndivAID/Rhino_photos/high_quality_cropped_parts/descriptions_four_parts.json \\
    --splits train query gallery
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import engine, AsyncSessionLocal, Base
from app.models import RhinoList, RhinoIdentity, RhinoImage

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _to_db_parts(entry: dict) -> dict[str, str]:
    return {
        "left_ear": str(entry.get("left_ear") or ""),
        "right_ear": str(entry.get("right_ear") or ""),
        "head": str(entry.get("head") or ""),
        "body": str(entry.get("body") or ""),
    }


def lookup_four_parts(desc: dict, identity: str, stem: str) -> dict[str, str] | None:
    for k in (f"{identity}/{stem}", stem, f"{identity}\\{stem}"):
        v = desc.get(k)
        if isinstance(v, dict) and all(x in v for x in ("body", "head", "left_ear", "right_ear")):
            return _to_db_parts(v)
    suffix = f"/{stem}"
    for key, v in desc.items():
        if not isinstance(key, str) or not isinstance(v, dict):
            continue
        if key == stem or key.endswith(suffix):
            if all(x in v for x in ("body", "head", "left_ear", "right_ear")):
                return _to_db_parts(v)
    return None


async def run_migrate(
    db: AsyncSession,
    split_root: Path,
    desc: dict,
    splits: list[str],
    list_name: str,
    dry_run: bool,
) -> dict:
    split_root = split_root.resolve()
    src_path = str(split_root)

    r = await db.execute(
        select(RhinoList).where(RhinoList.list_type == "images", RhinoList.source_path == src_path)
    )
    rlist = r.scalar_one_or_none()
    if not dry_run:
        if not rlist:
            rlist = RhinoList(name=list_name, list_type="images", source_path=src_path)
            db.add(rlist)
            await db.flush()
    else:
        class D:
            id = 0

        rlist = D()

    idents: dict[str, RhinoIdentity] = {}
    stats = {"images": 0, "with_desc": 0}

    out_base = settings.UPLOAD_DIR / "from_split"
    if not dry_run:
        out_base.mkdir(parents=True, exist_ok=True)

    for sp in splits:
        d = split_root / sp
        if not d.is_dir():
            continue
        for id_dir in sorted(p for p in d.iterdir() if p.is_dir()):
            ident_name = id_dir.name
            if not dry_run:
                if ident_name not in idents:
                    q = await db.execute(
                        select(RhinoIdentity).where(
                            RhinoIdentity.list_id == rlist.id,
                            RhinoIdentity.name == ident_name,
                        )
                    )
                    ex = q.scalar_one_or_none()
                    if not ex:
                        ex = RhinoIdentity(list_id=rlist.id, name=ident_name, pid=None, is_active=True)
                        db.add(ex)
                        await db.flush()
                    idents[ident_name] = ex
                ident = idents[ident_name]
            for img in sorted(id_dir.iterdir()):
                if not img.is_file() or img.suffix.lower() not in IMAGE_EXT:
                    continue
                stem = img.stem
                safe_id = ident_name.replace("/", "_").replace(" ", "_")
                rel = f"from_split/{sp}/{safe_id}/{stem}{img.suffix.lower()}"
                parts = lookup_four_parts(desc, ident_name, stem)
                if dry_run:
                    has_desc = parts and any((v or "").strip() for v in parts.values())
                    print(f"{sp}/{ident_name}/{img.name} -> .../{rel} desc={'yes' if has_desc else 'no'}")
                    stats["images"] += 1
                    if has_desc:
                        stats["with_desc"] += 1
                    continue
                dest = settings.UPLOAD_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                q2 = await db.execute(select(RhinoImage).where(RhinoImage.file_path == rel))
                if q2.scalar_one_or_none():
                    continue
                shutil.copy2(img, dest)
                img_row = RhinoImage(
                    identity_id=ident.id,
                    file_path=rel,
                    part_type=None,
                    confirmed=True,
                    is_active=True,
                    description_parts=parts,
                    description_schema={"split_four_parts": True, "split": sp, "base_key": f"{ident_name}/{stem}"},
                    description_source="four_parts_import"
                    if parts and any((v or "").strip() for v in parts.values())
                    else None,
                )
                db.add(img_row)
                stats["images"] += 1
                if parts and any(parts.values()):
                    stats["with_desc"] += 1

    return stats


async def amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split-root", type=Path, required=True)
    ap.add_argument("--descriptions", type=Path, required=True)
    ap.add_argument("--splits", nargs="+", default=["train", "query", "gallery"])
    ap.add_argument("--list-name", default="rhino_split")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.descriptions, encoding="utf-8") as f:
        desc = json.load(f)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        try:
            stats = await run_migrate(db, args.split_root, desc, args.splits, args.list_name, args.dry_run)
            if not args.dry_run:
                await db.commit()
        except Exception:
            await db.rollback()
            raise
    print("Done:", stats)


if __name__ == "__main__":
    asyncio.run(amain())
