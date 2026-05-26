"""Ensure result JSON never advertises empty translations for requested languages."""

from __future__ import annotations

from typing import Any


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


def translation_block_filled(item: dict, lang: str) -> bool:
    """True when lang has non-empty title+content and does not echo English."""
    tr = item.get("translations") or {}
    if not isinstance(tr, dict):
        return False
    block = tr.get(lang)
    if not isinstance(block, dict):
        return False
    t, c = block.get("title"), block.get("content")
    if not (isinstance(t, str) and isinstance(c, str) and t.strip() and c.strip()):
        return False
    english = item.get("english") or {}
    if not isinstance(english, dict):
        return False
    return not _block_echoes_english(english, block)


def missing_languages_for_item(item: dict, target_langs: list[str]) -> list[str]:
    english = item.get("english")
    if not isinstance(english, dict):
        return list(target_langs)
    return [lang for lang in target_langs if not translation_block_filled(item, lang)]


def prune_item_translations(item: dict, target_langs: list[str]) -> None:
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
            if translation_block_filled(item, lang):
                cleaned[lang] = block
        else:
            t, c = block.get("title"), block.get("content")
            if isinstance(t, str) and t.strip() and isinstance(c, str) and c.strip():
                cleaned[lang] = block

    item["translations"] = cleaned


def finalize_export_translations(
    export_doc: dict,
    target_langs: list[str],
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
        prune_item_translations(item, target_langs)
        missing = missing_languages_for_item(item, target_langs)
        item["missing_languages"] = missing
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
) -> None:
    """Prune empties and fail if any requested language is still missing."""
    details = finalize_export_translations(export_doc, target_langs)
    if details:
        raise IncompleteTranslationsError(details)
