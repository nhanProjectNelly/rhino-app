# Production deployment checklist — Rhino Re-ID

Use this before exposing the app to a network beyond local development.

## Secrets and defaults

- [ ] Set a strong random **`SECRET_KEY`** in `backend/.env` (JWT signing). Do not use the default from `config.py`.
- [ ] Change the default **`admin`** user password (created by `init_db.py`) or create a new admin and deactivate the default.
- [ ] Keep **`.env` out of version control**; rotate keys if they were ever committed.
- [ ] **`OPENAI_API_KEY`**: restrict by IP or usage caps on the provider side for production keys.

## Database

- [ ] Use **PostgreSQL** (or your org standard) with backups and restore tested.
- [ ] **`DATABASE_URL`** uses TLS if the DB is remote (`sslmode` for PostgreSQL).

## HTTP and CORS

- [ ] **`main.py` CORS** currently allows Vite dev origins only — update **`allow_origins`** for your real frontend origin(s).
- [ ] Serve the API and SPA over **HTTPS** behind a reverse proxy (nginx, Caddy, cloud LB).

## File storage

- [ ] **`UPLOAD_DIR`** (and IndivAID gallery paths) live on durable storage with **backup** and disk monitoring.
- [ ] Set OS file permissions so only the app user can read/write uploads.

## Rate limiting and auth

- [ ] Confirm **predict rate limits** (`auth.py`) meet your abuse model; note in-memory limits do not span multiple API processes — use Redis or similar if you scale horizontally.

## Monitoring

- [ ] Log aggregation and alerts for **5xx** and Re-ID failures.
- [ ] Optional: health check endpoint for orchestrators (extend beyond `GET /` if needed).

## Legal and data

- [ ] Image data may be sensitive — align retention and access with your organization’s policy (see also `DOCUMENTATION.md` security notes).
