"""WordPress-facing /v1 API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.auth import verify_api_secret
from app.config import get_settings
from app.job_types import DEFAULT_JOB_TYPE, storage_prefix
from app.models import (
    ExportUploadResponse,
    JobStatusResponse,
    JobTypeBody,
    ResultDownloadResponse,
    TranslateRequest,
    TranslateResponse202,
    resolve_job_type,
    validate_inline_export,
)
from app.storage import get_storage
from app.storage.base import StorageNotFoundError
from app.storage.keys import export_key, result_key

router = APIRouter(
    prefix="/v1",
    tags=["v1"],
    dependencies=[Depends(verify_api_secret)],
)


def _job_type_from_request_body(body: JobTypeBody | None) -> str:
    if body and body.job_type:
        return body.job_type
    return DEFAULT_JOB_TYPE


@router.post("/jobs/{wp_job_id}/export-upload", response_model=ExportUploadResponse)
def post_export_upload(
    wp_job_id: str,
    body: JobTypeBody | None = None,
) -> ExportUploadResponse:
    jt = _job_type_from_request_body(body)
    key = export_key(wp_job_id, jt)
    presigned = get_storage().presign_put(key)
    return ExportUploadResponse(
        upload_url=presigned["upload_url"],
        export_key=presigned["export_key"],
        expires_in=presigned["expires_in"],
    )


@router.post("/translate", status_code=200, response_model=TranslateResponse202)
async def post_translate(body: TranslateRequest) -> TranslateResponse202:
    wp_job_id = str(body.wp_job_id)
    inline = body.source.inline
    job_type = resolve_job_type(body.job_type, inline)
    rk = result_key(wp_job_id, job_type)

    if inline is not None:
        try:
            validate_inline_export(inline, job_type=job_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source_mode = "inline"
        s3_export_key = None
    elif body.source.s3 is not None:
        source_mode = "s3"
        s3_export_key = body.source.s3.key
        prefix = storage_prefix(job_type)
        if not s3_export_key.startswith(f"{prefix}/"):
            raise HTTPException(
                status_code=400,
                detail=f"S3 key must start with {prefix}/ for job_type={job_type}",
            )
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
        job_type=job_type,
    )

    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if not job:
        raise HTTPException(status_code=500, detail="job create failed")

    if source_mode == "inline" and inline is not None:
        job_dir = get_settings().data_dir / "jobs" / fastapi_job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        Path(job_dir / "input.json").write_text(
            json.dumps(inline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    from app.runner import schedule_worker_if_idle

    await schedule_worker_if_idle()

    position = db.queue_position(fastapi_job_id)
    return TranslateResponse202(
        fastapi_job_id=fastapi_job_id,
        s3_result_key=rk,
        job_type=job_type,
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

    jt = job.get("job_type") or DEFAULT_JOB_TYPE
    return JobStatusResponse(
        fastapi_job_id=job["fastapi_job_id"],
        wp_job_id=job["wp_job_id"],
        status=status_map.get(job["status"], "pending"),
        job_type=jt,
        s3_result_key=job["s3_result_key"] if job["status"] == "completed" else None,
        error=job.get("last_error"),
        stats=stats,
    )


@router.post("/jobs/{wp_job_id}/result-download", response_model=ResultDownloadResponse)
def post_result_download(
    wp_job_id: str,
    body: JobTypeBody | None = None,
) -> ResultDownloadResponse:
    job = db.get_job_by_wp_job_id(wp_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="job not completed")
    jt = job.get("job_type") or _job_type_from_request_body(body)
    result_s3_key = job["s3_result_key"] or result_key(wp_job_id, jt)
    presigned = get_storage().presign_get(result_s3_key)
    return ResultDownloadResponse(
        download_url=presigned["download_url"],
        s3_result_key=presigned["s3_result_key"],
        expires_in=presigned["expires_in"],
    )
