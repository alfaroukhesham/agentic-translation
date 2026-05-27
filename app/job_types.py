"""WordPress job types and S3 prefix mapping."""

from __future__ import annotations

from typing import Literal

JobType = Literal["blog", "news", "page_acf"]
DEFAULT_JOB_TYPE: JobType = "blog"

_PREFIX_BY_TYPE: dict[JobType, str] = {
    "blog": "blog-translations",
    "news": "news-translations",
    "page_acf": "page-acf-translations",
}


def normalize_job_type(value: str | None) -> JobType:
    if not value:
        return DEFAULT_JOB_TYPE
    v = value.strip().lower()
    if v in _PREFIX_BY_TYPE:
        return v  # type: ignore[return-value]
    raise ValueError(f"unsupported job_type: {value}")


def storage_prefix(job_type: JobType | str) -> str:
    jt = normalize_job_type(job_type if isinstance(job_type, str) else str(job_type))
    return _PREFIX_BY_TYPE[jt]
