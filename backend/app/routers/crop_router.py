from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import settings
from app.models import User
from app.services.auto_crop_bbox import suggest_all_part_bboxes, suggest_bbox_percent
from app.services.crop import crop_image

router = APIRouter(prefix="/crop", tags=["crop"])


class CropBody(BaseModel):
    x: int
    y: int
    width: int
    height: int


@router.post("/image")
async def crop_uploaded_image(
    x: int = Form(...),
    y: int = Form(...),
    width: int = Form(...),
    height: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="width and height must be positive")
    ext = Path(file.filename or "img").suffix or ".jpg"
    name = f"{uuid.uuid4().hex}_crop{ext}"
    tmp = settings.UPLOAD_DIR / "crops" / f"tmp_{name}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    out_path = settings.UPLOAD_DIR / "crops" / name
    crop_image(Path(tmp), x, y, width, height, out_path)
    tmp.unlink(missing_ok=True)
    rel = str(out_path.relative_to(settings.UPLOAD_DIR))
    return {"file_path": rel, "url": f"/uploads/{rel}"}


@router.post("/suggest-bbox")
async def suggest_crop_bbox(
    file: UploadFile = File(...),
    target: str = Form("body"),
    current_user: User = Depends(get_current_user),
):
    """
    YOLO-based crop suggestion (body.pt / head.pt in rhino_app/checkpoint/).
    Returns percentages of image size for the UI cropper. Falls back to full frame if no model/detection.
    """
    raw = await file.read()
    ext = Path(file.filename or "img").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    tmp = settings.UPLOAD_DIR / "crops" / f"_suggest_{uuid.uuid4().hex}{ext}"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    def _work() -> dict:
        try:
            tmp.write_bytes(raw)
            return suggest_bbox_percent(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    return await run_in_threadpool(_work)


@router.post("/suggest-part-bboxes")
async def suggest_part_bboxes(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """YOLO: body, head, left_ear, right_ear rects (pixels) on the uploaded image for step-2 previews."""
    raw = await file.read()
    ext = Path(file.filename or "img").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    tmp = settings.UPLOAD_DIR / "crops" / f"_parts_{uuid.uuid4().hex}{ext}"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    def _work() -> dict:
        try:
            tmp.write_bytes(raw)
            return suggest_all_part_bboxes(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    return await run_in_threadpool(_work)
