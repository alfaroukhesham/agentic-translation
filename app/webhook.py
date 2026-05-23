"""Outbound completion webhooks to WordPress."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app import db


async def send_webhook(job: dict[str, Any]) -> bool:
    payload = {
        "wp_job_id": job["wp_job_id"],
        "fastapi_job_id": job["fastapi_job_id"],
        "status": "completed" if job["status"] == "completed" else "failed",
    }
    if job["status"] == "completed":
        payload["s3_result_key"] = job["s3_result_key"]
    else:
        payload["error"] = job.get("last_error") or "translation failed"
        payload["s3_result_key"] = None

    secret = job["callback_secret"]
    url = job["callback_url"]
    body = json.dumps(payload, ensure_ascii=False)
    headers = {
        "Content-Type": "application/json",
        "X-Translation-Secret": secret,
    }

    last_err = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                resp.raise_for_status()
            db.append_event(job["fastapi_job_id"], "info", "webhook.sent", url)
            return True
        except Exception as exc:
            last_err = str(exc)
            db.append_event(
                job["fastapi_job_id"],
                "warn",
                "webhook.retry",
                f"attempt {attempt}: {last_err[:200]}",
            )
            if attempt < 3:
                await asyncio.sleep(2**attempt)
    db.append_event(job["fastapi_job_id"], "error", "webhook.failed", last_err or "")
    return False
