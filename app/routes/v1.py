"""WordPress-facing /v1 API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import db
from app.config import get_settings
from app.models import (
    ExportUploadResponse,
    JobStatusResponse,
    ResultDownloadResponse,
    TranslateRequest,
    TranslateResponse202,
    validate_inline_export,
)
from app.storage import get_storage
from app.storage.base import StorageNotFoundError
from app.storage.keys import export_key, result_key

router = APIRouter(prefix="/v1", tags=["v1"])


@router.post("/jobs/{wp_job_id}/export-upload", response_model=ExportUploadResponse)
def post_export_upload(wp_job_id: str) -> ExportUploadResponse:
    key = export_key(wp_job_id)
    presigned = get_storage().presign_put(key)
    return ExportUploadResponse(
        upload_url=presigned["upload_url"],
        export_key=presigned["export_key"],
        expires_in=presigned["expires_in"],
    )


@router.post("/translate", status_code=202, response_model=TranslateResponse202)
async def post_translate(body: TranslateRequest) -> TranslateResponse202:
    wp_job_id = str(body.wp_job_id)
    rk = result_key(wp_job_id)

    if body.source.inline is not None:
        validate_inline_export(body.source.inline)
        source_mode = "inline"
        s3_export_key = None
    elif body.source.s3 is not None:
        source_mode = "s3"
        s3_export_key = body.source.s3.key
        try:
            get_storage().head(s3_export_key)
        except StorageNotFoundError:
            raise HTTPException(status_code=400, detail=f"S3 object not found: {s3_export_key}")
    else:
        raise HTTPException(status_code=400, detail="source.inline or source.s3 required")

    fastapi_job_id = db.create_job(
        wp_job_id=wp_job_id,
        en_post_id=body.en_post_id,
        target_langs=body.target_langs,
        callback_url=body.callback_url,
        callback_secret=body.callback_secret,
        s3_result_key=rk,
        source_mode=source_mode,
        s3_export_key=s3_export_key,
    )

    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if not job:
        raise HTTPException(status_code=500, detail="job create failed")

    if source_mode == "inline" and body.source.inline is not None:
        job_dir = get_settings().data_dir / "jobs" / fastapi_job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        Path(job_dir / "input.json").write_text(
            json.dumps(body.source.inline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    from app.runner import schedule_worker_if_idle

    await schedule_worker_if_idle()

    position = db.queue_position(fastapi_job_id)
    return TranslateResponse202(
        fastapi_job_id=fastapi_job_id,
        s3_result_key=rk,
        status=job["status"],
        position=position,
    )


@router.get("/jobs/{fastapi_job_id}", response_model=JobStatusResponse)
def get_job_status(fastapi_job_id: str) -> JobStatusResponse:
    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    status_map = {
        "queued": "pending",
        "processing": "processing",
        "completed": "completed",
        "failed": "failed",
    }
    stats = None
    if job.get("stats_json"):
        try:
            stats = json.loads(job["stats_json"])
        except json.JSONDecodeError:
            stats = None

    return JobStatusResponse(
        fastapi_job_id=job["fastapi_job_id"],
        wp_job_id=job["wp_job_id"],
        status=status_map.get(job["status"], "pending"),
        s3_result_key=job["s3_result_key"] if job["status"] == "completed" else None,
        error=job.get("last_error"),
        stats=stats,
    )


@router.post("/jobs/{wp_job_id}/result-download", response_model=ResultDownloadResponse)
def post_result_download(wp_job_id: str) -> ResultDownloadResponse:
    job = db.get_job_by_wp_job_id(wp_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="job not completed")
    presigned = get_storage().presign_get(job["s3_result_key"])
    return ResultDownloadResponse(
        download_url=presigned["download_url"],
        s3_result_key=presigned["s3_result_key"],
        expires_in=presigned["expires_in"],
    )
