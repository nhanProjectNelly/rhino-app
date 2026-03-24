# Frontend UX and Backend Logic

> Companion to **[DOCUMENTATION.md](DOCUMENTATION.md)**. Describes **current** routing, UI modes, client–server contracts, and backend responsibilities so contributors and AI agents share one mental model.

---

## 1. Request path (all clients)

- Browser calls **`/api/...`** (Vite dev proxy strips `/api` and forwards to the FastAPI app on port 8000).
- Images and uploads use **`/uploads/...`** (also proxied in dev).
- Axios instance: `frontend/src/api.ts` — attaches `Authorization: Bearer <token>` from `localStorage`; on **401** clears token and redirects to **`/login`**.

---

## 2. Authentication (FE + BE)

| Concern | Frontend | Backend |
|--------|----------|---------|
| Token storage | `localStorage` key `token` | JWT issued by `/auth/login` and `/auth/register` |
| Session resolution | `AuthContext`: if token exists, calls **`GET /auth/me`** on load | `auth_router`: JWT `sub` = username |
| Role | `role: 'admin' \| 'user' \| null` from `/auth/me` | `User.role` in DB |
| Protected UI | `Protected` wrapper: no token → redirect `/login` | Protected routes use `Depends(get_current_user)` |
| Admin-only API | UI may hide actions; enforcement is **always** server-side | `require_admin` on selected gallery/list operations |
| Predict throttling | Transparent to UI (errors if rate limited) | `check_predict_rate_limit`: stricter for non-`admin` |

---

## 3. Routing and shell

| Route | Component | Purpose |
|-------|-----------|---------|
| `/login` | `Login` | Register / login; stores token via `AuthContext.login` |
| `/` | `Layout` → `Gallery` | **Re-ID mode** (see §4) |
| `/lists` | Same `Gallery` | **Rhino list mode** — paged identities, gallery management |
| `/dashboard` | `Dashboard` | Hub links to list management, rhino list, Re-ID, single predict |
| `/list-management` | `Lists` | CRUD rhino **lists** and migrate identities between lists |
| `/predict/single` | `Predict` | Single-image predict, confirm, assign (legacy path; still supported) |
| `/:identityId/img/:imageId` | `RhinoImageDetail` | One **capture** (anchor + part slots), descriptions, re-crop |

---

## 4. `Gallery.tsx`: two UX modes (single component)

**Detection:** `const isReID = location.pathname === '/'` — **`/` = Re-ID**, **`/lists` = Rhino list**.

### 4.1 Re-ID mode (`/`)

- **Goal:** Build a **batch** of query images (`batchItems`), optionally describe each, then run **one** set prediction.
- **Identity list:** `gallery.getIdentities({ all: true })` — all active identities for dropdowns (confirm/report).
- **Batch pipeline:**
  1. User adds files → each item can open a **two-step popup**: Step 1 body crop (YOLO stencil via `crop.suggestBbox`), Step 2 part thumbnails + `describeFile` or manual hints → merged `description_parts` stored on the batch item.
  2. **Predict (set only)** calls `predict.uploadSet(files, descriptionPartsPerImage)` → `POST /predict/upload-set` — backend writes `predict/set_<id>/`, runs Re-ID, persists `PredictionRecord`, returns `prediction_id`, `top_k`, `finalize`, `per_image`, optional weak-match demo URL.
- **After predict:** UI shows top-5, confirm into gallery, or **Report** → modal → `predict.report(prediction_id, correct_identity_id)`.
- **History:** `predict.history()` — list with `reported`, `top5_json`, etc.

### 4.2 Rhino list mode (`/lists`)

- **Goal:** Paginated **identities** (`gallery.getIdentities` with `page`, `q`), select identity → **images** (`gallery.getImages`), upload/add rhino with same **popup** pattern (add image vs Re-ID copy differs in titles only).
- **Admin actions** (when `role === 'admin'`): create/update/deactivate identity, etc., per UI gates + API.

### 4.3 Shared popup (crop + describe)

- Uses `ImageCropper`, `crop.suggestBbox` / `crop.suggestPartBboxes`, optional `predict.describeFile` for per-part LLM text.
- **Re-ID** vs **Add image** only changes labels (`Re-ID — step 1` vs `Add image — step 1`).

---

## 5. `RhinoImageDetail.tsx`: capture-centric editing

- **Load:** `GET /gallery/images/:id/capture-detail?identity_id=` — returns **anchor** image, **slots** per part (`left_ear`, `right_ear`, `head`, `body`), `canonical_description_parts`.
- **Save manual text:** `PATCH /gallery/images/:id/description` with part fields.
- **LLM regenerate:** `POST /gallery/images/describe` with part image ids and optional `llm_regenerate_with_form_hints`, `anchor_image_id`.
- **Re-crop part:** `partCropFromParent` uploads new crop tied to `parent_image_id`.
- **No full-frame-only step on this page** — full workflow for new uploads lives on `Gallery` (per DOCUMENTATION).

---

## 6. Backend logic by router (concise)

| Router | Role |
|--------|------|
| **`auth_router`** | Login/register, bcrypt, JWT; `/auth/me` |
| **`lists_router`** | CRUD lists; identities under list; **migrate** identities between lists |
| **`gallery_router`** | Identities (search/pagination, admin create/patch/deactivate); **upload** / **upload-with-description**; images list with filters; **capture-detail** / **captures**; description **versions**; **confirm** / **deactivate** image; **export-indivaid**; hybrid **describe** |
| **`predict_router`** | **describe-file** (YOLO + LLM parts); **upload** single; **upload-set** (multi-file → one aggregated result + `PredictionRecord`); **confirm**, **report**, **assign**, **PATCH top**; **history**; weak-match copies to `reid_demo_not_in_gallery/` when per-image score low |
| **`crop_router`** | Server-side **crop**; **suggest-bbox** (body/head); **suggest-part-bboxes** (all parts) |

**Services:**

- **`services/predict.py`:** `run_reid_top5` → `ai_core.reid_engine` if Torch + gallery `train/` exist, else subprocess IndivAID script.
- **`services/describe.py`:** OpenAI vision, per-part and hybrid flows; used by gallery and predict.
- **`services/auto_crop_bbox.py`:** YOLO for bbox suggestions (optional weights under project `checkpoint/`).

**Persistence:** See `models.py` — `User`, `RhinoList`, `RhinoIdentity`, `RhinoImage`, `RhinoDescriptionVersion`, `PredictionRecord`.

---

## 7. Client API surface (`api.ts` → backend)

| Client export | Main HTTP usage |
|---------------|-----------------|
| `auth` | `/auth/login`, `/auth/register`, `/auth/me` |
| `lists` | `/lists`, `/lists/:id/identities`, `/lists/migrate` |
| `gallery` | `/gallery/identities`, `/gallery/images`, uploads, capture-detail, describe, description versions, etc. |
| `predict` | `/predict/describe-file`, `/upload`, `/upload-set`, `/confirm`, `/report`, `/assign`, `/top`, `/history` |
| `crop` | `/crop/image`, `/crop/suggest-bbox`, `/crop/suggest-part-bboxes` |

---

## 8. BMad / AI usage

- This file is part of **`project_knowledge`** for BMad (`_bmad/bmm/config.yaml` → `docs/`).
- **`bmad-help`** workflows can use **`docs/*.md`** for grounding; keep this document updated when UX or router behavior changes.

---

## 9. Change checklist

When adding a feature:

1. Extend **`api.ts`** and backend router consistently.
2. If new user-visible copy, keep **English** ([LANGUAGE_POLICY.md](LANGUAGE_POLICY.md)).
3. Update **DOCUMENTATION.md** API summary if the public contract changes.
4. Update **this file** if routing, modes, or primary flows change.
