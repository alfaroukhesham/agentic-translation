from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from app.job_types import DEFAULT_JOB_TYPE, JobType, normalize_job_type
from app.validate_export import validate_export_payload, validate_target_langs


class JobTypeBody(BaseModel):
    job_type: JobType | None = None

    @field_validator("job_type", mode="before")
    @classmethod
    def normalize(cls, v: str | None) -> JobType | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return normalize_job_type(str(v))


class SourceInline(BaseModel):
    inline: dict[str, Any]


class SourceS3(BaseModel):
    bucket: str | None = None
    key: str


class Source(BaseModel):
    inline: dict[str, Any] | None = None
    s3: SourceS3 | None = None

    @model_validator(mode="after")
    def one_source(self) -> "Source":
        if (self.inline is None) == (self.s3 is None):
            raise ValueError("exactly one of source.inline or source.s3 required")
        return self


class TranslateRequest(BaseModel):
    wp_job_id: str
    en_post_id: int
    callback_url: str
    callback_secret: str
    target_langs: list[str]
    source: Source
    job_type: JobType | None = None

    @field_validator("job_type", mode="before")
    @classmethod
    def normalize_job_type_field(cls, v: str | None) -> JobType | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return normalize_job_type(str(v))

    @field_validator("target_langs")
    @classmethod
    def check_langs(cls, v: list[str]) -> list[str]:
        errs = validate_target_langs(v)
        if errs:
            raise ValueError("; ".join(errs))
        return v


class TranslateResponse202(BaseModel):
    fastapi_job_id: str
    s3_result_key: str
    job_type: JobType = DEFAULT_JOB_TYPE
    status: str = "queued"
    position: int = 0


class ExportUploadResponse(BaseModel):
    upload_url: str
    export_key: str
    expires_in: int


class ResultDownloadResponse(BaseModel):
    download_url: str
    s3_result_key: str
    expires_in: int


class JobStatusResponse(BaseModel):
    fastapi_job_id: str
    wp_job_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    job_type: JobType = DEFAULT_JOB_TYPE
    s3_result_key: str | None = None
    error: str | None = None
    stats: dict[str, Any] | None = None


def resolve_job_type(
    request_job_type: JobType | None,
    inline_export: dict[str, Any] | None,
) -> JobType:
    if request_job_type is not None:
        return request_job_type
    if inline_export and inline_export.get("job_type"):
        return normalize_job_type(str(inline_export["job_type"]))
    return DEFAULT_JOB_TYPE


def validate_inline_export(data: dict, job_type: JobType = DEFAULT_JOB_TYPE) -> None:
    errs = validate_export_payload(data, job_type=job_type)
    if errs:
        raise ValueError("; ".join(errs))
