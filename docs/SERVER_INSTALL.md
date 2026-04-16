# Server installation guide

Step-by-step setup for a **Linux server** (Ubuntu 22.04 LTS–style). Adjust paths and package names for your distro.

Before go-live, complete **[PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)** (secrets, HTTPS, CORS, backups).

What to copy when code already comes from Git: **[DEPLOY_DATA_SYNC.md](DEPLOY_DATA_SYNC.md)**.

---

## 1. What you will run

| Piece | Role |
|-------|------|
| **PostgreSQL** | Production database |
| **FastAPI (Uvicorn)** | API + serves `/uploads` |
| **Static SPA** | Built Vite app (`frontend/dist`), usually behind **nginx** |
| **IndivAID + checkpoint** | On-disk Re-ID gallery and weights (see `docs/DOCUMENTATION.md`) |

---

## 2. Server packages

```bash
sudo apt update
sudo apt install -y git nginx postgresql postgresql-contrib \
  python3.12 python3.12-venv build-essential
```

Install **Node.js 20** (e.g. from [NodeSource](https://github.com/nodesource/distributions) or your standard).

---

## 3. Database

```bash
sudo -u postgres psql -c "CREATE USER rhino WITH PASSWORD 'your-secure-password';"
sudo -u postgres psql -c "CREATE DATABASE rhino_app OWNER rhino;"
```

Use in `backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://rhino:your-secure-password@127.0.0.1:5432/rhino_app
```

---

## 4. Clone and layout

Example: app lives at `/opt/rhino_app` (repository root containing `backend/`, `frontend/`, `ai_core/`).

```bash
sudo mkdir -p /opt/rhino_app
sudo chown "$USER:$USER" /opt/rhino_app
cd /opt/rhino_app
git clone <your-repo-url> .
```

Place **IndivAID** and **model weights** where `INDIVAID_ROOT` and `MODEL_WEIGHT` in `.env` point (often next to the repo; see `backend/.env.example`).

---

## 5. Backend

```bash
cd /opt/rhino_app/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip

# API-only (small image) or full Re-ID + crop:
pip install -r requirements.txt
# pip install -r requirements-e2e.txt   # includes torch/torchvision; use GPU wheels if needed

cp .env.example .env
# Edit .env: SECRET_KEY, DATABASE_URL, OPENAI_API_KEY, INDIVAID_ROOT, MODEL_WEIGHT, etc.

python init_db.py --no-high-quality
```

**`PYTHONPATH`:** In-process Re-ID imports `ai_core` from the **repository root** (`/opt/rhino_app`), not only `backend/`.

```bash
export PYTHONPATH=/opt/rhino_app
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Populate gallery / Re-ID test data if needed (`sync_reid_test_data.py`, etc. — see [DOCUMENTATION.md](DOCUMENTATION.md)).

---

## 6. Frontend build

```bash
cd /opt/rhino_app/frontend
npm ci
npm run build
```

Output: `frontend/dist/`.

Production UX: serve `dist/` with **nginx** on the same host that proxies `/api` and `/uploads` to Uvicorn so the browser keeps calling `/api/...` (see nginx example below).

---

## 7. CORS

`app/main.py` allows dev Vite origins by default. For a dedicated API host, set **`allow_origins`** to your real HTTPS frontend origin(s), or use **one nginx site** for both static + proxy so the browser origin matches and paths stay `/api` and `/uploads`.

---

## 8. systemd (Uvicorn)

Create `/etc/systemd/system/rhino-api.service` (edit paths and user):

```ini
[Unit]
Description=Rhino Re-ID API
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/rhino_app/backend
Environment=PYTHONPATH=/opt/rhino_app
ExecStart=/opt/rhino_app/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rhino-api
sudo systemctl status rhino-api
```

Ensure `www-data` (or your service user) can read `UPLOAD_DIR`, IndivAID paths, and weights.

---

## 9. nginx (HTTPS + SPA + proxy)

Example server block (TLS certificates: use certbot or your CA):

```nginx
server {
    listen 443 ssl http2;
    server_name rhino.example.com;

    ssl_certificate     /etc/ssl/certs/your.crt;
    ssl_certificate_key /etc/ssl/private/your.key;

    root /opt/rhino_app/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /uploads/ {
        proxy_pass http://127.0.0.1:8000/uploads/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Reload nginx after testing config: `sudo nginx -t && sudo systemctl reload nginx`.

---

## 10. Docker (alternative)

See root [README.md](../README.md) **Quick start with Docker**. For full Re-ID inside containers you need a heavier image (torch + IndivAID mounts); the shipped `docker-compose.yml` is oriented toward a quicker stack — extend it for production ML if required.

---

## 11. After install

- Open `https://your-domain/` and log in.
- API docs: `https://your-domain/api/docs` if proxied as above (or `/docs` on port 8000 directly).
- Run through **[PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)**.
