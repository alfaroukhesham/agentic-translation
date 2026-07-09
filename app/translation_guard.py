"""Ensure result JSON never advertises empty translations for requested languages."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.job_types import DEFAULT_JOB_TYPE, JobType

_URL_RE = re.compile(r"^https?://", re.I)


class IncompleteTranslationsError(Exception):
    """Raised when one or more target_langs are missing or empty after translation."""

    def __init__(self, details: list[dict[str, Any]]):
        self.details = details
        parts = []
        for row in details:
            pid = row.get("original_post_id", "?")
            missing = row.get("missing") or []
            parts.append(f"post {pid}: {', '.join(missing)}")
        super().__init__(
            "Incomplete translations for requested languages: " + "; ".join(parts)
        )


def _block_echoes_english(english: dict, block: dict) -> bool:
    en_t = (english.get("title") or "").strip()
    en_c = english.get("content") or ""
    t = (block.get("title") or "").strip()
    c = block.get("content") or ""
    if en_t and t == en_t:
        return True
    if en_c and c == en_c:
        return True
    return False


def _title_echoes_english(english: dict, block: dict) -> bool:
    en_t = (english.get("title") or "").strip()
    t = (block.get("title") or "").strip()
    return bool(en_t and t == en_t)


def _is_preserve_acf_value(key: str, value: str) -> bool:
    if not isinstance(value, str):
        return True
    if key.endswith("_attachment_id") or key in ("logo", "icon", "thumbnail_id"):
        return True
    if value.isdigit():
        return True
    if _URL_RE.match(value.strip()):
        return True
    try:
        parsed = urlparse(value.strip())
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return True
    except Exception:
        pass
    return False


def _iter_acf_string_paths(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(val, str):
                if not _is_preserve_acf_value(str(key), val) and val.strip():
                    paths.append((path, val))
            else:
                paths.extend(_iter_acf_string_paths(val, path))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            path = f"{prefix}[{i}]"
            if isinstance(val, str):
                if val.strip() and not _URL_RE.match(val.strip()):
                    paths.append((path, val))
            else:
                paths.extend(_iter_acf_string_paths(val, path))
    return paths


def _acf_value_at_path(obj: Any, path: str) -> str | None:
    if not path:
        return None
    cur: Any = obj
    for token in re.split(r"\.|\[|\]", path):
        if not token:
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(token)]
            except (IndexError, ValueError):
                return None
        elif isinstance(cur, dict):
            if token not in cur:
                return None
            cur = cur[token]
        else:
            return None
    return cur if isinstance(cur, str) else None


def translation_block_filled(
    item: dict,
    lang: str,
    *,
    job_type: JobType | str = DEFAULT_JOB_TYPE,
) -> bool:
    tr = item.get("translations") or {}
    if not isinstance(tr, dict):
        return False
    block = tr.get(lang)
    if not isinstance(block, dict):
        return False
    english = item.get("english") or {}
    if not isinstance(english, dict):
        return False

    jt = job_type if job_type in ("blog", "news", "page_acf") else DEFAULT_JOB_TYPE

    if jt == "news":
        t = block.get("title")
        if not (isinstance(t, str) and t.strip()):
            return False
        return not _title_echoes_english(english, block)

    if jt == "page_acf":
        en_acf = english.get("acf_fields")
        tr_acf = block.get("acf_fields")
        if not isinstance(en_acf, dict) or not isinstance(tr_acf, dict):
            return False
        for path, en_val in _iter_acf_string_paths(en_acf):
            tr_val = _acf_value_at_path(tr_acf, path)
            if not isinstance(tr_val, str) or not tr_val.strip():
                return False
            if tr_val.strip() == en_val.strip():
                return False
        return bool(_iter_acf_string_paths(en_acf))

    t, c = block.get("title"), block.get("content")
    if not (isinstance(t, str) and isinstance(c, str) and t.strip() and c.strip()):
        return False
    return not _block_echoes_english(english, block)


def missing_languages_for_item(
    item: dict,
    target_langs: list[str],
    *,
    job_type: JobType | str = DEFAULT_JOB_TYPE,
) -> list[str]:
    english = item.get("english")
    if not isinstance(english, dict):
        return list(target_langs)
    return [
        lang
        for lang in target_langs
        if not translation_block_filled(item, lang, job_type=job_type)
    ]


def prune_item_translations(
    item: dict,
    target_langs: list[str],
    *,
    job_type: JobType | str = DEFAULT_JOB_TYPE,
) -> None:
    """
    Drop empty/partial blocks. For requested langs, keep only filled entries.
    Remove blank translation keys so consumers never see empty language slots.
    """
    tr = item.get("translations")
    if not isinstance(tr, dict):
        item["translations"] = {}
        return

    requested = set(target_langs)
    cleaned: dict[str, Any] = {}

    for lang, block in tr.items():
        if not isinstance(block, dict):
            continue
        if lang in requested:
            if translation_block_filled(item, lang, job_type=job_type):
                cleaned[lang] = block
        elif job_type == "news":
            t = block.get("title")
            if isinstance(t, str) and t.strip():
                cleaned[lang] = block
        elif job_type == "page_acf":
            if block.get("acf_fields"):
                cleaned[lang] = block
        else:
            t, c = block.get("title"), block.get("content")
            if isinstance(t, str) and t.strip() and isinstance(c, str) and c.strip():
                cleaned[lang] = block

    item["translations"] = cleaned


def finalize_export_translations(
    export_doc: dict,
    target_langs: list[str],
    *,
    job_type: JobType | str = DEFAULT_JOB_TYPE,
) -> list[dict[str, Any]]:
    """
    Prune empty translation entries and return per-item missing language details.
    Mutates export_doc items in place (sets missing_languages, prunes translations).
    """
    items = export_doc.get("items") or []
    details: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        prune_item_translations(item, target_langs, job_type=job_type)
        missing = missing_languages_for_item(item, target_langs, job_type=job_type)
        # Completed results must not advertise missing_languages: [] — WordPress news
        # import treats an empty array as "nothing to import" and skips all langs.
        if missing:
            item["missing_languages"] = missing
        else:
            item.pop("missing_languages", None)
        if missing:
            details.append(
                {
                    "original_post_id": item.get("original_post_id"),
                    "missing": missing,
                }
            )

    return details


def assert_all_target_langs_filled(
    export_doc: dict,
    target_langs: list[str],
    *,
    job_type: JobType | str = DEFAULT_JOB_TYPE,
) -> None:
    """Prune empties and fail if any requested language is still missing."""
    details = finalize_export_translations(export_doc, target_langs, job_type=job_type)
    if details:
        raise IncompleteTranslationsError(details)
