# Checkpoints (crop) + UI form → `description_parts` JSON

How **body.pt**, **ear.pt**, and **head.pt** relate to the four description parts, and how the **UI form** combines with them to produce per-part text stored as JSON.

---

## 1. Three weight files → four image regions

| Checkpoint | Role |
|------------|------|
| **body.pt** | Detect and **crop full body** (whole rhino). That crop corresponds to the **body** description part. |
| **head.pt** *(or a shared `best.pt` head class)* | Detect and **crop the head** (face, horn region). Used for the **head** part. |
| **ear.pt** | Detect **ears** (YOLO class `ear`; often alongside face/horn). There is **no separate left/right class** — side is inferred from **bbox position relative to the frame / head** (see below). |

### Left vs right ear convention (important)

Assume the **rhino faces the camera** (same as IndivAID `crop_rhino_regions.py`):

- Ear on the **left side of the image** (smaller x) → animal’s **right ear** → store as **right_ear**.
- Ear on the **right side of the image** (larger x) → animal’s **left ear** → store as **left_ear**.

So **ear.pt** = detect ears + **spatial assignment** → **left_ear** / **right_ear** crops.

Summary:

1. **body** → one full-body crop.  
2. **head** → one head crop.  
3. **ear** → up to two ear boxes → **left_ear** and **right_ear** by the rule above.

---

## 2. Four keys in app JSON

Each image may store:

```json
{
  "left_ear": "description string",
  "right_ear": "description string",
  "head": "description string",
  "body": "description string"
}
```

This object is **`description_parts`**: four fixed keys, values are **text** (often `key value` segments joined with `;`, e.g. `edge intact; notches 1`).

---

## 3. UI form maps to the four parts

The Gallery / manual description form follows `MANUAL_OPTIONS` in the frontend:

| JSON part | Form fields |
|-----------|-------------|
| **left_ear** | edge, notches, position (notch position), tuft |
| **right_ear** | same structure as left_ear |
| **head** | viewpoint, horn, muzzle, wrinkles |
| **body** | skin, size, viewpoint (full/partial) |

Selections are concatenated per part, e.g.:

- `left_ear`: `edge intact; notches 1; position top; tuft present`
- `head`: `viewpoint front_left; horn short blunt; muzzle round; wrinkles medium`

Optional **note** is often appended on **body** as `… note: …`.

The API receives **`description_parts`** as four strings.

---

## 4. Combining YOLO crops with form / LLM

High-level flow:

```
Source image
  ├─ body.pt   → full-body crop  ─┐
  ├─ head.pt   → head crop        ─┼─→ (optional) vision LLM → large schema → four strings
  └─ ear.pt    → L/R ears         ─┘
                                    │
Manual form ────────────────────────┴→ override / edit keys in description_parts
```

- **Form only**: no YOLO required; user fills four parts from the full image.  
- **With crops**: clearer **left_ear / right_ear / head / body** images → better LLM or human labels; values can still be merged with the form.

The rhino_app backend multi-image describe endpoint sends crops to the LLM in order: **left ear, right ear, head, full body** — aligned with these four parts.

---

## 5. One-line summary

- **body.pt** → full-body crop.  
- **head.pt** → head crop.  
- **ear.pt** → ear detection + **position vs frame/head** → **left_ear** / **right_ear**.  
- **UI form** → manual (or post-LLM) fill for all four keys → **`description_parts`** JSON for Re-ID and storage.

---

## 6. Code references

| Topic | Location |
|-------|----------|
| Form options per part | `frontend/src/constants/manualOptions.ts` |
| String build + notes | `buildManualParts`, `buildManualPartsWithNotes` (same file) |
| DB field | `backend/app/models.py` (`RhinoImage.description_parts`) |
| LLM prompt (4 images) | `backend/app/services/describe.py` (`SCHEMA_INSTRUCTIONS`) |
| YOLO crop + L/R rule | `IndivAID/tools/crop_rhino_regions.py` |

Checkpoints under `rhino_app/checkpoint/` (`body.pt`, `head.pt`, `ear.pt`) are used with the same crop logic when calling IndivAID scripts with matching `--weights`.

---

## 7. Hybrid API describe → `descriptions_four_parts.json`

`POST /gallery/images/describe` returns **`descriptions_four_parts`**: same shape as IndivAID `merge_four_part_descriptions.py` output:

- One object keyed by **`four_parts_key`** or `image_id`.
- Each value: **`body`**, **`head`**, **`left_ear`**, **`right_ear`** (string per part).

Rules: non-empty manual → no LLM for that part; empty manual + crop image ID → part-specific LLM; otherwise `""`. With **`llm_regenerate_with_form_hints`**, the LLM sees form text + each part image (capture **detail page**). List upload uses a single crop + optional manual or o4-mini only; four-part hybrid → **`/{identity_id}/img/{image_id}`**.

Example: [`data/descriptions_four_parts.example.json`](../data/descriptions_four_parts.example.json).

**DB import (no ATRW):** `python migrate_split_four_parts.py --split-root …/rhino_split --descriptions …/descriptions_four_parts.json`
