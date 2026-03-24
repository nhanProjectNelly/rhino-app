"""
Suggest crop rectangle from YOLO checkpoints (body.pt / head.pt under rhino_app/checkpoint/).
Returns percentages of image size for use in the cropper UI.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
RHINO_APP_ROOT = _BACKEND_ROOT.parent
CHECKPOINT_DIR = RHINO_APP_ROOT / "checkpoint"

MARGIN_FRAC = 0.08


def _checkpoint_path(target: str) -> Path | None:
    t = (target or "body").lower()
    name = "body" if t == "body" else "head"
    for fn in (f"{name}.pt", f"{name}.pth"):
        p = CHECKPOINT_DIR / fn
        if p.is_file():
            return p
    return None


def _pick_xyxy(boxes, names: dict, want: str) -> tuple[float, float, float, float] | None:
    """Choose best box for target class; fallback to largest detection."""
    n = len(boxes)
    if n == 0:
        return None
    want_l = want.lower()
    named: list[tuple[float, tuple[float, float, float, float]]] = []
    all_boxes: list[tuple[float, tuple[float, float, float, float]]] = []
    for i in range(n):
        cls_id = int(boxes.cls[i])
        label = str(names.get(cls_id, "") or "").lower()
        x1, y1, x2, y2 = boxes.xyxy[i].tolist()
        area = max(0.0, (x2 - x1) * (y2 - y1))
        t = (area, (x1, y1, x2, y2))
        all_boxes.append(t)
        if want_l == label or (want_l == "body" and "body" in label) or (want_l == "head" and "head" in label):
            named.append(t)
    pool = named if named else all_boxes
    pool.sort(key=lambda x: -x[0])
    return pool[0][1] if pool else None


def suggest_bbox_percent(image_path: Path, target: str = "body") -> dict:
    """
    Returns stencil as percent of natural image: left, top, width, height (0–100).
    """
    img = Image.open(image_path).convert("RGB")
    iw, ih = img.size
    if iw < 1 or ih < 1:
        return _full_frame(iw, ih, "invalid")

    try:
        from ultralytics import YOLO
    except ImportError:
        logger.warning("ultralytics not installed; crop suggest uses full frame")
        return _full_frame(iw, ih, "no_yolo")

    wpath = _checkpoint_path(target)
    if not wpath:
        logger.warning("No checkpoint at %s for target=%s", CHECKPOINT_DIR, target)
        return _full_frame(iw, ih, "no_weights")

    want = "body" if (target or "body").lower() == "body" else "head"
    try:
        model = YOLO(str(wpath))
        results = model.predict(str(image_path), conf=0.2, imgsz=1024, verbose=False)
    except Exception as e:
        logger.exception("YOLO predict failed: %s", e)
        return _full_frame(iw, ih, "error")

    if not results or results[0].boxes is None or len(results[0].boxes) == 0:
        return _full_frame(iw, ih, "no_detection")

    boxes = results[0].boxes
    names = model.names if isinstance(model.names, dict) else {i: str(n) for i, n in enumerate(model.names)}
    xyxy = _pick_xyxy(boxes, names, want)
    if not xyxy:
        return _full_frame(iw, ih, "no_detection")

    x1, y1, x2, y2 = xyxy
    bw, bh = x2 - x1, y2 - y1
    pad_w, pad_h = bw * MARGIN_FRAC, bh * MARGIN_FRAC
    x1 = max(0.0, x1 - pad_w)
    y1 = max(0.0, y1 - pad_h)
    x2 = min(float(iw), x2 + pad_w)
    y2 = min(float(ih), y2 + pad_h)
    if x2 <= x1 or y2 <= y1:
        return _full_frame(iw, ih, "degenerate")

    return {
        "x": int(round(x1)),
        "y": int(round(y1)),
        "width": max(1, int(round(x2 - x1))),
        "height": max(1, int(round(y2 - y1))),
        "image_width": iw,
        "image_height": ih,
        "source": "yolo",
        "weights": wpath.name,
    }


def _full_frame(iw: int, ih: int, source: str) -> dict:
    return {
        "x": 0,
        "y": 0,
        "width": max(1, iw),
        "height": max(1, ih),
        "image_width": iw,
        "image_height": ih,
        "source": source,
        "weights": None,
    }


def _pt_path(name: str) -> Path | None:
    for fn in (f"{name}.pt", f"{name}.pth"):
        p = CHECKPOINT_DIR / fn
        if p.is_file():
            return p
    return None


def _xyxy_to_rect(
    x1: float, y1: float, x2: float, y2: float, iw: int, ih: int
) -> dict[str, int] | None:
    x1 = max(0.0, min(float(x1), float(iw - 1)))
    y1 = max(0.0, min(float(y1), float(ih - 1)))
    x2 = max(0.0, min(float(x2), float(iw)))
    y2 = max(0.0, min(float(y2), float(ih)))
    bw, bh = x2 - x1, y2 - y1
    if bw < 2 or bh < 2:
        return None
    pad_w, pad_h = bw * MARGIN_FRAC, bh * MARGIN_FRAC
    x1 = max(0.0, x1 - pad_w)
    y1 = max(0.0, y1 - pad_h)
    x2 = min(float(iw), x2 + pad_w)
    y2 = min(float(ih), y2 + pad_h)
    if x2 <= x1 or y2 <= y1:
        return None
    return {
        "x": int(round(x1)),
        "y": int(round(y1)),
        "width": max(1, int(round(x2 - x1))),
        "height": max(1, int(round(y2 - y1))),
    }


def _ear_side_xyxy(
    box: tuple[float, float, float, float],
    head_xyxy: tuple[float, float, float, float] | None,
    img_width: int,
) -> str:
    """Animal's right ear = image-left (smaller x); animal's left = image-right."""
    x1, y1, x2, y2 = box
    ear_cx = (x1 + x2) / 2
    if head_xyxy is not None:
        hx1, _, hx2, _ = head_xyxy
        head_cx = (hx1 + hx2) / 2
    else:
        head_cx = img_width / 2
    return "right_ear" if ear_cx < head_cx else "left_ear"


def suggest_all_part_bboxes(image_path: Path) -> dict:
    """
    body.pt → body; head.pt → head; ear.pt → left_ear / right_ear by position vs head.
    Each value is {x,y,width,height} or null.
    """
    img = Image.open(image_path).convert("RGB")
    iw, ih = img.size
    empty = {
        "parts": {
            "body": None,
            "head": None,
            "left_ear": None,
            "right_ear": None,
        },
        "image_width": iw,
        "image_height": ih,
    }
    if iw < 2 or ih < 2:
        return empty

    try:
        from ultralytics import YOLO
    except ImportError:
        return empty

    def run_model(wpath: Path | None, want: str):
        if not wpath or not wpath.exists():
            return None, {}
        try:
            model = YOLO(str(wpath))
            results = model.predict(str(image_path), conf=0.15, imgsz=1024, verbose=False)
        except Exception as e:
            logger.warning("YOLO %s: %s", wpath.name, e)
            return None, {}
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None, {}
        boxes = results[0].boxes
        names = model.names if isinstance(model.names, dict) else {i: str(n) for i, n in enumerate(model.names)}
        xy = _pick_xyxy(boxes, names, want)
        if not xy:
            return None, {}
        return xy, names

    body_xy = None
    bp = _pt_path("body")
    if bp:
        body_xy, _ = run_model(bp, "body")
    head_xy = None
    hp = _pt_path("head")
    if hp:
        head_xy, _ = run_model(hp, "head")

    parts: dict[str, dict[str, int] | None] = {
        "body": _xyxy_to_rect(*body_xy, iw, ih) if body_xy else None,
        "head": _xyxy_to_rect(*head_xy, iw, ih) if head_xy else None,
        "left_ear": None,
        "right_ear": None,
    }

    ep = _pt_path("ear")
    if ep:
        try:
            model = YOLO(str(ep))
            results = model.predict(str(image_path), conf=0.12, imgsz=1024, verbose=False)
        except Exception as e:
            logger.warning("ear YOLO: %s", e)
            results = None
        if results and results[0].boxes is not None and len(results[0].boxes) > 0:
            boxes = results[0].boxes
            names = model.names if isinstance(model.names, dict) else {i: str(n) for i, n in enumerate(model.names)}
            ear_ids = {int(cid) for cid, nm in names.items() if str(nm).lower() == "ear"}
            if not ear_ids:
                ear_ids = {0}
            ear_list: list[tuple[float, tuple[float, float, float, float]]] = []
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i])
                if cls_id not in ear_ids:
                    continue
                label = str(names.get(cls_id, "") or "").lower()
                if label in ("face", "horn"):
                    continue
                conf = float(boxes.conf[i])
                t = tuple(boxes.xyxy[i].tolist())
                ear_list.append((conf, t))
            ear_list.sort(key=lambda x: -x[0])
            left_slot: tuple | None = None
            right_slot: tuple | None = None
            head_box = head_xy
            for _conf, box in ear_list:
                side = _ear_side_xyxy(box, head_box, iw)
                if side == "left_ear" and left_slot is None:
                    left_slot = box
                elif side == "right_ear" and right_slot is None:
                    right_slot = box
                if left_slot and right_slot:
                    break
            if left_slot:
                parts["left_ear"] = _xyxy_to_rect(*left_slot, iw, ih)
            if right_slot:
                parts["right_ear"] = _xyxy_to_rect(*right_slot, iw, ih)

    return {"parts": parts, "image_width": iw, "image_height": ih}
