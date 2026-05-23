#!/usr/bin/env bash
# Create bucket if missing (requires mc installed and MinIO running).
set -euo pipefail
ENDPOINT="${STORAGE_PUBLIC_ENDPOINT:-http://127.0.0.1:9000}"
BUCKET="${STORAGE_BUCKET:-visatop-translations}"
USER="${MINIO_ROOT_USER:-minioadmin}"
PASS="${MINIO_ROOT_PASSWORD:-changeme}"

mc alias set local "$ENDPOINT" "$USER" "$PASS"
mc mb --ignore-existing "local/${BUCKET}"
echo "Bucket ready: ${BUCKET}"
