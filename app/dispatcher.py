"""FastAPI application entry."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import bcrypt
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app import db
from app.config import get_settings
from app.routes import ui, v1
from app.runner import get_worker_state, start_runner

load_dotenv()

_poll_task = None
_started_at = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poll_task
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_schema()
    _poll_task = await start_runner()
    yield
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="VisaTop Translation Sidecar", lifespan=lifespan)
settings = get_settings()
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.include_router(v1.router)
app.include_router(ui.router)


@app.get("/health")
def health() -> dict:
    worker_proc, active_job_id = get_worker_state()
    worker_active = worker_proc is not None and worker_proc.poll() is None
    jobs = db.list_jobs(limit=1)
    last_job_at = jobs[0]["created_at"] if jobs else None
    return {
        "status": "ok",
        "worker_active": worker_active,
        "queue_depth": db.count_by_status("queued"),
        "running_job_id": active_job_id,
        "last_job_at": last_job_at,
        "dispatcher_uptime_seconds": int(
            (datetime.now(timezone.utc) - _started_at).total_seconds()
        ),
    }


def verify_admin_password(password: str) -> bool:
    settings = get_settings()
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            settings.admin_password.encode("utf-8"),
        )
    except ValueError:
        return password == settings.admin_password
