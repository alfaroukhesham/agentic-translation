"""Worker subprocess scheduling (avoids circular imports)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from app import db
from app.config import get_settings
from app.webhook import send_webhook

_worker_proc: subprocess.Popen | None = None
_active_job_id: str | None = None


def get_worker_state() -> tuple[subprocess.Popen | None, str | None]:
    return _worker_proc, _active_job_id


def _spawn_worker(fastapi_job_id: str) -> subprocess.Popen:
    env = os.environ.copy()
    settings = get_settings()
    env["DATA_DIR"] = str(settings.data_dir)
    cmd = [sys.executable, "-m", "app.worker", f"--fastapi-job-id={fastapi_job_id}"]
    proc = subprocess.Popen(cmd, env=env)
    db.set_status(fastapi_job_id, "processing", worker_pid=proc.pid)
    db.append_event(fastapi_job_id, "info", "worker.spawned", f"pid={proc.pid}")
    return proc


async def _handle_worker_exit(fastapi_job_id: str, returncode: int) -> None:
    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if not job:
        return
    if job["status"] == "processing" and returncode != 0:
        db.set_status(fastapi_job_id, "failed", last_error=f"worker exit code {returncode}")
    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if job and job["status"] == "completed":
        await send_webhook(job)
    await schedule_worker_if_idle()


async def schedule_worker_if_idle() -> None:
    global _worker_proc, _active_job_id
    if _worker_proc is not None and _worker_proc.poll() is None:
        return
    nxt = db.dequeue_next()
    if not nxt:
        _active_job_id = None
        return
    _active_job_id = nxt["fastapi_job_id"]
    _worker_proc = _spawn_worker(_active_job_id)


async def poll_worker_loop() -> None:
    global _worker_proc, _active_job_id
    while True:
        await asyncio.sleep(2)
        if _worker_proc is None:
            continue
        rc = _worker_proc.poll()
        if rc is None:
            continue
        fid = _active_job_id
        _worker_proc = None
        if fid:
            await _handle_worker_exit(fid, rc)


async def start_runner() -> asyncio.Task:
    db.recover_orphaned_processing()
    await schedule_worker_if_idle()
    return asyncio.create_task(poll_worker_loop())
