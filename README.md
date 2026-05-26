# Translation Sidecar Service

FastAPI service for WordPress blog translation: `/v1` API, MinIO storage, SQLite queue, on-demand worker.

## Stack

- **dispatcher** — FastAPI + SQLite (`/data/jobs.db` on a volume). No separate DB container.
- **MinIO** — runs separately under `../storage` (not bundled by default).
- **worker** — subprocess spawned per job (`python -m app.worker`).

## Quick start

```bash
cp .env.example .env
# Set GEMINI_API_KEY, API_SECRET, ADMIN_PASSWORD, and MinIO credentials (match ../storage/.env)

# Start MinIO (once)
cd ../storage && docker compose up -d

# Start translation sidecar
cd ../translation-sidecar-service
docker compose up -d --build

curl http://127.0.0.1:8080/health
```

Ensure bucket `visatop-translations` exists (MinIO console on :9001 or your bootstrap script).

Admin UI: http://127.0.0.1:8080/ui/ (session login: `ADMIN_USER` / `ADMIN_PASSWORD`).

Public API (WordPress): `http://<host>:8080/v1/...` — same secret as `BLOG_TRANSLATION_WEBHOOK_SECRET`:

```http
X-Translation-Secret: <API_SECRET>
Content-Type: application/json
```

(`API_SECRET` in `.env` must equal WordPress `BLOG_TRANSLATION_WEBHOOK_SECRET`.)

`/health`, `/docs`, and `/redoc` stay unauthenticated. Lock down port 8080 at the firewall to WordPress egress IPs when possible.

## MinIO endpoints

| Variable | Purpose |
|----------|---------|
| `STORAGE_ENDPOINT` | Set in compose to `http://host.docker.internal:9000` (host MinIO from `../storage`) |
| `STORAGE_PUBLIC_ENDPOINT` | Host in presigned URLs — must be reachable from WordPress (e.g. `http://138.68.184.84:9000`) |

## API (WordPress)

- `POST /v1/jobs/{wp_job_id}/export-upload` — presigned PUT for export JSON
- `POST /v1/translate` — start job (inline or `source.s3`)
- `GET /v1/jobs/{fastapi_job_id}` — status fallback
- `POST /v1/jobs/{wp_job_id}/result-download` — presigned GET for result

See `docs/superpowers/specs/2026-05-12-translation-service-design.md` and `wp-spec.md`.

## Local tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

## Production notes

- Optional: nginx in front with TLS + IP allowlist; `/v1` still needs `API_SECRET` even behind nginx.
- UI uses session login (`ADMIN_USER` / `ADMIN_PASSWORD`); `/v1` uses `API_SECRET` (not the admin password).
- Backup `translation-data` volume (`jobs.db`) and MinIO data in `../storage`.

### Optional bundled MinIO (local dev only)

If you do not use `../storage`, enable the profile (port 9000 must be free):

```bash
docker compose --profile bundled-minio up -d --build
```
