from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from app.validate_export import validate_export_payload, validate_target_langs


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
    status: str
    position: int


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
    s3_result_key: str | None = None
    error: str | None = None
    stats: dict[str, Any] | None = None


def validate_inline_export(data: dict) -> None:
    errs = validate_export_payload(data)
    if errs:
        raise ValueError("; ".join(errs))
