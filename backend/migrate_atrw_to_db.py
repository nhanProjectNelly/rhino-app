#!/usr/bin/env python3
"""Import IndivAID rhino_atrw_format (train/query/gallery) into rhino_app DB.

Copies images to uploads/gallery/atrw/{split}_{pid}_{camid}_{index}.ext, creates RhinoList + RhinoIdentity per pid,
RhinoImage rows. Optional JSON: descriptions_four_parts.json (body, head, left_ear, right_ear) or legacy ATRW stem keys.

Usage (from rhino_app/backend, .env loaded):

  python migrate_atrw_to_db.py \\
    --atrw-root ../../IndivAID/data/rhino_atrw_format \\
    --descriptions ../../IndivAID/.../descriptions_four_parts.json

  python migrate_atrw_to_db.py --atrw-root /path/to/rhino_atrw_format --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

# Run as script: ensure backend is on path
_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import engine, AsyncSessionLocal, Base
from app.models import RhinoList, RhinoIdentity, RhinoImage

ATRW_STEM_RE = re.compile(r"^(-?\d+)_(-?\d+)_(\d+)$")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLIT_NAMES = ("train", "query", "gallery")


def pid_to_display_name(split_root: Path | None) -> dict[int, str]:
    """Map ATRW pid -> identity folder name (same ordering as prepare_atrw_from_rhino)."""
    if not split_root or not split_root.is_dir():
        return {}
    names: set[str] = set()
    for sp in SPLIT_NAMES:
        d = split_root / sp
        if not d.is_dir():
            continue
        for c in d.iterdir():
            if c.is_dir():
                names.add(c.name)
    if not names:
        return {}
    ordered = sorted(names)
    return {idx: ordered[idx] for idx in range(len(ordered))}


def parse_atrw_filename(path: Path) -> tuple[int, int, int, str] | None:
    """Return (pid, camid, index, suffix) or None."""
    m = ATRW_STEM_RE.match(path.stem)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), path.suffix.lower() or ".jpg"


def load_descriptions(path: Path | None) -> dict:
    if not path or not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dict_to_description_parts(v: dict) -> dict[str, str] | None:
    """Normalize descriptions_four_parts.json or flat four-key dict to DB shape."""
    if not isinstance(v, dict):
        return None
    keys = set(v.keys())
    need = {"left_ear", "right_ear", "head", "body"}
    if not need <= keys:
        return None
    return {
        "left_ear": str(v.get("left_ear") or ""),
        "right_ear": str(v.get("right_ear") or ""),
        "head": str(v.get("head") or ""),
        "body": str(v.get("body") or ""),
    }


def lookup_description(desc_map: dict, split: str, stem: str) -> dict[str, str] | None:
    """Try split/stem, stem, then keys ending with /stem (four_parts base keys)."""
    for k in (f"{split}/{stem}", stem):
        v = desc_map.get(k)
        if isinstance(v, dict):
            out = _dict_to_description_parts(v)
            if out:
                return out
    suffix = f"/{stem}"
    for key, v in desc_map.items():
        if isinstance(v, dict) and isinstance(key, str) and (key == stem or key.endswith(suffix)):
            out = _dict_to_description_parts(v)
            if out and any(out.values()):
                return out
    return None


async def migrate(
    db: AsyncSession,
    atrw_root: Path,
    splits: list[str],
    descriptions: dict,
    list_name: str,
    dry_run: bool,
    skip_existing: bool,
    pid_names: dict[int, str],
) -> dict:
    atrw_root = atrw_root.resolve()
    if not atrw_root.is_dir():
        raise SystemExit(f"ATRW root not found: {atrw_root}")

    out_dir = settings.UPLOAD_DIR / "atrw"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Collect pids from all files
    pids: set[int] = set()
    files_by_split: dict[str, list[Path]] = {}
    for split in splits:
        d = atrw_root / split
        if not d.is_dir():
            continue
        files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT)
        files_by_split[split] = files
        for p in files:
            parsed = parse_atrw_filename(p)
            if parsed:
                pids.add(parsed[0])

    if not pids:
        raise SystemExit(f"No ATRW-named images (*_camid_index) under {atrw_root}/{{{','.join(splits)}}}")

    n_files = sum(len(files_by_split[s]) for s in files_by_split)
    if dry_run:
        print(f"[dry-run] atrw_root={atrw_root} splits={splits} pids={len(pids)} files={n_files}")
        for split, files in files_by_split.items():
            for src in files:
                parsed = parse_atrw_filename(src)
                if parsed:
                    print(f"  {split}/{src.name} -> pid {parsed[0]}")
        return {
            "dry_run": True,
            "identities": len(pids),
            "files": n_files,
        }

    result = await db.execute(
        select(RhinoList).where(
            RhinoList.list_type == "images",
            RhinoList.source_path == str(atrw_root),
        )
    )
    rlist = result.scalar_one_or_none()
    if not rlist:
        rlist = RhinoList(
            name=list_name,
            list_type="images",
            source_path=str(atrw_root),
        )
        db.add(rlist)
        await db.flush()

    pid_to_identity: dict[int, RhinoIdentity] = {}
    for pid in sorted(pids):
        q = await db.execute(
            select(RhinoIdentity).where(
                RhinoIdentity.list_id == rlist.id,
                RhinoIdentity.pid == pid,
            )
        )
        ident = q.scalar_one_or_none()
        display = pid_names.get(pid) or f"ATRW pid {pid}"
        if not ident:
            ident = RhinoIdentity(
                list_id=rlist.id,
                name=display,
                pid=pid,
                is_active=True,
            )
            db.add(ident)
            await db.flush()
        elif ident.name.startswith("ATRW pid ") and pid in pid_names:
            ident.name = display
        pid_to_identity[pid] = ident

    stats = {"identities": len(pids), "images_created": 0, "images_skipped": 0, "images_updated": 0}

    for split, files in files_by_split.items():
        for src in files:
            parsed = parse_atrw_filename(src)
            if not parsed:
                print(f"[skip] bad name: {src.name}")
                continue
            pid, camid, idx, suf = parsed
            stem = src.stem
            dest_name = f"{split}_{stem}{suf}"
            rel = f"atrw/{dest_name}"

            ident = pid_to_identity[pid]
            q = await db.execute(select(RhinoImage).where(RhinoImage.file_path == rel))
            existing = q.scalar_one_or_none()

            if existing and skip_existing:
                stats["images_skipped"] += 1
                continue

            dest_abs = settings.UPLOAD_DIR / rel
            shutil.copy2(src, dest_abs)

            desc_parts = lookup_description(descriptions, split, stem)

            meta = {
                "atrw_migrated": True,
                "split": split,
                "stem": stem,
                "camid": camid,
                "index": idx,
            }

            if existing:
                existing.description_parts = desc_parts or existing.description_parts
                existing.description_schema = meta
                existing.description_source = "atrw_import"
                stats["images_updated"] += 1
            else:
                img = RhinoImage(
                    identity_id=ident.id,
                    file_path=rel,
                    part_type=None,
                    confirmed=True,
                    is_active=True,
                    description_parts=desc_parts,
                    description_schema=meta,
                    description_source="atrw_import" if desc_parts else None,
                )
                db.add(img)
                stats["images_created"] += 1

    return stats


async def amain() -> None:
    ap = argparse.ArgumentParser(description="Migrate IndivAID rhino_atrw_format into rhino_app DB")
    ap.add_argument("--atrw-root", type=Path, required=True, help="e.g. IndivAID/data/rhino_atrw_format")
    ap.add_argument(
        "--descriptions",
        type=Path,
        default=None,
        help="JSON keyed by stem (or split/stem): { left_ear, right_ear, head, body }",
    )
    ap.add_argument("--splits", nargs="+", default=["train", "query", "gallery"])
    ap.add_argument("--list-name", default="ATRW", help="RhinoList name")
    ap.add_argument(
        "--split-source",
        type=Path,
        default=None,
        help="Original rhino_split root (pre-ATRW) to recover identity folder names per pid",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip DB rows whose file_path already exists (no copy overwrite for skipped)",
    )
    args = ap.parse_args()

    desc_map = load_descriptions(args.descriptions)
    pid_names = pid_to_display_name(args.split_source)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        try:
            stats = await migrate(
                db,
                args.atrw_root,
                args.splits,
                desc_map,
                args.list_name,
                args.dry_run,
                args.skip_existing,
                pid_names,
            )
            if not args.dry_run:
                await db.commit()
        except Exception:
            await db.rollback()
            raise

    print("Done:", stats)


if __name__ == "__main__":
    asyncio.run(amain())
