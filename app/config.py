"""Environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SUPPORTED_LANGS = frozenset({"ar", "de", "es", "fr", "ha", "hi", "it", "ru", "tl", "tr"})

LANG_NAMES = {
    "ar": "Arabic (ar)",
    "fr": "French (fr)",
    "es": "Spanish (es)",
    "it": "Italian (it)",
    "tr": "Turkish (tr)",
    "de": "German (de)",
    "hi": "Hindi (hi)",
    "tl": "Tagalog (tl)",
    "ru": "Russian (ru)",
    "ha": "Hausa (ha)",
}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    storage_endpoint: str
    storage_public_endpoint: str
    storage_bucket: str
    storage_access_key: str
    storage_secret_key: str
    storage_prefix: str
    storage_region: str
    presign_ttl_seconds: int
    gemini_api_key: str
    gemini_model: str
    gemini_model_fallback: str
    max_concurrency: int
    admin_user: str
    admin_password: str
    api_secret: str
    session_secret: str
    job_retention_days: int
    prompt_path: Path


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    internal = os.environ.get("STORAGE_ENDPOINT", "http://minio:9000").strip()
    public = os.environ.get("STORAGE_PUBLIC_ENDPOINT", "").strip() or internal
    return Settings(
        data_dir=data_dir,
        storage_endpoint=internal,
        storage_public_endpoint=public,
        storage_bucket=os.environ.get("STORAGE_BUCKET", "visatop-translations"),
        storage_access_key=os.environ.get("STORAGE_ACCESS_KEY", ""),
        storage_secret_key=os.environ.get("STORAGE_SECRET_KEY", ""),
        storage_prefix=os.environ.get("STORAGE_PREFIX", "blog-translations"),
        storage_region=os.environ.get("STORAGE_REGION", "us-east-1"),
        presign_ttl_seconds=int(os.environ.get("PRESIGN_TTL_SECONDS", "900")),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        gemini_model_fallback=os.environ.get("GEMINI_MODEL_FALLBACK", "gemini-2.5-flash"),
        max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "6")),
        admin_user=os.environ.get("ADMIN_USER", "admin"),
        admin_password=os.environ.get("ADMIN_PASSWORD", "changeme"),
        api_secret=os.environ.get("API_SECRET", "").strip(),
        session_secret=os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
        job_retention_days=int(os.environ.get("JOB_RETENTION_DAYS", "90")),
        prompt_path=Path(os.environ.get("PROMPT_PATH", "prompt-blogs.md")),
    )
