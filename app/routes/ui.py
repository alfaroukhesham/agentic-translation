"""Admin UI (session login)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.dispatcher import verify_admin_password
from app.runner import get_worker_state

router = APIRouter(prefix="/ui", tags=["ui"])


def _templates_dir():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "templates"


templates = Jinja2Templates(directory=str(_templates_dir()))


def _require_login(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse("/ui/login", status_code=303)
    return None


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    from app.config import get_settings

    settings = get_settings()
    if username == settings.admin_user and verify_admin_password(password):
        request.session["authenticated"] = True
        return RedirectResponse("/ui/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Invalid credentials"}, status_code=401
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/ui/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    proc, active_job_id = get_worker_state()
    worker_active = proc is not None and proc.poll() is None
    jobs = db.list_jobs(limit=1)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "worker_active": worker_active,
            "running_job_id": active_job_id,
            "queue_depth": db.count_by_status("queued"),
            "last_job_at": jobs[0]["created_at"] if jobs else "—",
            "processing_count": db.count_by_status("processing"),
        },
    )


@router.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    jobs = db.list_jobs(limit=200)
    for j in jobs:
        j["position"] = db.queue_position(j["fastapi_job_id"]) if j["status"] == "queued" else "—"
    return templates.TemplateResponse(request, "queue.html", {"jobs": jobs})


@router.get("/jobs/{fastapi_job_id}", response_class=HTMLResponse)
def job_detail(request: Request, fastapi_job_id: str):
    redir = _require_login(request)
    if redir:
        return redir
    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)
    events = db.get_events(fastapi_job_id)
    failures = db.get_task_failures(fastapi_job_id)
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {"job": job, "events": events, "failures": failures},
    )


@router.get("/fragments/status", response_class=HTMLResponse)
def fragment_status(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    proc, _ = get_worker_state()
    worker_active = proc is not None and proc.poll() is None
    return HTMLResponse(
        f'<span id="status-pill">Worker: {"active" if worker_active else "idle"} | '
        f"Queue: {db.count_by_status('queued')}</span>"
    )
