---
project_name: rhino_app
user_name: Roy
date: '2026-03-23'
sections_completed:
  - technology_stack
  - language_rules
  - framework_rules
  - testing_rules
  - quality_rules
  - workflow_rules
  - anti_patterns
status: complete
rule_count: 42
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

| Layer | Technology | Notes |
|-------|------------|--------|
| Backend | Python 3.12+ (project venv under `backend/.venv`) | Match team runtime. |
| API | FastAPI `0.115.6`, Uvicorn `0.32.1` | Async-first; OpenAPI at `/docs`. |
| DB | SQLAlchemy `2.0.36`, async (`asyncpg` / `aiosqlite`) | Models in `backend/app/models.py`. |
| Auth | `python-jose`, `bcrypt` | JWT bearer; see `backend/app/auth.py`. |
| Validation | Pydantic `2.10.x`, pydantic-settings `2.6.x` | Settings in `backend/app/config.py`. |
| Vision / ML | OpenAI `1.55.x`, Pillow `11.x`, optional `ultralytics` | Describe + YOLO crop suggest. |
| Re-ID | `ai_core/` in-process (Torch) or IndivAID subprocess | Requires `INDIVAID_ROOT`, weights, gallery `train/` + `gallery/`. |
| Frontend | React `19.2.x`, Vite `7.3.x`, TypeScript `5.9.x` | Strict TS; `verbatimModuleSyntax`. |
| HTTP client | Axios `^1.13` | Base URL `/api` (Vite proxy strips prefix to backend). |
| Routing | react-router-dom `7.x` | Browser router; token in `localStorage`. |

**Dev proxy:** `frontend/vite.config.ts` proxies `/api` → `http://127.0.0.1:8000` with path rewrite (`/api` removed). Backend routes have **no** `/api` prefix.

---

## Critical Implementation Rules

### Language-Specific Rules

**English only (mandatory)** — Read `docs/LANGUAGE_POLICY.md` and root `AGENTS.md`. All code, comments, UI strings, API error `detail` messages, and markdown under `rhino_app/` must be **English**. Do not add Vietnamese or other locales in this tree.

**Python**

- Use **async** session patterns already in routers (`AsyncSession`, `get_db`).
- New settings belong in `Settings` in `config.py` with `.env` documentation in `backend/.env.example` when adding vars.
- Paths for uploads resolve under `settings.UPLOAD_DIR`; IndivAID paths resolve via `settings.indivaid_root` (relative to **`backend/`**, not CWD).
- Re-ID service entry is `app.services.predict.run_reid_top5`; prefer fixing callers over duplicating IndivAID invocation.

**TypeScript**

- `strict: true`, `noUnusedLocals`, `noUnusedParameters`, `verbatimModuleSyntax` — use `import type` where needed; avoid unused bindings.
- Follow existing import style in `frontend/src` (named exports, `.tsx` for components).

### Framework-Specific Rules

**FastAPI**

- New HTTP surface lives under `backend/app/routers/` and is **included** in `main.py`.
- Use `Depends(get_current_user)` for protected routes; respect admin-only checks where gallery already gates create/update identity.
- Rate limiting applies to predict routes (`check_predict_rate_limit`).

**React**

- Primary UI for Re-ID + gallery is `frontend/src/pages/Gallery.tsx` (routes `/` and `/lists`). Other pages: `Dashboard` (`/dashboard`), `Lists` (`/list-management`), `Predict` (`/predict/single`), `RhinoImageDetail` (`/:identityId/img/:imageId`) — see `frontend/src/App.tsx` and `docs/FRONTEND_UX_AND_BACKEND_LOGIC.md`. UI refresh planning: `docs/UI_UPDATE_AND_DESIGN_SYSTEM.md`.
- API calls use `frontend/src/api.ts` axios instance with `Authorization: Bearer <token>`; 401 clears token and redirects to `/login`.
- Static images use `/uploads/...` URLs (proxied in dev).

### Testing Rules

- Backend: **pytest** smoke tests in `backend/tests/` (see `docs/DOCUMENTATION.md`, section 8). Frontend: `npm run lint` only unless Vitest or E2E is added later.
- Complement manual checks: backend `/docs`, frontend dev server, and documented sync scripts in `docs/DOCUMENTATION.md`.

### Code Quality & Style Rules

- Match neighboring file style: routers thin, heavy logic in `app/services/`.
- Keep changes minimal and scoped; avoid drive-by refactors (see user preferences).
- `Gallery.tsx` is very large — new UI should extract components rather than growing the file further when touching that area.

### Development Workflow Rules

- Backend cwd for scripts: `rhino_app/backend/` (see `docs/DOCUMENTATION.md`).
- Environment: copy `backend/.env.example` → `backend/.env`; never commit secrets.
- CORS in `main.py` allows `localhost:5173` / `127.0.0.1:5173` for Vite.

### Critical Don't-Miss Rules

- **Subprocess Re-ID fallback** uses a **unique tempfile** for JSON output and deletes it in a `finally` block (`backend/app/services/predict.py`).
- **OPENAI_API_KEY** required for LLM describe endpoints; return clear HTTP errors when missing (existing routes use 503).
- **Gallery layout for Re-ID:** under `uploads`, `reid_atrw` or `gallery_atrw` must expose `train/` and `gallery/` for in-process engine.
- **Four-part descriptions:** schema and part keys align with `docs/CHECKPOINTS_AND_DESCRIPTION_PARTS.md` — do not invent divergent JSON shapes without updating docs and consumers.
- **Database migrations:** `main.py` uses additive `ALTER TABLE` for legacy DBs; new columns should be reflected in `models.py` and optionally in the same migration hook for SQLite/Postgres parity.

---

## Usage Guidelines

**For AI agents**

- Read this file and `docs/LANGUAGE_POLICY.md` before editing `rhino_app/`.
- Prefer the more restrictive option when unsure (English-only, async DB, existing service entry points).
- Update this file when stack versions or non-obvious conventions change.

**For humans**

- Keep this file lean; remove rules that become obvious over time.
- Re-run or edit after major dependency or architecture changes.

Last updated: 2026-03-23
