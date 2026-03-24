import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.config import settings
from app.database import get_db
from app.models import User, RhinoIdentity, RhinoImage, RhinoList, PredictionRecord, PredictionAuditLog
from app.auth import get_current_user, check_predict_rate_limit, require_admin
from app.services.predict import run_reid_top5
from app.services.describe import describe_uploaded_image_per_part

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])


def save_upload(file: UploadFile, subdir: str) -> Path:
    ext = Path(file.filename or "img").suffix or ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / subdir / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dest


def _review_target_dir(identity_id: int | None, status: str | None) -> Path:
    base = settings.UPLOAD_DIR / "review"
    if status == "junk" or identity_id is None:
        return base / "junk"
    return base / f"identity_{identity_id}"


def _move_to_review_bucket(src_rel: str, identity_id: int | None, status: str | None) -> str:
    src = settings.UPLOAD_DIR / src_rel
    if not src.exists():
        return src_rel.replace("\\", "/")
    target_dir = _review_target_dir(identity_id, status)
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / f"{uuid.uuid4().hex}{src.suffix.lower() or '.jpg'}"
    shutil.move(str(src), str(dst))
    return str(dst.relative_to(settings.UPLOAD_DIR)).replace("\\", "/")


def _reid_params() -> tuple[str, list[str], str | None, Path | None]:
    cfg_rel = (settings.INDIVAID_REID_CONFIG or "").strip()
    cf = (
        Path(cfg_rel).resolve()
        if Path(cfg_rel).is_absolute()
        else (settings.indivaid_root / cfg_rel).resolve()
    )
    config_file = str(cf)
    overrides: list[str] = []
    tdp = (settings.INDIVAID_REID_TEXT_DESC_PATH or "").strip()
    if tdp:
        p = Path(tdp).resolve() if Path(tdp).is_absolute() else (settings.indivaid_root / tdp).resolve()
        if p.is_file():
            overrides.extend(["DATASETS.TEXT_DESC_PATH", str(p)])
    wbo = (settings.INDIVAID_REID_USE_WHOLE_BODY_ONLY or "").strip().lower()
    if wbo in ("true", "1", "yes", "false", "0", "no"):
        overrides.extend(["DATASETS.USE_WHOLE_BODY_ONLY", "True" if wbo in ("true", "1", "yes") else "False"])
    gallery_root = None
    for name in ("reid_atrw", "gallery_atrw"):
        p = settings.UPLOAD_DIR / name
        if (p / "train").is_dir() and (p / "gallery").is_dir():
            gallery_root = str(p.resolve())
            break
    if gallery_root is None and (settings.UPLOAD_DIR / "gallery_atrw" / "gallery").is_dir():
        gallery_root = str((settings.UPLOAD_DIR / "gallery_atrw").resolve())
    return config_file, overrides, gallery_root, settings.model_weight_path


def _uploads_rel(abs_path: str) -> str | None:
    try:
        return str(Path(abs_path).resolve().relative_to(settings.UPLOAD_DIR.resolve())).replace("\\", "/")
    except ValueError:
        return None


def _normalize_top_k_paths(top_k: list) -> None:
    for t in top_k:
        ri = t.get("representative_image")
        if not ri:
            continue
        s = str(ri)
        if Path(s).is_absolute():
            rel = _uploads_rel(s)
            if rel:
                t["representative_image"] = rel


def _gallery_sources_from_query_rel(rel: str) -> list[Path]:
    """Single file, or all images in predict/set_* when rel is first file in set."""
    p = settings.UPLOAD_DIR / rel
    if not p.exists():
        return []
    if p.is_file():
        par = p.parent
        if par.name.startswith("set_") and par.parent.name == "predict":
            return sorted(
                x
                for x in par.iterdir()
                if x.is_file() and x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            )
        return [p]
    return []


@router.post("/describe-file")
async def describe_file(
    file: UploadFile = File(...),
    left_ear_text: str | None = Form(None),
    right_ear_text: str | None = Form(None),
    head_text: str | None = Form(None),
    body_text: str | None = Form(None),
    current_user: User = Depends(get_current_user),
):
    """Per-part vision LLM (YOLO crops) + merge; optional form hints per part bias LLM when ambiguous."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set")
    dest = save_upload(file, "predict")
    try:
        manual = {
            "left_ear": left_ear_text,
            "right_ear": right_ear_text,
            "head": head_text,
            "body": body_text,
        }
        result = describe_uploaded_image_per_part(
            dest, settings.OPENAI_API_KEY, manual_parts=manual
        )
        return {
            "description_schema": result["schema"],
            "description_parts": result["part_texts"],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Describe failed: {e}") from e


def _copy_weak_match_demo(out: dict) -> str | None:
    """Copy query images with low per-image top-1 score into reid_demo_not_in_gallery/<id>/."""
    thresh = float(settings.REID_LOW_SCORE_THRESHOLD)
    per = out.get("per_image") or []
    weak = [p for p in per if p.get("top1_score", 1.0) < thresh]
    if not weak:
        return None
    demo_id = uuid.uuid4().hex[:14]
    demo_dir = settings.UPLOAD_DIR / "reid_demo_not_in_gallery" / demo_id
    demo_dir.mkdir(parents=True, exist_ok=True)
    for j, w in enumerate(weak):
        src = Path(w["path"])
        if src.is_file():
            shutil.copy2(src, demo_dir / f"weak_{j:02d}_{src.name}")
    (demo_dir / "README.txt").write_text(
        f"Weak match (per-image top-1 < {thresh} vs eval gallery). Use for demo / manual review.\n",
        encoding="utf-8",
    )
    return f"reid_demo_not_in_gallery/{demo_id}"


async def _persist_reid_prediction(
    db: AsyncSession,
    query_rel: str,
    out: dict,
    *,
    demo_rel: str | None = None,
    query_urls_extra: list[str] | None = None,
    set_folder_rel: str | None = None,
) -> dict:
    if out.get("error"):
        return {
            "query_path": query_rel,
            "query_url": f"/uploads/{query_rel}",
            "query_urls": query_urls_extra or [f"/uploads/{query_rel}"],
            "top_k": [],
            "top1": None,
            "error": out["error"],
        }
    top_k = list(out.get("top_k") or [])
    _normalize_top_k_paths(top_k)
    fin = out.get("finalize")
    top1 = top_k[0] if top_k else None
    if fin and top_k:
        rep = next((t for t in top_k if t["id"] == fin["id"]), top_k[0])
        top1 = {
            "rank": 1,
            "id": fin["id"],
            "id_name": rep.get("id_name"),
            "score": fin["score"],
            "representative_image": rep.get("representative_image"),
            "finalize_method": fin.get("method"),
        }
    per_image = list(out.get("per_image") or [])
    for pi in per_image:
        ur = _uploads_rel(pi["path"])
        if ur:
            pi["upload_rel"] = ur
    top5_stored: dict = {
        "top_k": top_k,
        "finalize": fin,
        "per_image": per_image,
        "is_set": len(per_image) > 1,
    }
    if demo_rel:
        top5_stored["demo_not_in_gallery_rel"] = demo_rel
    if set_folder_rel:
        top5_stored["set_folder_rel"] = set_folder_rel

    rec = PredictionRecord(
        query_image_path=query_rel.replace("\\", "/"),
        top1_identity_id=None,
        top1_score=float(top1["score"]) if top1 else None,
        top5_json=top5_stored,
    )
    db.add(rec)
    await db.flush()
    identity_id = None
    if top1 and "id" in top1:
        pid = top1["id"]
        res = await db.execute(select(RhinoIdentity).where(RhinoIdentity.pid == pid))
        ident = res.scalar_one_or_none()
        if ident:
            identity_id = ident.id
            rec.top1_identity_id = ident.id
    rec.review_status = "draft" if identity_id else "junk"
    rec.review_reason = "predicted_id" if identity_id else ("no_match" if not out.get("error") else "predict_error")
    moved_rel = _move_to_review_bucket(query_rel.replace("\\", "/"), identity_id, rec.review_status)
    rec.query_image_path = moved_rel
    img = RhinoImage(
        identity_id=identity_id or await _ensure_junk_identity_id(db),
        file_path=moved_rel,
        confirmed=False,
        review_status=rec.review_status,
        review_reason=rec.review_reason,
    )
    db.add(img)
    await db.flush()
    rec.source_image_id = img.id
    db.add(
        PredictionAuditLog(
            prediction_id=rec.id,
            action="predict_upload",
            actor_user_id=None,
            from_status=None,
            to_status=rec.review_status,
            note=rec.review_reason,
        )
    )
    qurls = query_urls_extra or [f"/uploads/{moved_rel}"]
    resp = {
        "prediction_id": rec.id,
        "query_path": moved_rel,
        "query_url": qurls[0] if qurls else f"/uploads/{moved_rel}",
        "query_urls": qurls,
        "top_k": top_k,
        "top1": top1,
        "finalize": fin,
        "per_image": per_image,
        "top1_identity_id": identity_id,
        "nearest_images": [t.get("representative_image") for t in top_k[:5]],
    }
    if demo_rel:
        resp["demo_not_in_gallery_url"] = f"/uploads/{demo_rel}"
    if set_folder_rel:
        resp["set_folder_rel"] = set_folder_rel
    if out.get("reid_debug"):
        resp["reid_debug"] = out["reid_debug"]
    return resp


async def _ensure_system_list(db: AsyncSession) -> RhinoList:
    q = await db.execute(select(RhinoList).where(RhinoList.name == "System Review Buckets"))
    row = q.scalar_one_or_none()
    if row:
        return row
    row = RhinoList(name="System Review Buckets", list_type="images")
    db.add(row)
    await db.flush()
    return row


async def _ensure_identity(db: AsyncSession, name: str, pid: int | None = None) -> RhinoIdentity:
    q = await db.execute(select(RhinoIdentity).where(RhinoIdentity.name == name))
    row = q.scalar_one_or_none()
    if row:
        return row
    system_list = await _ensure_system_list(db)
    row = RhinoIdentity(list_id=system_list.id, name=name, pid=pid, is_active=True)
    db.add(row)
    await db.flush()
    return row


async def _ensure_junk_identity_id(db: AsyncSession) -> int:
    return (await _ensure_identity(db, "JUNK")).id


async def _ensure_pending_identity_id(db: AsyncSession) -> int:
    return (await _ensure_identity(db, "PENDING_REVIEW")).id


@router.post("/upload")
async def predict_upload(
    file: UploadFile = File(...),
    llm_non_rhino: bool = Form(False, description="If true, skip Re-ID and classify as junk/non-rhino."),
    description_parts_json: str | None = Form(
        None,
        description='JSON object {"left_ear","right_ear","head","body"} from describe step',
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(check_predict_rate_limit),
):
    dest = save_upload(file, "predict")
    rel = str(dest.relative_to(settings.UPLOAD_DIR)).replace("\\", "/")
    config_file, overrides, gallery_root, weight_path = _reid_params()
    qparts: list[dict[str, str]] | None = None
    if description_parts_json and str(description_parts_json).strip():
        try:
            raw = json.loads(description_parts_json)
            if isinstance(raw, dict):
                qparts = [
                    {
                        k: str(raw.get(k, "") or "")
                        for k in ("left_ear", "right_ear", "head", "body")
                    }
                ]
            elif isinstance(raw, list) and raw:
                qparts = []
                for item in raw:
                    if isinstance(item, dict):
                        qparts.append(
                            {
                                k: str(item.get(k, "") or "")
                                for k in ("left_ear", "right_ear", "head", "body")
                            }
                        )
        except json.JSONDecodeError:
            logger.warning("upload: invalid description_parts_json")
    logger.info(
        "predict upload: description_parts=%s",
        "yes" if qparts else "no",
    )
    if llm_non_rhino:
        out = {"error": "LLM classified as non-rhino", "top_k": [], "query": str(dest)}
    else:
        out = run_reid_top5(
            config_file=config_file,
            weight_path=str(weight_path) if weight_path else "",
            query_path=str(dest),
            gallery_root=gallery_root,
            topk=5,
            cfg_overrides=overrides or None,
            query_description_parts_list=qparts,
        )
    demo_rel = _copy_weak_match_demo(out) if not out.get("error") else None
    resp = await _persist_reid_prediction(db, rel, out, demo_rel=demo_rel)
    if llm_non_rhino and resp.get("prediction_id"):
        rec = await db.get(PredictionRecord, int(resp["prediction_id"]))
        if rec:
            from_status = rec.review_status
            rec.review_status = "junk"
            rec.review_reason = "llm_non_rhino"
            if rec.source_image_id:
                img = await db.get(RhinoImage, rec.source_image_id)
                if img:
                    img.identity_id = await _ensure_junk_identity_id(db)
                    img.review_status = "junk"
                    img.review_reason = "llm_non_rhino"
                    moved = _move_to_review_bucket(img.file_path, None, "junk")
                    img.file_path = moved
                    rec.query_image_path = moved
            db.add(
                PredictionAuditLog(
                    prediction_id=rec.id,
                    actor_user_id=current_user.id,
                    action="llm_non_rhino",
                    from_status=from_status,
                    to_status="junk",
                    note="client_flag_llm_non_rhino",
                )
            )
    return resp


@router.post("/upload-set")
async def predict_upload_set(
    files: list[UploadFile] = File(...),
    description_parts_list_json: str | None = Form(
        None,
        description="JSON array of description_parts objects, same order as files",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(check_predict_rate_limit),
):
    """Multi-image → one Re-ID conclusion (mean embedding + majority finalize)."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one image required")
    sid = uuid.uuid4().hex[:16]
    set_dir = settings.UPLOAD_DIR / "predict" / f"set_{sid}"
    set_dir.mkdir(parents=True, exist_ok=True)
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    rels: list[str] = []
    for i, f in enumerate(files):
        ext = (Path(f.filename or "").suffix or ".jpg").lower()
        if ext not in allowed:
            ext = ".jpg"
        dest = set_dir / f"{i:03d}{ext}"
        with dest.open("wb") as outf:
            shutil.copyfileobj(f.file, outf)
        rels.append(str(dest.relative_to(settings.UPLOAD_DIR)).replace("\\", "/"))
    qlist: list[dict[str, str]] | None = None
    if description_parts_list_json and str(description_parts_list_json).strip():
        try:
            arr = json.loads(description_parts_list_json)
            if isinstance(arr, list) and len(arr) == len(files):
                qlist = []
                for item in arr:
                    if isinstance(item, dict):
                        qlist.append(
                            {
                                k: str(item.get(k, "") or "")
                                for k in ("left_ear", "right_ear", "head", "body")
                            }
                        )
                    else:
                        qlist.append(
                            {k: "" for k in ("left_ear", "right_ear", "head", "body")}
                        )
        except json.JSONDecodeError:
            logger.warning("upload-set: invalid description_parts_list_json")
    logger.info(
        "predict upload-set: files=%s desc_list=%s parsed_ok=%s",
        len(files),
        len(qlist) if qlist else 0,
        qlist is not None and len(qlist) == len(files),
    )
    config_file, overrides, gallery_root, weight_path = _reid_params()
    out = run_reid_top5(
        config_file=config_file,
        weight_path=str(weight_path) if weight_path else "",
        query_path=str(set_dir),
        gallery_root=gallery_root,
        topk=5,
        cfg_overrides=overrides or None,
        query_description_parts_list=qlist,
    )
    demo_rel = _copy_weak_match_demo(out) if not out.get("error") else None
    folder_rel = f"predict/set_{sid}"
    return await _persist_reid_prediction(
        db,
        rels[0],
        out,
        demo_rel=demo_rel,
        query_urls_extra=[f"/uploads/{r}" for r in rels],
        set_folder_rel=folder_rel,
    )


@router.post("/confirm")
async def confirm_prediction(
    prediction_id: int = Form(...),
    identity_id: int = Form(...),
    add_to_gallery: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = await db.get(PredictionRecord, prediction_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Prediction not found")
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    rec.confirmed = True
    rec.confirmed_identity_id = identity_id
    if add_to_gallery:
        for src in _gallery_sources_from_query_rel(rec.query_image_path):
            name = f"{uuid.uuid4().hex}{src.suffix.lower() or '.jpg'}"
            dest = settings.UPLOAD_DIR / "gallery" / name
            shutil.copy2(src, dest)
            rel_g = str(dest.relative_to(settings.UPLOAD_DIR))
            img = RhinoImage(identity_id=identity_id, file_path=rel_g, confirmed=False)
            db.add(img)
    return {"confirmed": True, "identity_id": identity_id, "added_to_gallery": add_to_gallery}


@router.post("/report")
async def report_prediction(
    prediction_id: int = Form(...),
    correct_identity_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark prediction as wrong and set the correct identity (label)."""
    rec = await db.get(PredictionRecord, prediction_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Prediction not found")
    ident = await db.get(RhinoIdentity, correct_identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    rec.reported = True
    rec.corrected_identity_id = correct_identity_id
    rec.confirmed_identity_id = correct_identity_id
    rec.confirmed = True
    rec.review_status = "pending_review"
    rec.review_reason = "report_wrong_id"
    if rec.source_image_id:
        img = await db.get(RhinoImage, rec.source_image_id)
        if img:
            img.identity_id = correct_identity_id
            img.review_status = "pending_review"
            img.review_reason = "report_wrong_id"
            moved = _move_to_review_bucket(img.file_path, correct_identity_id, "pending_review")
            img.file_path = moved
            rec.query_image_path = moved
    db.add(
        PredictionAuditLog(
            prediction_id=rec.id,
            actor_user_id=current_user.id,
            action="report",
            from_status="draft",
            to_status="pending_review",
            note=f"correct_identity_id={correct_identity_id}",
        )
    )
    return {"reported": True, "correct_identity_id": correct_identity_id}


@router.post("/assign")
async def assign_prediction(
    prediction_id: int = Form(...),
    identity_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually assign identity for prediction (when prediction fails or to correct)."""
    rec = await db.get(PredictionRecord, prediction_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Prediction not found")
    ident = await db.get(RhinoIdentity, identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    from_status = rec.review_status
    rec.confirmed_identity_id = identity_id
    rec.confirmed = True
    rec.review_status = "confirmed"
    rec.review_reason = "admin_assign_existing"
    if rec.source_image_id:
        img = await db.get(RhinoImage, rec.source_image_id)
        if img:
            img.identity_id = identity_id
            img.confirmed = True
            img.review_status = "confirmed"
            img.review_reason = "admin_assign_existing"
            moved = _move_to_review_bucket(img.file_path, identity_id, "confirmed")
            img.file_path = moved
            rec.query_image_path = moved
    db.add(
        PredictionAuditLog(
            prediction_id=rec.id,
            actor_user_id=current_user.id,
            action="assign_existing_identity",
            from_status=from_status,
            to_status="confirmed",
            note=f"identity_id={identity_id}",
        )
    )
    return {"assigned": True, "identity_id": identity_id}


class CreateIdentityBody(BaseModel):
    name: str
    pid: int | None = None


@router.post("/review/{prediction_id}/assign")
async def admin_review_assign(
    prediction_id: int,
    identity_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return await assign_prediction(prediction_id=prediction_id, identity_id=identity_id, db=db, current_user=current_user)


@router.post("/review/{prediction_id}/create-identity")
async def admin_review_create_identity(
    prediction_id: int,
    body: CreateIdentityBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    ident = RhinoIdentity(name=body.name.strip(), pid=body.pid)
    db.add(ident)
    await db.flush()
    await assign_prediction(prediction_id=prediction_id, identity_id=ident.id, db=db, current_user=current_user)
    return {"created_identity_id": ident.id, "name": ident.name}


@router.post("/review/{prediction_id}/mark-junk")
async def admin_review_mark_junk(
    prediction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    rec = await db.get(PredictionRecord, prediction_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Prediction not found")
    from_status = rec.review_status
    rec.review_status = "junk"
    rec.review_reason = "admin_mark_junk"
    if rec.source_image_id:
        img = await db.get(RhinoImage, rec.source_image_id)
        if img:
            img.identity_id = await _ensure_junk_identity_id(db)
            img.confirmed = False
            img.review_status = "junk"
            img.review_reason = "admin_mark_junk"
            moved = _move_to_review_bucket(img.file_path, None, "junk")
            img.file_path = moved
            rec.query_image_path = moved
    db.add(
        PredictionAuditLog(
            prediction_id=rec.id,
            actor_user_id=current_user.id,
            action="mark_junk",
            from_status=from_status,
            to_status="junk",
            note="admin_mark_junk",
        )
    )
    return {"prediction_id": rec.id, "review_status": "junk"}


@router.patch("/top")
async def set_top(
    prediction_id: int = Form(...),
    top1_identity_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update top 1 selection (set/update)."""
    rec = await db.get(PredictionRecord, prediction_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Prediction not found")
    ident = await db.get(RhinoIdentity, top1_identity_id)
    if not ident:
        raise HTTPException(status_code=404, detail="Identity not found")
    rec.top1_identity_id = top1_identity_id
    return {"top1_identity_id": top1_identity_id}


@router.get("/history")
async def prediction_history(
    limit: int = 50,
    confirmed: bool | None = None,
    reported_only: bool = Query(
        False,
        description="If true, only rows with reported=True. Requires admin role.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if reported_only and getattr(current_user, "role", "user") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role required for reported_only filter",
        )
    q = select(PredictionRecord).order_by(PredictionRecord.id.desc()).limit(limit)
    if confirmed is not None:
        q = q.where(PredictionRecord.confirmed == confirmed)
    if reported_only:
        q = q.where(PredictionRecord.reported.is_(True))
    result = await db.execute(q)
    rows = list(result.scalars().all())
    return [
        {
            "id": r.id,
            "query_path": r.query_image_path,
            "query_url": f"/uploads/{r.query_image_path}",
            "top1_identity_id": r.top1_identity_id,
            "top1_score": r.top1_score,
            "top5_json": r.top5_json,
            "confirmed": r.confirmed,
            "confirmed_identity_id": r.confirmed_identity_id,
            "reported": getattr(r, "reported", False),
            "corrected_identity_id": getattr(r, "corrected_identity_id", None),
            "source_image_id": getattr(r, "source_image_id", None),
            "review_status": getattr(r, "review_status", None),
            "review_reason": getattr(r, "review_reason", None),
        }
        for r in rows
    ]


@router.get("/review-queue")
async def review_queue(
    status: str | None = Query(None, description="draft|pending_review|junk"),
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = select(PredictionRecord).order_by(PredictionRecord.id.desc()).limit(limit)
    if status:
        q = q.where(PredictionRecord.review_status == status)
    rows = list((await db.execute(q)).scalars().all())
    return [
        {
            "prediction_id": r.id,
            "query_url": f"/uploads/{r.query_image_path}",
            "top1_identity_id": r.top1_identity_id,
            "review_status": r.review_status,
            "review_reason": r.review_reason,
            "reported": r.reported,
            "corrected_identity_id": r.corrected_identity_id,
            "source_image_id": r.source_image_id,
        }
        for r in rows
    ]
