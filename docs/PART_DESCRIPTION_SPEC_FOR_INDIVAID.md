# Part description spec — for IndivAID prompt updates

**Audience:** Maintainers updating ear / face / body prompts in IndivAID (e.g. `tools/generate_part_descriptions_*.py`, `describe_part_crops_llm.py`, schema JSON in `describe.py`).

**Goal:** Align vision LLM outputs with rhino re-ID practice: ear notching (including central hole), face/head cues, and body cues — so merged `descriptions_four_parts.json` and app manual fields stay consistent.

---

## 1. Ear (`left_ear`, `right_ear`)

### 1.1 Biology & ID context

- Many populations use **intentional ear notches** for individual ID.
- Two common mark types:
  - **Rim notches** — cuts / V-shapes along the outer ear margin (often coded by position: upper / mid / lower, or numeric schemes).
  - **Central hole** — a **round perforation in the middle of the ear pinna** (punch), not the same as a rim notch.

### 1.2 Hussek-style numeric reminder (for prompt text)

| Animal’s ear | Rim codes (typical) | Central round hole |
|--------------|---------------------|--------------------|
| **Right** | Positions **1–4** along rim | Often recorded as position **5** |
| **Left** | Positions **6–9** along rim | Often recorded as position **10** |

Prompts should ask the model to **separate** rim notches vs **central round hole** when visible. Do not collapse a central punch into “one more rim notch” without stating it is central.

### 1.3 Namibia-style (optional in prompts)

- Edge values may be a **sum code** (e.g. 1, 3, 5, 10, 30, 50).
- **Central hole** may map to **hole_value** 100 / 200 — if the dataset uses this, prompts should output `has_central_hole` and `hole_value` where relevant.

### 1.4 Vocabulary to reinforce in prompts

| Concept | Model should mention when visible |
|---------|-----------------------------------|
| **Edge condition** | intact, or **torn** as a list (one entry per damaged area: notches, rim position, central_hole, optional note) |
| **Rim notch count** | 0, 1, 2, 3+ |
| **Rim notch position** | top, mid, bottom, mixed |
| **Center of pinna** | **round hole** (ID punch), **irregular** opening, or absent |
| **Tuft** | hair tuft at ear tip present / absent |

### 1.5 rhino_app manual strings (target alignment)

Examples embedded in training text:

- `edge intact; notches 1; position top; central_hole none; tuft present`
- `central_hole round_middle` — explicit **round hole in middle of ear**

### 1.6 IndivAID schema gap (suggested extension)

Current aggregated schema in `rhino_app/backend/app/services/describe.py` (`ears.left_ear` / `right_ear`) has `edge_status`, `notches_count`, `notch_positions`, `tuft` but **no** `central_hole` or `center` in `notch_positions`.

**Suggested additions** for schema + `schema_record_to_part_texts`:

- `notch_positions`: add **`center`** when the main mark is central (or keep rim-only as top|mid|bottom|mixed).
- New optional fields: `central_hole: none|round|irregular|unknown`, or boolean `has_central_round_hole`.

Until schema is extended, prompts should still **spell out** “central round hole” in free-text / `raw` so it flows into part descriptions.

### 1.7 Files in IndivAID to review

- `tools/generate_part_descriptions_gpt.py` — Hussek / Namibia / detailed ear prompts  
- `tools/generate_part_descriptions_llava.py` — same  
- `tools/generate_part_descriptions_claude.py`  
- `tools/describe_part_crops_llm.py` — `PART_PROMPTS` for left/right ear  
- `docs/description_detail_guide.md` — ear table (extend with central hole)

---

## 2. Face / head (`head`, schema `head_face`)

### 2.1 What “face” means here

Crop is **head + face + horns** (same individual, same capture). Focus on **re-ID**, not generic captioning.

### 2.2 Fields to extract (align with `SCHEMA_INSTRUCTIONS` + app manual)

| Area | Elements |
|------|----------|
| **Viewpoint** | front, front_left, front_right, side_left, side_right, rear (camera-relative) |
| **Horns** | Count 1 / 2; front & rear: length (short/medium/long), broken, blunt/sharp, curved/straight |
| **Eyes / brow** | Scar near eye: none / left / right / both; wrinkle density low/medium/high |
| **Muzzle** | Nose wrinkles; muzzle shape **round** vs **elongated** |
| **Distinctive** | Short free text: scars, asymmetry, cuts, unique folds |

### 2.3 rhino_app manual (condensed horn labels)

Manual form uses combined horn phrases, e.g. `short blunt`, `long sharp`, `curved`, `straight`. Prompts can map to `front_horn_shape` / `rear_horn_shape` enums in schema.

### 2.4 Prompt discipline

- Only **visible** evidence; use **unknown** when occluded.
- Prefer **comparative** terms (blunt vs sharp, round vs elongated muzzle) over “large horn” alone.

### 2.5 Files to review

- `describe.py` — `head_face` block in `SCHEMA_INSTRUCTIONS`  
- `tools/describe_part_crops_llm.py` — `PROMPT_HEAD`  
- `tools/generate_part_descriptions_*.py` — head sections  
- `docs/description_detail_guide.md` — head_face table  

---

## 3. Body (`body`, schema `full_body`)

### 3.1 Scope

**Torso + limbs visible in frame** — posture, bulk, skin, mud, scars/wounds.

### 3.2 Fields (schema + manual)

| Concept | Values / notes |
|---------|----------------|
| **Framing** | full body vs partial in frame |
| **Build** | small / medium / large |
| **Back line** | flat vs arched (if visible) |
| **Skin** | smooth, moderate_wrinkle, heavy_wrinkle |
| **Mud / dust** | none / light / heavy; location legs, flank, back, mixed |
| **Marks** | Free text: scars, open wounds, unusual patches |

### 3.3 Prompt discipline

- Distinguish **mud pattern** from **skin scar**.
- **Heavy wrinkle** on shoulder/flank is a strong ID cue — encourage short location-tagged phrases.

### 3.4 Files to review

- `describe.py` — `full_body` in `SCHEMA_INSTRUCTIONS`  
- `tools/describe_part_crops_llm.py` — `PROMPT_BODY` (body crop)  
- `docs/description_detail_guide.md` — full_body table  

---

## 4. Cross-reference: four-part text shape

Training often consumes one JSON entry per image base:

```json
{
  "left_ear": "<string>",
  "right_ear": "<string>",
  "head": "<string>",
  "body": "<string>"
}
```

Order in `merge_four_part_descriptions.py`: **body**, **head**, **left_ear**, **right_ear** — same semantic content.

Prompts should produce **dense, comparable** phrases (not “a rhino standing”) so **contrastive** learning can separate individuals.

---

## 5. Checklist for IndivAID PR

- [ ] Ear prompts: explicit **central round hole** vs rim notches; Hussek 5 / 10 mentioned where useful.  
- [ ] Ear JSON (if extended): `central_hole` or equivalent + optional `center` in positions.  
- [ ] Head prompts: horns (both if 2), muzzle round/elongated, eye scars, wrinkle level.  
- [ ] Body prompts: skin texture, mud vs scar, size, partial/full.  
- [ ] Re-run sample crops; compare to `docs/description_detail_guide.md` “sufficient detail” examples.  
- [ ] If schema JSON changes, update `rhino_app` `SCHEMA_INSTRUCTIONS` + `schema_record_to_part_texts` in lockstep.

---

## 6. Contact artifact

This file is the **handoff spec** from **rhino_app** → **IndivAID**: path  

`rhino_app/docs/PART_DESCRIPTION_SPEC_FOR_INDIVAID.md`

Related: [EAR_NOTCH_AND_CENTRAL_HOLE.md](EAR_NOTCH_AND_CENTRAL_HOLE.md), [CHECKPOINTS_AND_DESCRIPTION_PARTS.md](CHECKPOINTS_AND_DESCRIPTION_PARTS.md).
