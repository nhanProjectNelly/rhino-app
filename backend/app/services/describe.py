"""Describe rhino images with OpenAI o4-mini (vision), returns IndivAID schema."""
import concurrent.futures
import json
import logging
import re
import base64
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

from openai import OpenAI

SCHEMA_INSTRUCTIONS = r"""You are a rhino re-identification annotator. You will receive 4 images in order:
  Image 1: LEFT ear crop
  Image 2: RIGHT ear crop  
  Image 3: HEAD / FACE crop
  Image 4: FULL BODY crop

They all belong to the same individual and the same capture (same image_id).

Output a single JSON object with exactly this structure. Use only the allowed values where specified; use "unknown" when not visible or uncertain. For free-text fields use short phrases or "none".

{
  "id": "<rhino_id_or_unknown>",
  "image_id": "<file_name_or_index>",
  "head_face": {
    "viewpoint": "front_left|front_right|side_left|side_right|front|rear|unknown",
    "horn": {
      "count": "1|2|unknown",
      "front_horn_shape": "short|medium|long|broken|blunt|sharp|curved|straight|unknown",
      "rear_horn_shape": "short|medium|long|broken|blunt|sharp|curved|straight|unknown"
    },
    "eye_area_marks": {
      "scar_near_eye": "none|left|right|both|unknown",
      "notable_wrinkles": "low|medium|high|unknown"
    },
    "nose_muzzle": {
      "nose_wrinkles": "low|medium|high|unknown",
      "muzzle_shape": "round|elongated|unknown"
    },
    "head_marks": {
      "distinctive_scars": "<free_text_or_none_or_unknown>"
    }
  },
  "ears": {
    "visibility": "both|left_only|right_only|none|unknown",
    "left_ear": {
      "edge_status": "intact|torn|ragged|unknown",
      "notches_count": "0|1|2|3plus|unknown",
      "notch_positions": "top|mid|bottom|mixed|unknown",
      "tuft": "present|absent|unknown"
    },
    "right_ear": {
      "edge_status": "intact|torn|ragged|unknown",
      "notches_count": "0|1|2|3plus|unknown",
      "notch_positions": "top|mid|bottom|mixed|unknown",
      "tuft": "present|absent|unknown"
    }
  },
  "full_body": {
    "body_viewpoint": "full|partial|unknown",
    "size_build": "small|medium|large|unknown",
    "back_profile": "flat|arched|unknown",
    "skin_texture": "smooth|moderate_wrinkle|heavy_wrinkle|unknown",
    "mud_dust_pattern": {
      "presence": "none|light|heavy|unknown",
      "location": "legs|flank|back|mixed|unknown"
    },
    "body_scars_wounds": "<free_text_or_none_or_unknown>"
  }
}

Output only the JSON object, no markdown or extra text."""


def schema_record_to_part_texts(record: dict) -> dict[str, str]:
    """Convert one schema record to { left_ear, right_ear, head, body }."""
    head = record.get("head_face") or {}
    ears = record.get("ears") or {}
    body = record.get("full_body") or {}
    le = ears.get("left_ear") or {}
    re_ear = ears.get("right_ear") or {}

    def ear_str(e: dict) -> str:
        parts = []
        if e.get("edge_status") and e["edge_status"] != "unknown":
            parts.append(f"edge {e['edge_status']}")
        if e.get("notches_count") is not None and str(e.get("notches_count")) != "unknown":
            parts.append(f"{e['notches_count']} notch(es)")
        if e.get("notch_positions") and str(e.get("notch_positions", "")).lower() not in ("unknown", "none"):
            parts.append(str(e["notch_positions"]))
        if e.get("tuft") and e["tuft"] != "unknown":
            parts.append(f"tuft {e['tuft']}")
        return "; ".join(parts) if parts else "no detail"

    def head_str() -> str:
        parts = []
        if head.get("viewpoint"):
            parts.append(head["viewpoint"])
        h = head.get("horn") or {}
        if h.get("count"):
            parts.append(f"horns {h['count']}")
        for k in ("eye_area_marks", "nose_muzzle", "head_marks"):
            sub = head.get(k)
            if isinstance(sub, dict):
                parts.append(", ".join(f"{a}:{v}" for a, v in sub.items() if v))
        return "; ".join(parts) if parts else "no detail"

    def body_str() -> str:
        parts = []
        if body.get("body_viewpoint"):
            parts.append(body["body_viewpoint"])
        if body.get("size_build"):
            parts.append(body["size_build"])
        if body.get("skin_texture"):
            parts.append(body["skin_texture"])
        if body.get("body_scars_wounds") and str(body.get("body_scars_wounds", "")).lower() not in ("none", "unknown"):
            parts.append(str(body["body_scars_wounds"]))
        return "; ".join(parts) if parts else "no detail"

    return {
        "left_ear": ear_str(le),
        "right_ear": ear_str(re_ear),
        "head": head_str(),
        "body": body_str(),
    }


def encode_image(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        return json.loads(m.group(0))
    return json.loads(raw)


async def describe_rhino_images(
    image_paths: dict[str, Path],
    image_id: str,
    rhino_id_hint: str | None,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """Call o4-mini with 4 images (left_ear, right_ear, head, body), returns schema + part texts."""
    client = OpenAI(api_key=api_key)
    content = [
        {
            "type": "text",
            "text": (
                "image_id for this set: " + image_id + "\n\n"
                + (f"Rhino id hint: {rhino_id_hint}\n\n" if rhino_id_hint else "")
                + SCHEMA_INSTRUCTIONS
            ),
        },
    ]
    for part in ["left_ear", "right_ear", "head", "body"]:
        p = image_paths.get(part)
        if p and p.exists():
            b64 = encode_image(p)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
    if len(content) == 1:
        raise ValueError("No part images provided")
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output only valid JSON. No markdown, no explanation."},
            {"role": "user", "content": content},
        ],
        "max_tokens": 1200,
        "temperature": 0.2,
    }
    if model in ("gpt-4o-mini", "gpt-4o", "o4-mini", "o4-mini-2025-01-31"):
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    raw = resp.choices[0].message.content.strip()
    schema = extract_json(raw)
    schema["image_id"] = schema.get("image_id") or image_id
    if rhino_id_hint and (not schema.get("id") or schema.get("id") == "unknown"):
        schema["id"] = rhino_id_hint
    part_texts = schema_record_to_part_texts(schema)
    return {"schema": schema, "part_texts": part_texts}


SINGLE_IMAGE_PROMPT = """You are a rhino re-identification annotator. Describe this single rhino image for re-identification.

Output a JSON object with these keys (use "unknown" when not visible):
- left_ear: short text (edge status, notches, tuft)
- right_ear: short text (edge status, notches, tuft)
- head: short text (viewpoint, horn shape, muzzle, wrinkles)
- body: short text (viewpoint, size, skin texture, scars)

Output only the JSON object, no markdown."""


PART_ORDER = ("left_ear", "right_ear", "head", "body")

PART_LLM_PROMPTS: dict[str, str] = {
    "left_ear": (
        "This image is a cropped rhino LEFT EAR (animal's left). "
        "Note intentional ear-notch ID marks: edge notches (top/mid/bottom) and a possible "
        "round hole in the CENTER of the ear (Hussek-style position 10 on left ear). "
        "Describe edge (intact/torn), notches, central round hole if visible, tuft. "
        'Output only valid JSON: {"raw": "your concise description"}'
    ),
    "right_ear": (
        "This image is a cropped rhino RIGHT EAR (animal's right). "
        "Ear-notch ID: edge notches and optional round CENTRAL hole (Hussek-style position 5 on right ear). "
        "Describe edge, notches, central hole if present, tuft. "
        'Output only valid JSON: {"raw": "your concise description"}'
    ),
    "head": (
        "This image is a cropped rhino HEAD / face. "
        "Describe viewpoint (e.g. front_left, side_right), horn shape, muzzle (round/elongated), wrinkles. "
        'Output only valid JSON: {"raw": "your concise description"}'
    ),
    "body": (
        "This image is a cropped rhino FULL BODY or torso. "
        "Describe body viewpoint (full/partial), size build (small/medium/large), skin texture (smooth/wrinkled), notable marks. "
        'Output only valid JSON: {"raw": "your concise description"}'
    ),
}


def describe_one_part_with_llm(
    part: str,
    image_path: Path,
    api_key: str,
    model: str = "gpt-4o-mini",
    form_hint: str | None = None,
) -> str:
    """Single-part vision call. Optional form_hint: annotator draft sent with the image so the model can refine it."""
    if part not in PART_LLM_PROMPTS:
        raise ValueError(f"Unknown part: {part}")
    client = OpenAI(api_key=api_key)
    b64 = encode_image(image_path)
    prompt = PART_LLM_PROMPTS[part]
    if form_hint and str(form_hint).strip():
        hint = str(form_hint).strip()[:1200]
        prompt += (
            "\n\nAnnotator form (structured choices encoded as text below). "
            "Write a concise description consistent with the image. "
            "Where the image is ambiguous or low detail, **slightly favor** reflecting their "
            "specific choices (e.g. notch count, torn vs intact, rim position, central hole, tuft) "
            "unless the image clearly contradicts them.\n"
            "Draft: "
            + hint
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output only valid JSON with a single key 'raw'. No markdown."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        "max_tokens": 300,
        "temperature": 0.2,
    }
    if model in ("gpt-4o-mini", "gpt-4o", "o4-mini", "o4-mini-2025-01-31"):
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    raw = (resp.choices[0].message.content or "").strip()
    data = extract_json(raw)
    out = (data.get("raw") or data.get("description") or "").strip()
    if not out and isinstance(data, dict):
        out = json.dumps({k: v for k, v in data.items() if k != "raw"}, ensure_ascii=False)[:500]
    return out or "no detail"


def _four_parts_merge_shape(part_texts: dict[str, str]) -> dict[str, str]:
    """Same key order as IndivAID merge_four_part_descriptions.py output."""
    return {
        "body": part_texts.get("body") or "",
        "head": part_texts.get("head") or "",
        "left_ear": part_texts.get("left_ear") or "",
        "right_ear": part_texts.get("right_ear") or "",
    }


def describe_parts_hybrid(
    image_paths: dict[str, Path],
    manual_parts: dict[str, str | None],
    *,
    image_id: str,
    api_key: str | None,
    model: str = "gpt-4o-mini",
    rhino_id_hint: str | None = None,
    four_parts_key: str | None = None,
    llm_regenerate_with_form_hints: bool = False,
) -> dict[str, Any]:
    """
    Default: non-empty manual text wins (no LLM); empty manual + crop -> part LLM.
    If llm_regenerate_with_form_hints: for each part with a crop image, always call LLM and pass
    manual text as context (form + image). Parts without image keep manual text only.
    """
    part_texts: dict[str, str] = {}
    llm_used: list[str] = []
    manual_used: list[str] = []

    if llm_regenerate_with_form_hints:
        for part in PART_ORDER:
            manual = (manual_parts.get(part) or "").strip()
            pth = image_paths.get(part)
            if pth and Path(pth).exists():
                if not api_key or not str(api_key).strip():
                    raise ValueError(
                        f"Part {part} has a crop image; OPENAI_API_KEY is required for LLM regenerate"
                    )
                part_texts[part] = describe_one_part_with_llm(
                    part, Path(pth), api_key, model, form_hint=manual or None
                )
                llm_used.append(part)
            elif manual:
                part_texts[part] = manual
                manual_used.append(part)
            else:
                part_texts[part] = ""
    else:
        for part in PART_ORDER:
            manual = (manual_parts.get(part) or "").strip()
            if manual:
                part_texts[part] = manual
                manual_used.append(part)
                continue
            pth = image_paths.get(part)
            if pth and Path(pth).exists():
                if not api_key or not str(api_key).strip():
                    raise ValueError(
                        f"Part {part} has a crop image but no manual text; OPENAI_API_KEY is required for LLM describe"
                    )
                part_texts[part] = describe_one_part_with_llm(part, Path(pth), api_key, model)
                llm_used.append(part)
            else:
                part_texts[part] = ""

    if not any(part_texts[p].strip() for p in PART_ORDER):
        raise ValueError(
            "At least one part must be filled: provide manual text and/or crop image IDs for parts to describe with LLM"
        )

    base_key = (four_parts_key or image_id).strip() or "unknown"
    base_key = base_key.replace("\\", "/")

    schema_meta: dict[str, Any] = {
        "hybrid_part_descriptions": True,
        "llm_regenerate_with_form_hints": llm_regenerate_with_form_hints,
        "image_id": image_id,
        "four_parts_key": base_key,
        "id": rhino_id_hint or "unknown",
        "llm_parts": llm_used,
        "manual_parts": manual_used,
    }
    merged = _four_parts_merge_shape(part_texts)
    return {
        "part_texts": part_texts,
        "descriptions_four_parts": {base_key: merged},
        "schema": schema_meta,
        "llm_parts_used": llm_used,
        "manual_parts_used": manual_used,
    }


def _crop_rect_to_jpeg(image_path: Path, rect: dict[str, int]) -> Path:
    """Write a JPEG crop to a temp file; caller must unlink."""
    im = Image.open(image_path).convert("RGB")
    x, y = int(rect["x"]), int(rect["y"])
    w, h = int(rect["width"]), int(rect["height"])
    x2, y2 = min(x + w, im.width), min(y + h, im.height)
    if x2 - x < 8 or y2 - y < 8:
        raise ValueError("degenerate crop")
    crop = im.crop((x, y, x2, y2))
    fd = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    p = Path(fd.name)
    fd.close()
    crop.save(p, "JPEG", quality=92)
    return p


def describe_uploaded_image_per_part(
    image_path: Path,
    api_key: str,
    model: str = "gpt-4o-mini",
    *,
    manual_parts: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """
    IndivAID-style: YOLO suggests bboxes per part → one vision LLM call per crop
    (parallel). Missing ears/head → \"unknown\". Body uses full image if no body box.
    Merge shape in schema under descriptions_four_parts.
    """
    from app.services.auto_crop_bbox import suggest_all_part_bboxes

    tmp_paths: list[Path] = []
    try:
        bbox_result = suggest_all_part_bboxes(image_path)
        parts_rect: dict = bbox_result.get("parts") or {}

        jobs: list[tuple[str, Path]] = []

        for part in ("left_ear", "right_ear", "head"):
            r = parts_rect.get(part)
            if not r or int(r.get("width") or 0) < 16 or int(r.get("height") or 0) < 16:
                continue
            try:
                p = _crop_rect_to_jpeg(image_path, r)
                tmp_paths.append(p)
                jobs.append((part, p))
            except Exception as e:
                logger.debug("crop %s skipped: %s", part, e)

        rbody = parts_rect.get("body")
        if rbody and int(rbody.get("width") or 0) >= 16 and int(rbody.get("height") or 0) >= 16:
            try:
                pb = _crop_rect_to_jpeg(image_path, rbody)
                tmp_paths.append(pb)
                jobs.append(("body", pb))
            except Exception:
                jobs.append(("body", image_path))
        else:
            jobs.append(("body", image_path))

        part_texts: dict[str, str] = {
            "left_ear": "unknown",
            "right_ear": "unknown",
            "head": "unknown",
            "body": "unknown",
        }

        hints = manual_parts or {}

        def run_one(part: str, path: Path) -> tuple[str, str]:
            try:
                h = (hints.get(part) or "").strip() or None
                return part, describe_one_part_with_llm(part, path, api_key, model, form_hint=h)
            except Exception as e:
                logger.warning("LLM describe part=%s failed: %s", part, e)
                return part, "unknown"

        order_idx = {p: i for i, p in enumerate(PART_ORDER)}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(run_one, pt, imgp) for pt, imgp in jobs]
            for fu in concurrent.futures.as_completed(futs):
                part, text = fu.result()
                part_texts[part] = text

        llm_parts_ordered = sorted({j[0] for j in jobs}, key=lambda x: order_idx[x])
        merged = _four_parts_merge_shape(part_texts)
        base_key = image_path.stem
        schema: dict[str, Any] = {
            "per_part_llm": True,
            "llm_parts": llm_parts_ordered,
            "bbox_had_crop": {k: bool(v) for k, v in parts_rect.items()},
            "descriptions_four_parts": {base_key: merged},
        }
        return {"schema": schema, "part_texts": part_texts}
    finally:
        for p in tmp_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def describe_single_image(image_path: Path, api_key: str, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """Describe one rhino image with vision model (o4-mini/gpt-4o-mini). Returns part_texts."""
    client = OpenAI(api_key=api_key)
    b64 = encode_image(image_path)
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output only valid JSON. No markdown."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SINGLE_IMAGE_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        "max_tokens": 800,
        "temperature": 0.2,
    }
    if model in ("gpt-4o-mini", "gpt-4o", "o4-mini", "o4-mini-2025-01-31"):
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    raw = resp.choices[0].message.content.strip()
    data = extract_json(raw)
    part_texts = {
        "left_ear": data.get("left_ear") or "unknown",
        "right_ear": data.get("right_ear") or "unknown",
        "head": data.get("head") or "unknown",
        "body": data.get("body") or "unknown",
    }
    return {"schema": data, "part_texts": part_texts}
