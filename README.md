# Rhino Re-ID App

Rhino gallery, re-identification, and description tooling.

**English only** for all code and docs in this folder — see [docs/LANGUAGE_POLICY.md](docs/LANGUAGE_POLICY.md) (also for AI/codegen). Cursor/agents: [AGENTS.md](AGENTS.md).

- [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) — full developer guide  
- [docs/REID_CHECKPOINT_FROM_SERVER.md](docs/REID_CHECKPOINT_FROM_SERVER.md) — scp latest `.pth` + `.env` for Re-ID  
- [ai_core/README.md](ai_core/README.md) — in-process set-to-set Re-ID (IndivAID pipeline); `backend/sync_reid_test_data.py` syncs ATRW → `uploads/reid_atrw` + DB  
- [docs/PART_DESCRIPTION_SPEC_FOR_INDIVAID.md](docs/PART_DESCRIPTION_SPEC_FOR_INDIVAID.md) — ear / face / body spec for IndivAID prompt updates  
- [docs/CHECKPOINTS_AND_DESCRIPTION_PARTS.md](docs/CHECKPOINTS_AND_DESCRIPTION_PARTS.md) — YOLO crops + UI form → JSON  
- [LOCALHOST.md](LOCALHOST.md) — PostgreSQL localhost setup  
- [docs/SERVER_INSTALL.md](docs/SERVER_INSTALL.md) — production server install (nginx, systemd, PostgreSQL)  

## Run backend (FastAPI)

```bash
cd rhino_app/backend
# Optional: create venv and install deps
#   python -m venv venv && source venv/bin/activate   # macOS/Linux
#   pip install -r requirements.txt
# Full predict path (in-process Re-ID + crop): pip install -r requirements-e2e.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API: http://localhost:8000  
Docs: http://localhost:8000/docs

## Run frontend (Vite)

```bash
cd rhino_app/frontend
npm install   # first time only
npm run dev
```

App: http://localhost:5173

## One-time DB setup

```bash
cd rhino_app/backend
# Set .env (see .env.example), then:
python init_db.py
```

## Quick start with Docker

Run all services (PostgreSQL + backend + frontend):

```bash
cd rhino_app
docker compose up --build
```

- If you have IndivAID data mounted (default `../IndivAID`), the backend container runs `python init_db.py` on startup and will
  prefer importing `IndivAID/Rhino_photos/high_quality_cropped` + `high_quality_cropped_parts` (and `descriptions_four_parts.json`
  if present). It falls back to `IndivAID/Rhino_photos/high_quality` when cropped data is missing.
- To skip IndivAID import on startup:

```bash
cd rhino_app
NO_HIGH_QUALITY=1 docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Backend docs: http://localhost:8000/docs

Stop:

```bash
docker compose down
```

Remove DB volume too (full reset):

```bash
docker compose down -v
```

## Import IndivAID split + `descriptions_four_parts.json` (recommended)

```bash
cd rhino_app/backend
python migrate_split_four_parts.py \
  --split-root ../../IndivAID/data/rhino_split \
  --descriptions ../../IndivAID/.../descriptions_four_parts.json
```

Optional ATRW folder import: [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md).
