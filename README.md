# Translation Sidecar Service

FastAPI service for WordPress blog translation: `/v1` API, MinIO storage, SQLite queue, on-demand worker.

## Stack

- **dispatcher** — FastAPI + SQLite (`/data/jobs.db` on a volume). No separate DB container.
- **MinIO** — S3-compatible object storage (separate container in `docker-compose.yml`).
- **worker** — subprocess spawned per job (`python -m app.worker`).

## Quick start

```bash
cp .env.example .env
# Set GEMINI_API_KEY, ADMIN_PASSWORD, MINIO_ROOT_PASSWORD

docker compose up -d --build
# Create bucket (install mc locally or use MinIO console on :9001)
./scripts/bootstrap-minio.sh

curl http://127.0.0.1:8080/health
```

Admin UI: http://127.0.0.1:8080/ui/ (login from `.env`).

## MinIO endpoints

| Variable | Purpose |
|----------|---------|
| `STORAGE_ENDPOINT` | Internal URL for dispatcher/worker (`http://minio:9000` in compose) |
| `STORAGE_PUBLIC_ENDPOINT` | Host in presigned URLs — must be reachable from WordPress (`http://127.0.0.1:9000` or public hostname) |

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

- Put nginx in front with **IP allowlist** for `/v1/*` (WordPress droplet egress only).
- UI uses session login (`ADMIN_USER` / `ADMIN_PASSWORD`).
- Backup `translation-data` volume (`jobs.db`) and `minio-data`.
