# Rhino Re-ID App — Documentation

> **Language:** This project uses **English only** for code and documentation. See **[LANGUAGE_POLICY.md](LANGUAGE_POLICY.md)** — required reading for contributors and AI assistants to avoid mixed-language output.

The **Rhino Re-ID** app covers gallery management, vision-based descriptions, re-identification, and human confirmation of predictions.

---

## 1. Overview

| Layer      | Technology                          |
|-----------|--------------------------------------|
| Backend   | FastAPI, SQLAlchemy (async), PostgreSQL or SQLite |
| Frontend  | React (Vite), TypeScript            |
| ML / AI   | IndivAID checkpoint for embedding search; OpenAI (e.g. o4-mini) for image description JSON |

Users upload rhino images, run predictions against a reference gallery, confirm or correct identities, and maintain per-image descriptions (manual or LLM-assisted).

---

## 2. Repository layout

```
rhino_app/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, CORS, static /uploads
│   │   ├── config.py        # Settings from .env
│   │   ├── database.py      # Async engine & sessions
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── auth.py          # JWT / password hashing
│   │   └── routers/         # auth, lists, gallery, predict, crop
│   ├── init_db.py           # Schema + default admin user
│   ├── uploads/             # gallery, predict, crops (created at runtime)
│   └── requirements.txt
├── frontend/
│   └── src/                 # pages, API client, contexts
├── docs/
│   ├── DOCUMENTATION.md                    # This file
│   ├── LANGUAGE_POLICY.md                  # English-only rule (code + docs)
│   ├── FRONTEND_UX_AND_BACKEND_LOGIC.md    # Routes, Gallery modes, API mapping
│   ├── BUSINESS_LOGIC.md                    # Product decision rules and status flow
│   ├── UI_UPDATE_AND_DESIGN_SYSTEM.md      # Tokens, phases, inventory for UI refresh
│   ├── PRODUCTION_CHECKLIST.md             # Secrets, HTTPS, DB, go-live
│   ├── SERVER_INSTALL.md                   # Linux server install (nginx, systemd, DB)
│   ├── DEPLOY_DATA_SYNC.md                 # Git + data to copy (env, IndivAID, weights, init_db)
│   └── CHECKPOINTS_AND_DESCRIPTION_PARTS.md # body/ear/head + UI form → JSON
├── AGENTS.md                # Pointers for AI tools (links language policy)
├── README.md                # Quick start
└── LOCALHOST.md             # PostgreSQL localhost setup
```

---

## 3. Environment variables (backend)

Copy `backend/.env.example` to `backend/.env` and set:

| Variable         | Purpose |
|------------------|---------|
| `SECRET_KEY`     | JWT signing; use a strong random value in production |
| `OPENAI_API_KEY` | OpenAI API for description generation |
| `DATABASE_URL`   | e.g. `postgresql+asyncpg://user@localhost:5432/rhino_app` or SQLite |
| `INDIVAID_ROOT`  | Optional: path to IndivAID repo root (for prediction + high-quality gallery seed) |
| `MODEL_WEIGHT`   | Path to `.pth` / `.pt` or directory containing checkpoint |
| `INDIVAID_REID_CONFIG` | IndivAID config YAML path (relative to `INDIVAID_ROOT`), e.g. `vit_prompt_injected_finetune_wildlife_unfreeze.yml` |
| `INDIVAID_REID_TEXT_DESC_PATH` | Optional; part-description JSON path (under IndivAID root) so inference matches server eval |
| `INDIVAID_REID_USE_WHOLE_BODY_ONLY` | Optional `true`/`false`; overrides YAML if set |

**Download latest finetuned `.pth`** and **sync ATRW test data**: [REID_CHECKPOINT_FROM_SERVER.md](REID_CHECKPOINT_FROM_SERVER.md). **Populate Re-ID gallery + DB:**

```bash
cd rhino_app/backend
python sync_reid_test_data.py --atrw-root ../../IndivAID/data/rhino_atrw_format \
  --descriptions ../../IndivAID/data/rhino_part_descriptions_four_atrw.json
```

**Recommended Re-ID test flow** (train+gallery in DB only; query on disk for reference):

```bash
cd backend   # if already in rhino_app/   OR   cd rhino_app/backend from repo root
python init_db.py --reset --no-high-quality
python sync_reid_test_data.py --atrw-root ../../IndivAID/data/rhino_atrw_format \\
  --descriptions ../../IndivAID/data/rhino_part_descriptions_four_atrw.json
```

- `uploads/reid_atrw/`: `train/` + `gallery/` + empty `query/`. **Gallery is filled to all 19 pids** (train copy per missing id) unless `--no-full-gallery`. One-shot fix: `python sync_reid_test_data.py --ensure-full-gallery-only`.
- `uploads/reid_query_reference/`: copy of query jpgs + README (**not in DB**).
- PID display names: [ATRW_RHINO_PID_TABLE.md](ATRW_RHINO_PID_TABLE.md) / `backend/data/atrw_rhino_pid_names.json`.

In-process Re-ID: **[../ai_core/README.md](../ai_core/README.md)** (requires `torch`).

See `.env.example` for examples and comments.

---

## 4. Setup

**Working directory:** backend scripts live in `rhino_app/backend/`. From repo root use `cd rhino_app/backend`; if you are already inside `rhino_app/`, use `cd backend` only.

1. **Database**: Create DB (PostgreSQL) or use SQLite URL.
2. **Backend**: `pip install -r requirements.txt`, then `python init_db.py` (creates tables and default user **admin** / **admin**).
3. **Frontend**: `npm install`, `npm run dev`.

### Import `rhino_split` + `descriptions_four_parts.json` (no ATRW)

JSON keys like `IdentityFolder/image_stem`; values `{ body, head, left_ear, right_ear }` (same as `merge_four_part_descriptions.py`).

```bash
cd rhino_app/backend
python migrate_split_four_parts.py \
  --split-root ../../IndivAID/data/rhino_split \
  --descriptions ../../IndivAID/Rhino_photos/high_quality_cropped_parts/descriptions_four_parts.json
```

- **RhinoList** + one **RhinoIdentity** per identity folder name; images under `uploads/from_split/{split}/{identity}/{stem}.ext`.
- `--dry-run` to preview.

### Optional: `rhino_atrw_format` import

If you already use ATRW-renamed files:

```bash
python migrate_atrw_to_db.py --atrw-root ../../IndivAID/data/rhino_atrw_format \
  --split-source ../../IndivAID/data/rhino_split \
  --descriptions ../../IndivAID/.../descriptions_four_parts.json
```

`--descriptions` accepts **descriptions_four_parts.json** (lookup by identity/stem-style keys) or legacy stem-key JSON.

### Sync `high_quality_cropped` + `high_quality_cropped_parts`

Imports full-frame images from `high_quality_cropped/<identity>/` as **anchor** rows (`source_stem` = file stem, e.g. `10_rhino`), and part crops from `high_quality_cropped_parts/<identity>/` (`10_rhino_left_ear.jpg`, …) with `parent_image_id` pointing at the anchor (for **re-crop from parent** in the UI). Optional `--descriptions` attaches four-part text and creates an initial active **description version**.

```bash
cd rhino_app/backend
python migrate_sync_hq_cropped.py \
  --cropped-root ../../IndivAID/Rhino_photos/high_quality_cropped \
  --parts-root ../../IndivAID/Rhino_photos/high_quality_cropped_parts \
  --descriptions ../../IndivAID/Rhino_photos/high_quality_cropped_parts/descriptions_four_parts.json
```

Use `--dry-run` / `--skip-existing` as needed. Gallery **Captures** groups by `source_stem`; **Detail** shows part thumbnails, version timeline (**Set active**), **Edit part description**, and **Re-crop** when `parent_url` exists.

### Capture detail page (four crops + LLM)

**Capture detail** (`/{identity_id}/img/{image_id}`): only **part rows** (crop left, form right) + save / LLM — no separate “main image” step (that lives in the Re-ID / Add-rhino popup). API: **`GET …/capture-detail`**, **`POST …/part-crop-from-parent`**, describe with **`llm_regenerate_with_form_hints`** + **`anchor_image_id`**.

**Re-ID & Add-rhino popup:** **Step 1** — `body.pt` once per new image; returning from step 2 **reuses** the last stencil (no re-detect). **Step 2** — part thumbnails from **`/crop/suggest-part-bboxes`** once per file; **pencil** opens **manual crop** for that part (no re-run YOLO). `← Main crop` adjusts step 1 manually.

Default URLs: API `http://localhost:8000`, app `http://localhost:5173`. Full steps: **README.md** and **LOCALHOST.md**.

---

## 5. API (summary)

Interactive docs: `http://localhost:8000/docs`.

| Router        | Role |
|---------------|------|
| `auth_router` | Login, JWT |
| `lists_router`| Rhino lists / identities |
| `gallery_router` | Upload images, hybrid four-part describe (manual + per-part LLM), export |
| `predict_router` | **POST /predict/upload** single query; **POST /predict/upload-set** multiple images → one finalized pid (mean embedding; majority per-image top-1 if more than half agree). Weak per-image scores (below `REID_LOW_SCORE_THRESHOLD`) are copied to `uploads/reid_demo_not_in_gallery/<id>/` for demo. **POST /predict/describe-file** per-part LLM + merge |
| `crop_router`  | Server-side crop; **suggest-bbox** (YOLO body/head checkpoint) for step-1 auto stencil |

Static files under `/uploads` mirror the `uploads/` directory on disk.

---

## 6. Frontend (English UI)

**Detailed behavior (routes, Re-ID vs list mode, `api.ts` map):** **[FRONTEND_UX_AND_BACKEND_LOGIC.md](FRONTEND_UX_AND_BACKEND_LOGIC.md)**.

**UI refresh / design system (tokens, file inventory, phased rollout):** **[UI_UPDATE_AND_DESIGN_SYSTEM.md](UI_UPDATE_AND_DESIGN_SYSTEM.md)**.

**Product decision rules (predict, draft/report/review/junk lifecycle):** **[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)**.

- **Re-ID home**: Build a **set** of cropped images → **Predict** calls **upload-set** once; UI shows final ID, gallery match image, per-image breakdown, and link to the weak-match demo folder when applicable.
- **Gallery / workflow**: Upload → predict → **Unconfirmed** queue: confirm predicted ID, pick another identity, or **Report (wrong prediction)** and submit the correct identity.
- **Confirmed** section lists accepted predictions.
- **Draft / confirmed**: Draft items are not yet reviewed; **Confirm** moves them to confirmed.
- Image tools: crop, edit description (manual IndivAID-style parts + optional shared note).

All user-visible strings in the app source are in **English**.

---

## 7. Security notes

- Change default admin password and `SECRET_KEY` before any production use.
- Do not commit `.env` or API keys.
- Structured go-live steps: **[PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)**.
- Server setup (Ubuntu-style, nginx, systemd, PostgreSQL): **[SERVER_INSTALL.md](SERVER_INSTALL.md)**.

## 8. Automated tests (backend)

From `rhino_app/backend/` with dev dependencies installed:

```bash
pip install -r requirements-dev.txt
pytest -v
```

Smoke tests live in `backend/tests/test_smoke.py` (root, OpenAPI, auth on `/predict/history`).

---

## 9. Troubleshooting

- **Backend won’t start**: Check `DATABASE_URL` and that PostgreSQL is running (if used).
- **Predict fails**: Verify `MODEL_WEIGHT` and `INDIVAID_ROOT` paths; ensure OpenAI key if using LLM description.
- **CORS / API errors**: Frontend dev server proxies `/api` and `/uploads` to the backend; ensure backend runs on the port expected by Vite config.

For local PostgreSQL commands and login defaults, see **LOCALHOST.md**.

**Checkpoints & four-part descriptions:** [CHECKPOINTS_AND_DESCRIPTION_PARTS.md](CHECKPOINTS_AND_DESCRIPTION_PARTS.md)  
**Ear notch + central hole (UI):** [EAR_NOTCH_AND_CENTRAL_HOLE.md](EAR_NOTCH_AND_CENTRAL_HOLE.md)  
**IndivAID prompt handoff (ear / face / body):** [PART_DESCRIPTION_SPEC_FOR_INDIVAID.md](PART_DESCRIPTION_SPEC_FOR_INDIVAID.md) — `body.pt` / `ear.pt` / `head.pt`, `left_ear` / `right_ear` / `head` / `body`, and how the UI form maps to `description_parts` JSON.
