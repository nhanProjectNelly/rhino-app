import asyncio
import json
import re
import shutil
import uuid
from functools import partial
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.config import settings
from app.database import get_db
from app.models import User, RhinoIdentity, RhinoImage, RhinoDescriptionVersion
from app.auth import get_current_user, require_admin
from app.services.describe import describe_parts_hybrid, describe_single_image

router = APIRouter(prefix="/gallery", tags=["gallery"])

PART_STEM_RE = re.compile(r"^(.+)_(left_ear|right_ear|head|body)(?:_\d+|_fallback)?$", re.IGNORECASE)
PART_KEYS = ("left_ear", "right_ear", "head", "body")


def parse_part_filename_stem(stem: str) -> tuple[str, str | None]:
    m = PART_STEM_RE.match(stem)
    if m:
        return m.group(1), m.group(2).lower()
    return stem, None


def merge_four_description_parts(
    existing: dict | None,
    updates: dict[str, str | None],
) -> dict[str, str]:
    out = {k: str((existing or {}).get(k) or "") for k in PART_KEYS}
    for k in PART_KEYS:
        v = updates.get(k)
        if v is not None and str(v).strip():
            out[k] = str(v).strip()
    return out


async def resolve_anchor_image(db: AsyncSession, img: RhinoImage) -> RhinoImage:
    if img.parent_image_id:
        p = await db.get(RhinoImage, img.parent_image_id)
        if p:
            return p
    if img.part_type is None or img.part_type == "body":
        return img
    if img.source_stem:
        q = (
            select(RhinoImage)
            .where(
                RhinoImage.identity_id == img.identity_id,
                RhinoImage.source_stem == img.source_stem,
                RhinoImage.is_active == True,
            )
            .order_by(RhinoImage.id)
        )
        rows = list((await db.execute(q)).scalars().all())
        for r in rows:
            if r.part_type is None and r.parent_image_id is None:
                return r
        for r in rows:
            if r.part_type is None or r.part_type == "body":
                return r
    return img


async def _active_version_id(db: AsyncSession, anchor_id: int) -> int | None:
    q = (
        select(RhinoDescriptionVersion.id)
        .where(
            RhinoDescriptionVersion.anchor_image_id == anchor_id,
            RhinoDescriptionVersion.is_active == True,
        )
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def push_description_version(
    db: AsyncSession,
    anchor: RhinoImage,
    parts: dict[str, str],
    schema: dict | None,
    label: str | None,
    from_version_id: int | None,
    make_active: bool,
) -> RhinoDescriptionVersion:
    if make_active:
        await db.execute(
            update(RhinoDescriptionVersion)
            .where(RhinoDescriptionVersion.anchor_image_id == anchor.id)
            .values(is_active=False)
        )
    ver = RhinoDescriptionVersion(
        anchor_image_id=anchor.id,
        description_parts={k: parts.get(k, "") for k in PART_KEYS},
        description_schema=dict(schema) if isinstance(schema, dict) else schema,
        label=label,
        is_active=make_active,
        created_from_version_id=from_version_id,
    )
    db.add(ver)
    await db.flush()
    if make_active:
        anchor.description_parts = {k: parts.get(k, "") for k in PART_KEYS}
        if schema is not None:
            anchor.description_schema = schema
    return ver


def save_upload(file: UploadFile, subdir: str, ext: str = None) -> Path:
    ext = ext or (Path(file.filename or "img").suffix or ".jpg")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / subdir / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dest


@router.get("/identities")
async def list_gallery_identities(
    include_inactive: bool = False,
    q: str | None = Query(None, description="Search identity name (substring, case-insensitive)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fetch_all: bool = Query(False, alias="all", description="Return all matches (e.g. for dropdowns); max 10000"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated + optional name search. Use all=true for full list (dropdowns)."""
    def apply_filters(stmt):
        if not include_inactive:
            stmt = stmt.where(RhinoIdentity.is_active == True)
        if q and str(q).strip():
            stmt = stmt.where(RhinoIdentity.name.ilike(f"%{str(q).strip()}%"))
        return stmt

    count_stmt = apply_filters(select(func.count(RhinoIdentity.id)))
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    list_stmt = apply_filters(select(RhinoIdentity)).order_by(
        RhinoIdentity.name.asc(),
        RhinoIdentity.id.asc(),
    )
    if fetch_all:
        list_stmt = list_stmt.limit(10000)
    else:
        list_stmt = list_stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(list_stmt)
    identities = list(result.scalars().all())
    items = [{"id": i.id, "name": i.name, "pid": i.pid, "is_active": i.is_active} for i in identities]
    if fetch_all:
        return {
            "items": items,
            "total": total,
            "page": 1,
            "page_size": len(items),
            "pages": 1,
        }
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


class IdentityCreate(BaseModel):
    name: str
    pid: int | None = None


class IdentityUpdate(BaseModel):
    name: str | None = None
    pid: int | None = None


@router.post("/identities", status_code=201)
async def create_identity(
    data: IdentityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    ident = RhinoIdentity(name=data.name.strip(), pid=data.pid)
    db.add(ident)
    await db.flush()
    return {"id": ident.id, "name": ident.name, "pid": ident.pid}


@router.patch("/identities/{identity_id}")
async def update_identity(
    identity_id: int,
    data: IdentityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    if data.name is not None:
        ident.name = data.name.strip()
    if data.pid is not None:
        ident.pid = data.pid
    return {"id": ident.id, "name": ident.name, "pid": ident.pid}


@router.patch("/identities/{identity_id}/deactivate")
async def deactivate_identity(
    identity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    ident.is_active = False
    return {"id": ident.id, "is_active": False}


@router.post("/upload")
async def upload_gallery_image(
    identity_id: int = Form(...),
    part_type: str | None = Form(None),
    confirmed: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident or not ident.is_active:
        raise HTTPException(status_code=404, detail="Identity not found")
    if part_type and part_type not in ("left_ear", "right_ear", "head", "body"):
        raise HTTPException(status_code=400, detail="part_type must be left_ear|right_ear|head|body")
    dest = save_upload(file, "gallery")
    rel = str(dest.relative_to(settings.UPLOAD_DIR))
    img = RhinoImage(identity_id=identity_id, file_path=rel, part_type=part_type, confirmed=confirmed)
    db.add(img)
    await db.flush()
    return {"id": img.id, "file_path": rel, "identity_id": identity_id, "part_type": part_type, "confirmed": img.confirmed}


@router.post("/upload-with-description")
async def upload_with_description(
    identity_id: int = Form(...),
    part_type: str | None = Form(None),
    confirmed: bool = Form(False),
    left_ear: str | None = Form(None),
    right_ear: str | None = Form(None),
    head: str | None = Form(None),
    body: str | None = Form(None),
    run_llm: bool = Form(True),
    descriptions_four_parts_json: str | None = Form(
        None,
        description="Optional JSON string: full descriptions_four_parts object to store on image schema",
    ),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload image and optionally run LLM; optional descriptions_four_parts from hybrid popup."""
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident or not ident.is_active:
        raise HTTPException(status_code=404, detail="Identity not found")
    if part_type and part_type not in ("left_ear", "right_ear", "head", "body"):
        raise HTTPException(status_code=400, detail="part_type must be left_ear|right_ear|head|body")
    dest = save_upload(file, "gallery")
    rel = str(dest.relative_to(settings.UPLOAD_DIR))
    img = RhinoImage(identity_id=identity_id, file_path=rel, part_type=part_type, confirmed=confirmed)
    db.add(img)
    await db.flush()

    part_overrides = {}
    if left_ear is not None and str(left_ear).strip():
        part_overrides["left_ear"] = str(left_ear).strip()
    if right_ear is not None and str(right_ear).strip():
        part_overrides["right_ear"] = str(right_ear).strip()
    if head is not None and str(head).strip():
        part_overrides["head"] = str(head).strip()
    if body is not None and str(body).strip():
        part_overrides["body"] = str(body).strip()

    if run_llm and settings.OPENAI_API_KEY:
        try:
            result = describe_single_image(dest, settings.OPENAI_API_KEY)
            img.description_schema = result["schema"]
            img.description_parts = {**(result["part_texts"] or {}), **part_overrides}
            img.description_source = "o4-mini"
        except Exception as e:
            if part_overrides:
                img.description_parts = part_overrides
                img.description_source = "manual"
            raise HTTPException(status_code=502, detail=f"LLM describe failed: {e}") from e
    elif part_overrides:
        img.description_parts = part_overrides
        img.description_source = "manual"

    if descriptions_four_parts_json and str(descriptions_four_parts_json).strip():
        try:
            parsed = json.loads(descriptions_four_parts_json)
            base = dict(img.description_schema) if isinstance(img.description_schema, dict) else {}
            base["descriptions_four_parts"] = parsed
            img.description_schema = base
        except Exception:
            pass

    if part_type is None and img.description_parts:
        prev = await _active_version_id(db, img.id)
        await push_description_version(
            db,
            img,
            {k: str((img.description_parts or {}).get(k) or "") for k in PART_KEYS},
            img.description_schema,
            label="upload",
            from_version_id=prev,
            make_active=True,
        )

    return {
        "id": img.id,
        "file_path": rel,
        "identity_id": identity_id,
        "part_type": part_type,
        "confirmed": img.confirmed,
        "description_parts": img.description_parts,
        "description_schema": img.description_schema,
        "description_source": img.description_source,
    }


@router.get("/images")
async def list_gallery_images(
    identity_id: int | None = None,
    include_inactive: bool = False,
    confirmed: bool | None = None,
    review_status: str | None = Query(None, description="draft|pending_review|junk|confirmed"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(RhinoImage).order_by(RhinoImage.id)
    if identity_id is not None:
        q = q.where(RhinoImage.identity_id == identity_id)
    if not include_inactive:
        q = q.where(RhinoImage.is_active == True)
    if confirmed is not None:
        q = q.where(RhinoImage.confirmed == confirmed)
    if review_status is not None:
        q = q.where(RhinoImage.review_status == review_status)
    result = await db.execute(q)
    images = list(result.scalars().all())
    return [
        {
            "id": i.id,
            "identity_id": i.identity_id,
            "file_path": i.file_path,
            "url": f"/uploads/{i.file_path}",
            "part_type": i.part_type,
            "parent_image_id": i.parent_image_id,
            "source_stem": i.source_stem,
            "confirmed": i.confirmed,
            "is_active": i.is_active,
            "description_schema": i.description_schema,
            "description_parts": i.description_parts,
            "description_source": i.description_source,
            "review_status": i.review_status,
            "review_reason": i.review_reason,
        }
        for i in images
    ]


class ManualDescriptionBody(BaseModel):
    left_ear: str | None = None
    right_ear: str | None = None
    head: str | None = None
    body: str | None = None


@router.patch("/images/{image_id}/description")
async def save_manual_description(
    image_id: int,
    data: ManualDescriptionBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save manual four-part description on capture anchor; traces a new description version."""
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    anchor = await resolve_anchor_image(db, img)
    updates = {k: getattr(data, k) for k in PART_KEYS}
    parts = merge_four_description_parts(anchor.description_parts, updates)
    prev = await _active_version_id(db, anchor.id)
    await push_description_version(
        db, anchor, parts, anchor.description_schema, label="manual", from_version_id=prev, make_active=True
    )
    anchor.description_source = "manual"
    return {
        "id": anchor.id,
        "description_parts": anchor.description_parts,
        "description_source": "manual",
        "anchor_image_id": anchor.id,
    }


@router.post("/images/{image_id}/describe-o4mini")
async def describe_single_image_o4mini(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run o4-mini to describe one image (vision). Updates description_schema, description_parts, description_source=o4-mini."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set")
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    path = settings.UPLOAD_DIR / img.file_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    result = describe_single_image(path, settings.OPENAI_API_KEY)
    img.description_schema = result["schema"]
    img.description_parts = result["part_texts"]
    img.description_source = "o4-mini"
    anchor = await resolve_anchor_image(db, img)
    if anchor.id == img.id:
        pt = result.get("part_texts") or {}
        parts = {k: str(pt.get(k) or "") for k in PART_KEYS}
        prev = await _active_version_id(db, anchor.id)
        await push_description_version(
            db, anchor, parts, result.get("schema"), label="o4-mini", from_version_id=prev, make_active=True
        )
    return {
        "id": img.id,
        "description_schema": result["schema"],
        "description_parts": result["part_texts"],
        "description_source": "o4-mini",
        "anchor_image_id": anchor.id,
    }


@router.patch("/images/{image_id}")
async def update_gallery_image(
    image_id: int,
    left_ear: str | None = Form(None),
    right_ear: str | None = Form(None),
    head: str | None = Form(None),
    body: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update image: optional new file (crop replacement), optional description parts."""
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    if file and file.filename:
        dest = save_upload(file, "gallery")
        rel = str(dest.relative_to(settings.UPLOAD_DIR))
        old_path = settings.UPLOAD_DIR / img.file_path
        if old_path.exists() and old_path != dest:
            try:
                old_path.unlink()
            except OSError:
                pass
        img.file_path = rel
    part_overrides = {}
    if left_ear is not None and str(left_ear).strip():
        part_overrides["left_ear"] = str(left_ear).strip()
    if right_ear is not None and str(right_ear).strip():
        part_overrides["right_ear"] = str(right_ear).strip()
    if head is not None and str(head).strip():
        part_overrides["head"] = str(head).strip()
    if body is not None and str(body).strip():
        part_overrides["body"] = str(body).strip()
    if part_overrides:
        anchor = await resolve_anchor_image(db, img)
        merged = merge_four_description_parts(anchor.description_parts, part_overrides)
        prev = await _active_version_id(db, anchor.id)
        await push_description_version(
            db, anchor, merged, anchor.description_schema, label="patch", from_version_id=prev, make_active=True
        )
        anchor.description_source = "manual"
        if img.id != anchor.id:
            img.description_parts = {**(img.description_parts or {}), **part_overrides}
    return {
        "id": img.id,
        "file_path": img.file_path,
        "description_parts": img.description_parts,
        "description_source": img.description_source,
    }


@router.post("/images/part-crop-from-parent")
async def part_crop_from_parent(
    identity_id: int = Form(...),
    parent_image_id: int = Form(...),
    part_type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create or replace a part crop (left_ear, right_ear, head, body) from the parent frame.
    If a row already exists for this capture + part_type, replaces its file; otherwise inserts.
    """
    if part_type not in PART_KEYS:
        raise HTTPException(status_code=400, detail="part_type must be left_ear|right_ear|head|body")
    parent = await db.get(RhinoImage, parent_image_id)
    if not parent or parent.identity_id != identity_id or not parent.is_active:
        raise HTTPException(status_code=404, detail="Parent image not found")
    stem = parent.source_stem
    if stem:
        q = (
            select(RhinoImage)
            .where(
                RhinoImage.identity_id == identity_id,
                RhinoImage.source_stem == stem,
                RhinoImage.part_type == part_type,
                RhinoImage.is_active == True,
            )
            .order_by(RhinoImage.id)
            .limit(1)
        )
    else:
        q = (
            select(RhinoImage)
            .where(
                RhinoImage.identity_id == identity_id,
                RhinoImage.parent_image_id == parent_image_id,
                RhinoImage.part_type == part_type,
                RhinoImage.is_active == True,
            )
            .order_by(RhinoImage.id)
            .limit(1)
        )
    result = await db.execute(q)
    existing = result.scalar_one_or_none()

    dest = save_upload(file, "gallery")
    rel = str(dest.relative_to(settings.UPLOAD_DIR))
    if existing:
        old_path = settings.UPLOAD_DIR / existing.file_path
        if old_path.exists() and old_path != dest:
            try:
                old_path.unlink()
            except OSError:
                pass
        existing.file_path = rel
        existing.parent_image_id = parent_image_id
        await db.flush()
        return {
            "id": existing.id,
            "file_path": rel,
            "url": f"/uploads/{rel}",
            "created": False,
        }
    img = RhinoImage(
        identity_id=identity_id,
        file_path=rel,
        part_type=part_type,
        parent_image_id=parent_image_id,
        source_stem=stem,
        confirmed=False,
    )
    db.add(img)
    await db.flush()
    return {
        "id": img.id,
        "file_path": rel,
        "url": f"/uploads/{rel}",
        "created": True,
    }


@router.patch("/images/{image_id}/confirm")
async def confirm_image(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    img.confirmed = True
    return {"id": img.id, "confirmed": True}


@router.patch("/images/{image_id}/deactivate")
async def deactivate_image(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    img.is_active = False
    return {"id": img.id, "is_active": False}


@router.get("/images/{image_id}/capture-detail")
async def get_capture_detail(
    image_id: int,
    identity_id: int = Query(..., description="Must match the image's identity (URL path)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    One capture context for the detail page URL /{identity_id}/img/{image_id}.
    Resolves anchor + four part slots (re-crop parent URLs).
    """
    img = await db.get(RhinoImage, image_id)
    if not img or not img.is_active:
        raise HTTPException(status_code=404, detail="Image not found")
    if img.identity_id != identity_id:
        raise HTTPException(status_code=404, detail="Image does not belong to this identity")
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    anchor = await resolve_anchor_image(db, img)
    stem = anchor.source_stem
    if stem:
        q = select(RhinoImage).where(
            RhinoImage.identity_id == identity_id,
            RhinoImage.source_stem == stem,
            RhinoImage.is_active == True,
        )
        group = list((await db.execute(q)).scalars().all())
    else:
        group = [anchor]

    anchor_url = f"/uploads/{anchor.file_path}"
    slots: dict[str, dict | None] = {k: None for k in PART_KEYS}
    for im in group:
        if im.part_type not in PART_KEYS:
            continue
        pu = anchor_url
        if im.parent_image_id:
            p = await db.get(RhinoImage, im.parent_image_id)
            if p:
                pu = f"/uploads/{p.file_path}"
        slots[im.part_type] = {
            "id": im.id,
            "url": f"/uploads/{im.file_path}",
            "parent_url": pu,
        }
    if slots["body"] is None:
        slots["body"] = {
            "id": anchor.id,
            "url": anchor_url,
            "parent_url": anchor_url,
            "is_anchor_fallback": True,
        }

    return {
        "identity_id": identity_id,
        "identity_name": ident.name,
        "anchor_image_id": anchor.id,
        "source_stem": stem,
        "anchor": {"id": anchor.id, "url": anchor_url},
        "slots": slots,
        "canonical_description_parts": anchor.description_parts,
        "four_parts_key_default": f"{ident.name}/{stem or anchor.id}",
    }


@router.post("/images/describe")
async def describe_images(
    identity_id: int = Form(...),
    image_id: str = Form(...),
    left_ear_id: int | None = Form(None),
    right_ear_id: int | None = Form(None),
    head_id: int | None = Form(None),
    body_id: int | None = Form(None),
    left_ear_text: str | None = Form(None),
    right_ear_text: str | None = Form(None),
    head_text: str | None = Form(None),
    body_text: str | None = Form(None),
    four_parts_key: str | None = Form(
        None,
        description="JSON base key for descriptions_four_parts.json (e.g. IdentityName/image_stem). Defaults to image_id.",
    ),
    llm_regenerate_with_form_hints: bool = Form(
        False,
        description="If true, run vision LLM for each part that has a crop, passing form text as hint.",
    ),
    anchor_image_id: int | None = Form(
        None,
        description="When set, write merged description + version on this anchor after describe.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Hybrid describe: manual part strings (from form) skip LLM for that part.
    With llm_regenerate_with_form_hints, always LLM per part crop using form text as context.
    Response descriptions_four_parts matches IndivAID merge_four shape.
    """
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    paths: dict[str, Path] = {}
    for part, img_id in [
        ("left_ear", left_ear_id),
        ("right_ear", right_ear_id),
        ("head", head_id),
        ("body", body_id),
    ]:
        if img_id:
            row = await db.get(RhinoImage, img_id)
            if row:
                paths[part] = settings.UPLOAD_DIR / row.file_path
    manual_parts = {
        "left_ear": left_ear_text,
        "right_ear": right_ear_text,
        "head": head_text,
        "body": body_text,
    }
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(
                describe_parts_hybrid,
                paths,
                manual_parts,
                image_id=image_id,
                api_key=settings.OPENAI_API_KEY,
                model="gpt-4o-mini",
                rhino_id_hint=ident.name,
                four_parts_key=four_parts_key,
                llm_regenerate_with_form_hints=llm_regenerate_with_form_hints,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Describe failed: {e}") from e

    part_ids = [left_ear_id, right_ear_id, head_id, body_id]
    for iid in part_ids:
        if iid:
            row = await db.get(RhinoImage, iid)
            if row:
                sch = dict(result["schema"])
                sch["descriptions_four_parts"] = result.get("descriptions_four_parts")
                row.description_schema = sch
                row.description_parts = result["part_texts"]
                row.description_source = "hybrid-llm" if llm_regenerate_with_form_hints else row.description_source

    if anchor_image_id is not None:
        anchor = await db.get(RhinoImage, anchor_image_id)
        if anchor and anchor.identity_id == identity_id:
            sch = dict(result["schema"])
            sch["descriptions_four_parts"] = result.get("descriptions_four_parts")
            anchor.description_schema = sch
            prev = await _active_version_id(db, anchor.id)
            await push_description_version(
                db,
                anchor,
                {k: str((result["part_texts"] or {}).get(k) or "") for k in PART_KEYS},
                sch,
                label="llm-regenerate" if llm_regenerate_with_form_hints else "hybrid-describe",
                from_version_id=prev,
                make_active=True,
            )
            anchor.description_source = "hybrid-llm"

    return result


class DescriptionVersionCreate(BaseModel):
    """Create a new traced version; optional fork from from_version_id."""

    left_ear: str | None = None
    right_ear: str | None = None
    head: str | None = None
    body: str | None = None
    label: str | None = None
    from_version_id: int | None = None
    make_active: bool = True


@router.get("/identities/{identity_id}/captures")
async def list_identity_captures(
    identity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Group gallery images by source_stem (or one group per unsynced image) for capture + part crops."""
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    q = select(RhinoImage).where(
        RhinoImage.identity_id == identity_id,
        RhinoImage.is_active == True,
    )
    images = list((await db.execute(q)).scalars().all())
    groups: dict[str, list[RhinoImage]] = {}
    for im in images:
        key = im.source_stem or f"_single_{im.id}"
        groups.setdefault(key, []).append(im)

    def img_dict(im: RhinoImage, parent_url: str | None = None) -> dict:
        d = {
            "id": im.id,
            "url": f"/uploads/{im.file_path}",
            "part_type": im.part_type,
            "parent_image_id": im.parent_image_id,
            "description_parts": im.description_parts,
        }
        if parent_url:
            d["parent_url"] = parent_url
        return d

    captures = []
    parent_cache: dict[int, str] = {}

    async def parent_url(pid: int | None) -> str | None:
        if not pid:
            return None
        if pid in parent_cache:
            return parent_cache[pid]
        p = await db.get(RhinoImage, pid)
        if not p:
            return None
        u = f"/uploads/{p.file_path}"
        parent_cache[pid] = u
        return u

    for stem, group in sorted(groups.items(), key=lambda x: x[0]):
        ordered = sorted(group, key=lambda x: x.id)
        anchor = next((im for im in ordered if im.part_type is None and im.parent_image_id is None), None)
        if not anchor:
            anchor = next((im for im in ordered if im.part_type in (None, "body")), ordered[0])

        anchor_full = await resolve_anchor_image(db, anchor)
        active_vid = await _active_version_id(db, anchor_full.id)
        parts_out: dict[str, dict] = {
            "anchor": img_dict(anchor_full),
        }
        for im in group:
            if im.id == anchor_full.id:
                continue
            pu = await parent_url(im.parent_image_id)
            key = im.part_type or f"extra_{im.id}"
            parts_out[key] = img_dict(im, parent_url=pu)

        captures.append(
            {
                "source_stem": None if stem.startswith("_single_") else stem,
                "anchor_image_id": anchor_full.id,
                "active_version_id": active_vid,
                "canonical_description_parts": anchor_full.description_parts,
                "parts": parts_out,
            }
        )

    return {"identity_id": identity_id, "captures": captures}


@router.get("/images/{image_id}/description-versions")
async def list_description_versions(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    anchor = await resolve_anchor_image(db, img)
    q = (
        select(RhinoDescriptionVersion)
        .where(RhinoDescriptionVersion.anchor_image_id == anchor.id)
        .order_by(RhinoDescriptionVersion.id.desc())
    )
    rows = list((await db.execute(q)).scalars().all())
    return {
        "anchor_image_id": anchor.id,
        "versions": [
            {
                "id": v.id,
                "label": v.label,
                "is_active": v.is_active,
                "created_at": v.created_at.isoformat() + "Z" if v.created_at else None,
                "created_from_version_id": v.created_from_version_id,
                "description_parts": v.description_parts,
            }
            for v in rows
        ],
    }


@router.post("/images/{image_id}/description-versions", status_code=201)
async def create_description_version_api(
    image_id: int,
    body: DescriptionVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    anchor = await resolve_anchor_image(db, img)
    updates = {k: getattr(body, k) for k in PART_KEYS}
    parts = merge_four_description_parts(anchor.description_parts, updates)
    from_id = body.from_version_id
    if from_id is None:
        from_id = await _active_version_id(db, anchor.id)
    await push_description_version(
        db,
        anchor,
        parts,
        anchor.description_schema,
        label=body.label or "fork",
        from_version_id=from_id,
        make_active=body.make_active,
    )
    if body.make_active:
        anchor.description_source = "manual"
    return {
        "anchor_image_id": anchor.id,
        "description_parts": anchor.description_parts,
        "is_active": body.make_active,
    }


@router.post("/images/{image_id}/description-versions/{version_id}/activate")
async def activate_description_version(
    image_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = await db.get(RhinoImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    anchor = await resolve_anchor_image(db, img)
    ver = await db.get(RhinoDescriptionVersion, version_id)
    if not ver or ver.anchor_image_id != anchor.id:
        raise HTTPException(status_code=404, detail="Version not found")
    await db.execute(
        update(RhinoDescriptionVersion)
        .where(RhinoDescriptionVersion.anchor_image_id == anchor.id)
        .values(is_active=False)
    )
    ver.is_active = True
    if ver.description_parts:
        anchor.description_parts = {k: str((ver.description_parts or {}).get(k) or "") for k in PART_KEYS}
    if ver.description_schema is not None:
        anchor.description_schema = ver.description_schema
    return {"anchor_image_id": anchor.id, "active_version_id": ver.id}


class ConvertExport(BaseModel):
    format: str  # "indivaid_schema" | "indivaid_part_texts" | "atrw_meta"


@router.get("/export-indivaid")
async def export_for_indivaid(
    list_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export schema + part descriptions for IndivAID (train)."""
    q = select(RhinoImage).where(RhinoImage.description_schema.isnot(None)).order_by(RhinoImage.identity_id)
    if list_id is not None:
        q = q.join(RhinoIdentity).where(RhinoIdentity.list_id == list_id)
    result = await db.execute(q)
    images = list(result.scalars().all())
    schema_list = []
    part_descriptions = {}
    for img in images:
        if img.description_schema:
            rec = dict(img.description_schema)
            rec["image_id"] = rec.get("image_id") or Path(img.file_path).stem
            schema_list.append(rec)
        if img.description_parts and img.file_path:
            stem = Path(img.file_path).stem
            part_descriptions[stem] = img.description_parts
    return {"schema": schema_list, "part_descriptions": part_descriptions}
