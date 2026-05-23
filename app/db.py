"""SQLite persistence for translation jobs."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DuplicateJobError(Exception):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "jobs.db"
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              fastapi_job_id TEXT PRIMARY KEY,
              wp_job_id TEXT NOT NULL,
              en_post_id INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued',
              target_langs TEXT NOT NULL,
              s3_export_key TEXT,
              s3_result_key TEXT NOT NULL,
              callback_url TEXT NOT NULL,
              callback_secret TEXT NOT NULL,
              source_mode TEXT NOT NULL,
              stats_json TEXT,
              last_error TEXT,
              worker_pid INTEGER,
              created_at TEXT NOT NULL,
              started_at TEXT,
              completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_wp_job_id ON jobs(wp_job_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE TABLE IF NOT EXISTS job_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              fastapi_job_id TEXT NOT NULL,
              level TEXT NOT NULL,
              event TEXT NOT NULL,
              message TEXT,
              meta_json TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (fastapi_job_id) REFERENCES jobs(fastapi_job_id)
            );
            CREATE TABLE IF NOT EXISTS task_failures (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              fastapi_job_id TEXT NOT NULL,
              original_post_id INTEGER,
              lang TEXT,
              error TEXT,
              attempts INTEGER,
              FOREIGN KEY (fastapi_job_id) REFERENCES jobs(fastapi_job_id)
            );
            """
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def get_active_job_by_wp_job_id(wp_job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE wp_job_id = ? AND status IN ('queued', 'processing')
            ORDER BY created_at DESC LIMIT 1
            """,
            (str(wp_job_id),),
        ).fetchone()
    return _row_to_dict(row)


def create_job(
    *,
    wp_job_id: str,
    en_post_id: int,
    target_langs: list[str],
    callback_url: str,
    callback_secret: str,
    s3_result_key: str,
    source_mode: str,
    s3_export_key: str | None = None,
) -> str:
    existing = get_active_job_by_wp_job_id(wp_job_id)
    if existing:
        return existing["fastapi_job_id"]

    fastapi_job_id = str(uuid.uuid4())
    now = _utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              fastapi_job_id, wp_job_id, en_post_id, status, target_langs,
              s3_export_key, s3_result_key, callback_url, callback_secret,
              source_mode, created_at
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fastapi_job_id,
                str(wp_job_id),
                en_post_id,
                json.dumps(target_langs),
                s3_export_key,
                s3_result_key,
                callback_url,
                callback_secret,
                source_mode,
                now,
            ),
        )
        conn.commit()
    append_event(fastapi_job_id, "info", "job.created", f"Job queued for wp_job_id={wp_job_id}")
    return fastapi_job_id


def get_job_by_fastapi_id(fastapi_job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE fastapi_job_id = ?",
            (fastapi_job_id,),
        ).fetchone()
    return _row_to_dict(row)


def get_job_by_wp_job_id(wp_job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE wp_job_id = ? ORDER BY created_at DESC LIMIT 1",
            (str(wp_job_id),),
        ).fetchone()
    return _row_to_dict(row)


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_by_status(status: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status = ?",
            (status,),
        ).fetchone()
    return int(row["c"]) if row else 0


def queue_position(fastapi_job_id: str) -> int:
    job = get_job_by_fastapi_id(fastapi_job_id)
    if not job or job["status"] != "queued":
        return 0
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM jobs
            WHERE status = 'queued' AND created_at <= ?
            """,
            (job["created_at"],),
        ).fetchone()
    return int(row["c"]) if row else 0


def has_processing_job() -> bool:
    return count_by_status("processing") > 0


def dequeue_next() -> dict[str, Any] | None:
    if has_processing_job():
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM jobs WHERE status = 'queued'
            ORDER BY created_at ASC LIMIT 1
            """
        ).fetchone()
    return _row_to_dict(row)


def set_status(
    fastapi_job_id: str,
    status: str,
    *,
    last_error: str | None = None,
    stats: dict | None = None,
    worker_pid: int | None = None,
) -> None:
    now = _utc_now()
    fields = ["status = ?"]
    params: list[Any] = [status]

    if status == "processing":
        fields.append("started_at = COALESCE(started_at, ?)")
        params.append(now)
    if status in ("completed", "failed"):
        fields.append("completed_at = ?")
        params.append(now)
    if last_error is not None:
        fields.append("last_error = ?")
        params.append(last_error)
    if stats is not None:
        fields.append("stats_json = ?")
        params.append(json.dumps(stats))
    if worker_pid is not None:
        fields.append("worker_pid = ?")
        params.append(worker_pid)

    params.append(fastapi_job_id)
    sql = f"UPDATE jobs SET {', '.join(fields)} WHERE fastapi_job_id = ?"
    with connect() as conn:
        conn.execute(sql, params)
        conn.commit()


def append_event(
    fastapi_job_id: str,
    level: str,
    event: str,
    message: str = "",
    meta: dict | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO job_events (fastapi_job_id, level, event, message, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fastapi_job_id,
                level,
                event,
                message,
                json.dumps(meta) if meta else None,
                _utc_now(),
            ),
        )
        conn.commit()


def record_task_failure(
    fastapi_job_id: str,
    original_post_id: int | None,
    lang: str,
    error: str,
    attempts: int,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO task_failures (fastapi_job_id, original_post_id, lang, error, attempts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fastapi_job_id, original_post_id, lang, error, attempts),
        )
        conn.commit()


def get_events(fastapi_job_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM job_events WHERE fastapi_job_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (fastapi_job_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_task_failures(fastapi_job_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_failures WHERE fastapi_job_id = ? ORDER BY id DESC",
            (fastapi_job_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def recover_orphaned_processing() -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE jobs SET status = 'failed',
              last_error = 'worker interrupted on dispatcher restart',
              completed_at = ?
            WHERE status = 'processing'
            """,
            (_utc_now(),),
        )
        conn.commit()
        return cur.rowcount
