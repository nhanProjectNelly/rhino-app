# Rhino App – localhost (PostgreSQL)

## 1. Create PostgreSQL database

```bash
# Create database (uses current OS user by default; or specify user with -U)
createdb rhino_app

# Or with explicit user (e.g. postgres):
# createdb -U postgres rhino_app
```

## 2. Backend (BE)

```bash
cd rhino_app/backend

# Create .env from example and set DATABASE_URL for Postgres, e.g.:
# DATABASE_URL=postgresql+asyncpg://USER@localhost:5432/rhino_app
# If no password (peer/trust auth): postgresql+asyncpg://postgres@localhost:5432/rhino_app

# Install deps (includes asyncpg for Postgres)
pip install -r requirements.txt

# Init DB and default admin user (admin / admin)
python init_db.py

# Run backend at http://localhost:8000
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 3. Frontend (FE)

```bash
cd rhino_app/frontend

# Install deps
npm install

# Run dev server (proxies /api and /uploads to backend)
npm run dev
```

Open **http://localhost:5173** (Vite default). The app will call the backend at `http://127.0.0.1:8000` via the proxy.

---

**Summary**

| Service   | URL                  | Command / note                          |
|----------|----------------------|-----------------------------------------|
| Postgres | localhost:5432       | `createdb rhino_app`                    |
| Backend  | http://localhost:8000 | `uvicorn app.main:app --reload --port 8000` |
| Frontend | http://localhost:5173 | `npm run dev` (from frontend dir)       |

Login: **admin** / **admin**
