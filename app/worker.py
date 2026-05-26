"""One-shot worker: translate a single queued job."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app import db
from app.blog_export import run_blog_export
from app.translation_guard import IncompleteTranslationsError
from app.config import get_settings
from app.storage import get_storage
from app.storage.base import StorageNotFoundError


def _job_dir(fastapi_job_id: str) -> Path:
    return get_settings().data_dir / "jobs" / fastapi_job_id


def _load_input(job: dict) -> dict:
    job_dir = _job_dir(job["fastapi_job_id"])
    inline_path = job_dir / "input.json"
    if inline_path.exists():
        return json.loads(inline_path.read_text(encoding="utf-8"))
    if job.get("s3_export_key"):
        raw = get_storage().get(job["s3_export_key"])
        return json.loads(raw.decode("utf-8"))
    raise FileNotFoundError("No input.json and no s3_export_key")


async def run_job(fastapi_job_id: str) -> int:
    db.init_schema()
    job = db.get_job_by_fastapi_id(fastapi_job_id)
    if not job:
        print(f"Job not found: {fastapi_job_id}", file=sys.stderr)
        return 1

    db.set_status(fastapi_job_id, "processing")
    db.append_event(fastapi_job_id, "info", "worker.started", "Worker subprocess started")

    try:
        export_doc = _load_input(job)
        target_langs = json.loads(job["target_langs"])

        def on_event(level: str, event: str, meta: dict) -> None:
            db.append_event(fastapi_job_id, level, event, json.dumps(meta))

        def on_failure(post_id, lang, error, attempts) -> None:
            db.record_task_failure(fastapi_job_id, post_id, lang, error, attempts)

        filled, stats = await run_blog_export(
            export_doc=export_doc,
            target_langs=target_langs,
            on_event=on_event,
            on_task_failure=on_failure,
        )

        # run_blog_export raises IncompleteTranslationsError if any target_lang is empty.

        job_dir = _job_dir(fastapi_job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        out_path = job_dir / "output.json"
        out_bytes = json.dumps(filled, ensure_ascii=False, indent=2).encode("utf-8")
        out_path.write_bytes(out_bytes)

        get_storage().put(job["s3_result_key"], out_bytes)
        db.append_event(fastapi_job_id, "info", "s3.uploaded", job["s3_result_key"])

        db.set_status(fastapi_job_id, "completed", stats=stats)
        db.append_event(fastapi_job_id, "info", "worker.completed", json.dumps(stats))
        return 0
    except IncompleteTranslationsError as exc:
        db.set_status(fastapi_job_id, "failed", last_error=str(exc))
        db.append_event(fastapi_job_id, "error", "worker.incomplete_translations", str(exc))
        return 1
    except StorageNotFoundError as exc:
        db.set_status(fastapi_job_id, "failed", last_error=str(exc))
        db.append_event(fastapi_job_id, "error", "worker.failed", str(exc))
        return 1
    except Exception as exc:
        db.set_status(fastapi_job_id, "failed", last_error=str(exc))
        db.append_event(fastapi_job_id, "error", "worker.failed", str(exc))
        return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fastapi-job-id", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_job(args.fastapi_job_id)))


if __name__ == "__main__":
    main()
