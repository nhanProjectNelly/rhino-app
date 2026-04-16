# Deploy: code from Git + data from local

Code is installed with **git clone / git pull**. The following **are not in Git** and must be copied or recreated on the server so the app can run predict, describe, and init the DB consistently with your machine.

---

## 1. Required: environment file

| Item | Purpose |
|------|---------|
| `backend/.env` | Copy from local **or** create from `backend/.env.example` on the server. |

Must set at minimum:

- `SECRET_KEY` (strong random in production)
- `DATABASE_URL` (PostgreSQL URL on the server, or SQLite path if you accept file DB)
- `OPENAI_API_KEY` if you use LLM describe endpoints

---

## 2. Required for Re-ID / IndivAID predict

| Item | Purpose |
|------|---------|
| **IndivAID repo** | Directory referenced by `INDIVAID_ROOT` (clone or rsync from local). |
| **Model weights** | Path in `MODEL_WEIGHT` (file or directory with `.pth` / `.pt`). |
| **Re-ID config** | `INDIVAID_REID_CONFIG` (YAML under IndivAID), e.g. `configs/Rhino/...`. |

Optional but recommended for parity with training:

- `INDIVAID_REID_TEXT_DESC_PATH` (four-part text JSON under IndivAID)

---

## 3. Optional: gallery / uploads / test data

| Item | Purpose |
|------|---------|
| `uploads/` | User uploads and Re-ID folders (`reid_atrw`, `predict`, etc.). Omit for a **clean** server; run sync scripts instead (below). |
| Local **SQLite** `backend/rhino.db` | Do **not** copy if the server uses **PostgreSQL**. Prefer `init_db.py` on the server and re-import data. |

To mirror ATRW + DB content like local dev, use scripts from `backend/` (see **DOCUMENTATION.md**):

- `sync_reid_test_data.py` (ATRW paths + descriptions JSON)
- Other migrations as documented for your dataset

---

## 4. One-shot rsync from local machine (example)

Run **on your laptop**, adjusting paths and host:

```bash
# Environment (never commit .env to Git)
scp backend/.env nguyenthanh@rhino-gpu1:~/rhino-app-env/backend.env

# IndivAID tree (large)
rsync -avz --progress /path/to/IndivAID/ nguyenthanh@rhino-gpu1:~/IndivAID/

# Checkpoints (if not inside repo)
rsync -avz --progress /path/to/production_checkpoint/ nguyenthanh@rhino-gpu1:~/production_checkpoint/

# Optional: uploads mirror
rsync -avz --progress ./uploads/ nguyenthanh@rhino-gpu1:~/rhino-uploads/
```

On the server, move files into place (e.g. `/opt/rhino-app/`, `/opt/IndivAID/`) and fix `INDIVAID_ROOT` / `MODEL_WEIGHT` in `.env`.

---

## 5. Database init on the server

From `backend/` with venv activated and `PYTHONPATH` set to the **repository root** (for `ai_core`):

```bash
export PYTHONPATH=/opt/rhino-app   # example; adjust to your clone path
cd /opt/rhino-app/backend
source .venv/bin/activate
pip install -r requirements.txt
# place backend/.env here (or symlink)

python init_db.py --no-high-quality
```

Use `--reset` only if you accept **wiping** the database.

Then run optional data sync scripts (ATRW, etc.) as in **DOCUMENTATION.md**.

---

## 6. Verify

- `GET /docs` — API up
- Login — user created by `init_db.py` (change default password)
- Run one predict after gallery + weights are configured

See also: **[SERVER_INSTALL.md](SERVER_INSTALL.md)**, **[PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)**.
