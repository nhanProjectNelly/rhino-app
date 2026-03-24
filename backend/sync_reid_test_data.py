#!/usr/bin/env python3
"""
Re-ID test layout (matches prepare_atrw rhino split):

1) uploads/reid_atrw/     — train/ + gallery/ + empty query/
2) uploads/reid_query_reference/ — copy of source query/*.jpg + README (NOT in DB)
3) DB                     — RhinoImage rows for train + gallery (query never imported)

**Full gallery (default):** After copying source gallery/, any pid in atrw_rhino_pid_names.json
missing from gallery/ gets one image copied from train/ (*_reid_full_gallery.jpg) so Re-ID
searches all 19 identities (objective retrieval). Use --no-full-gallery for the original
5-pid gallery-only eval split.

Already synced? Run:  python sync_reid_test_data.py --ensure-full-gallery-only

PID names: backend/data/atrw_rhino_pid_names.json. See docs/ATRW_RHINO_PID_TABLE.md.

Fresh DB (from rhino_app/backend):

  python init_db.py --reset --no-high-quality
  python sync_reid_test_data.py --atrw-root ../../IndivAID/data/rhino_atrw_format \\
    --descriptions ../../IndivAID/data/rhino_part_descriptions_four_atrw.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

_GALLERY_PID_RE = re.compile(r"(\d+)_-?\d+_\d+")

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.config import settings
from app.database import engine, AsyncSessionLocal, Base
from migrate_atrw_to_db import load_descriptions, migrate

_PID_JSON = _BACKEND / "data" / "atrw_rhino_pid_names.json"

QUERY_README = """# Query set (reference only — not in DB)

These images are copies of `rhino_atrw_format/query/*.jpg` for manual testing / evaluation.
They are **not** imported into rhino_app DB.

Eval gallery lives under `uploads/reid_atrw/gallery/`. Train under `reid_atrw/train/`.

See project docs: docs/ATRW_RHINO_PID_TABLE.md

Expected query pids: 2, 3, 4, 7, 8 (Donny, Ennex, Evan, Goat, Gordon).
"""


def load_fixed_pid_names() -> dict[int, str]:
    if not _PID_JSON.is_file():
        return {}
    with open(_PID_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): str(v) for k, v in raw.items()}


def _pid_from_jpg_stem(stem: str) -> int:
    m = _GALLERY_PID_RE.search(stem)
    return int(m.group(1)) if m else -1


def ensure_full_reid_gallery(gallery_dir: Path, train_dir: Path, expected_pids: set[int]) -> list[int]:
    """
    Re-ID retrieval is objective only if every identity appears in gallery/.
    Copy one train image per pid missing from gallery (default after sync).
    Returns sorted list of pids that were added from train.
    """
    if not gallery_dir.is_dir() or not train_dir.is_dir():
        return []
    in_gallery: set[int] = set()
    for p in gallery_dir.glob("*.jpg"):
        pid = _pid_from_jpg_stem(p.stem)
        if pid >= 0:
            in_gallery.add(pid)
    added: list[int] = []
    for pid in sorted(expected_pids - in_gallery):
        candidates = sorted(
            p for p in train_dir.glob("*.jpg") if _pid_from_jpg_stem(p.stem) == pid
        )
        if not candidates:
            print(f"WARNING: full-gallery: no train .jpg for pid {pid}, skip", file=sys.stderr)
            continue
        src = candidates[0]
        dest = gallery_dir / f"{src.stem}_reid_full_gallery{src.suffix}"
        shutil.copy2(src, dest)
        added.append(pid)
    return added


async def amain() -> None:
    ap = argparse.ArgumentParser(
        description="Sync ATRW: reid_atrw (train+gallery), query reference folder, DB train+gallery only"
    )
    ap.add_argument("--atrw-root", type=Path, required=True)
    ap.add_argument("--descriptions", type=Path, default=None)
    ap.add_argument("--skip-copy", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-name", default="Re-ID ATRW (train+gallery DB)")
    ap.add_argument(
        "--pid-names-json",
        type=Path,
        default=_PID_JSON,
        help="JSON object pid string -> display name (prepare_atrw order)",
    )
    ap.add_argument(
        "--no-full-gallery",
        action="store_true",
        help="Keep only rhino_atrw_format/gallery (small test split). Default: fill gallery with every pid from train so all 19 ids are searchable.",
    )
    ap.add_argument(
        "--ensure-full-gallery-only",
        action="store_true",
        help="Do not copy ATRW; only add missing pids from train/ into existing uploads/reid_atrw/gallery/.",
    )
    args = ap.parse_args()

    if args.ensure_full_gallery_only:
        dest = settings.UPLOAD_DIR / "reid_atrw"
        names = load_fixed_pid_names()
        if not names:
            raise SystemExit(f"Need {_PID_JSON} for pid list")
        added = ensure_full_reid_gallery(
            dest / "gallery", dest / "train", set(names.keys())
        )
        print(f"ensure-full-gallery-only: added pids {added} (total new files: {len(added)})")
        raise SystemExit(0)

    src = args.atrw_root.resolve()
    if not src.is_dir():
        raise SystemExit(f"ATRW root not found: {src}")
    for sub in ("train", "gallery", "query"):
        if not (src / sub).is_dir():
            raise SystemExit(f"Missing {src}/{sub}")

    dest = settings.UPLOAD_DIR / "reid_atrw"
    ref = settings.UPLOAD_DIR / "reid_query_reference"

    if not args.skip_copy and not args.dry_run:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        shutil.copytree(src / "train", dest / "train")
        shutil.copytree(src / "gallery", dest / "gallery")
        (dest / "query").mkdir(exist_ok=True)
        (dest / "query" / ".gitkeep").write_text(
            "Empty query dir for ATRW layout; real query jpgs are in reid_query_reference/\n"
        )

        if ref.exists():
            shutil.rmtree(ref)
        ref.mkdir(parents=True)
        nq = 0
        for jpg in sorted((src / "query").glob("*.jpg")):
            shutil.copy2(jpg, ref / jpg.name)
            nq += 1
        (ref / "README.md").write_text(QUERY_README, encoding="utf-8")
        pid_names_pre = load_fixed_pid_names()
        if not args.no_full_gallery and pid_names_pre:
            extra = ensure_full_reid_gallery(
                dest / "gallery", dest / "train", set(pid_names_pre.keys())
            )
            if extra:
                print(
                    f"full-gallery: added {len(extra)} pid(s) from train -> gallery: {extra}"
                )
            else:
                print("full-gallery: gallery already covered all pids (or none added)")
        elif args.no_full_gallery:
            print("full-gallery: skipped (--no-full-gallery); only source gallery/ pids in Re-ID gallery")
        print(f"reid_atrw: train + gallery + empty query/ -> {dest}")
        print(f"reid_query_reference: {nq} jpgs + README -> {ref}")
    elif args.dry_run:
        print(f"[dry-run] reid_atrw <- train+gallery; query -> {ref}; DB splits train+gallery only")
    else:
        print(f"Skip filesystem copy; expect {dest} and {ref}")

    pid_names: dict[int, str] = {}
    pj = args.pid_names_json.resolve() if args.pid_names_json else _PID_JSON
    if pj.is_file():
        with open(pj, encoding="utf-8") as f:
            pid_names = {int(k): str(v) for k, v in json.load(f).items()}
    if not pid_names:
        raise SystemExit(f"Missing pid names JSON: {_PID_JSON}")

    desc_map = load_descriptions(args.descriptions)
    root_for_migrate = dest if not args.dry_run else src

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        try:
            stats = await migrate(
                db,
                root_for_migrate,
                ["train", "gallery"],
                desc_map,
                args.list_name,
                args.dry_run,
                skip_existing=False,
                pid_names=pid_names,
            )
            if not args.dry_run:
                await db.commit()
        except Exception:
            await db.rollback()
            raise

    print("Done:", stats)
    print("DB: train + gallery only. Query: see uploads/reid_query_reference/")


if __name__ == "__main__":
    asyncio.run(amain())
