"""News export translation (title only)."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import LANG_NAMES, get_settings
from app.gemini_client import extract_retry_delay, gemini_raw_json_payload
from app.translation_guard import assert_all_target_langs_filled, translation_block_filled

EventCallback = Callable[[str, str, dict], None] | None


def _lang_display_name(code: str) -> str:
    return LANG_NAMES.get(code, f"{code} (language code)")


def _load_prompt_base(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"News prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def _make_system_instruction(base_prompt: str, target_lang: str) -> str:
    lang = _lang_display_name(target_lang)
    rtl = (
        "\n\nArabic (ar): use natural RTL phrasing."
        if target_lang == "ar"
        else ""
    )
    return (
        base_prompt
        + rtl
        + f"\n\n---\nTranslate **one news title** into **{lang}** (`{target_lang}`).\n"
        "INPUT JSON: `{\"title\": \"...\"}`\n"
        'OUTPUT: valid JSON only — `{"title": "..."}` with a non-empty translated title.\n'
    )


def _normalize_title_output(data: dict) -> dict:
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Missing non-empty title in model output")
    return {"title": title.strip()}


async def _translate_title(
    title: str,
    lang: str,
    gemini_model: str,
    system_instruction: str,
) -> dict:
    raw = await gemini_raw_json_payload({"title": title}, system_instruction, gemini_model)
    out = _normalize_title_output(raw)
    if title.strip() and out["title"].strip() == title.strip():
        raise ValueError("Model output still matches English title")
    return out


async def run_news_export(
    *,
    export_doc: dict,
    target_langs: list[str],
    prompt_path: Path | None = None,
    gemini_model: str | None = None,
    max_concurrency: int | None = None,
    on_event: EventCallback = None,
    on_task_failure: Callable[[int | None, str, str, int], None] | None = None,
) -> tuple[dict, dict]:
    settings = get_settings()
    prompt_path = prompt_path or settings.news_prompt_path
    primary_model = gemini_model or settings.gemini_model
    fallback_model = settings.gemini_model_fallback
    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)
    max_concurrency = max_concurrency or settings.max_concurrency
    base_prompt = _load_prompt_base(prompt_path)

    out = copy.deepcopy(export_doc)
    out["job_type"] = "news"
    items = out.get("items") or []
    sem = asyncio.Semaphore(max_concurrency)
    stats = {"tasks_total": 0, "tasks_ok": 0, "tasks_failed": 0}

    async def _translate_with_model(
        title: str,
        lang: str,
        model_name: str,
        si: str,
    ) -> tuple[dict | None, str | None]:
        last_err: str | None = None
        for attempt in range(1, 4):
            async with sem:
                stats["tasks_total"] += 1
                try:
                    return await _translate_title(title, lang, model_name, si), None
                except Exception as exc:
                    last_err = str(exc)
                    if attempt < 3 and ("429" in last_err or "503" in last_err):
                        await asyncio.sleep(
                            extract_retry_delay(last_err) if "429" in last_err else 5
                        )
                        continue
                    return None, last_err
        return None, last_err

    async def _worker(item: dict, lang: str) -> None:
        nonlocal stats
        oid = item.get("original_post_id")
        english = item.get("english") or {}
        if not isinstance(english, dict):
            return
        if translation_block_filled(item, lang, job_type="news"):
            return
        title = english.get("title", "") if isinstance(english.get("title"), str) else ""
        si = _make_system_instruction(base_prompt, lang)
        last_err: str | None = None

        for model_index, model_name in enumerate(models):
            if model_index > 0 and on_event:
                on_event(
                    "info",
                    "task.model_fallback",
                    {
                        "post_id": oid,
                        "lang": lang,
                        "from_model": models[model_index - 1],
                        "to_model": model_name,
                    },
                )
            result, model_err = await _translate_with_model(title, lang, model_name, si)
            if result is not None:
                item.setdefault("translations", {})
                if not isinstance(item["translations"], dict):
                    item["translations"] = {}
                item["translations"][lang] = {"title": result["title"]}
                stats["tasks_ok"] += 1
                if on_event:
                    meta: dict[str, Any] = {"post_id": oid, "lang": lang, "model": model_name}
                    if model_index > 0:
                        meta["used_fallback"] = True
                    on_event("info", "task.ok", meta)
                return
            last_err = model_err or f"{model_name} failed after retries"

        stats["tasks_failed"] += 1
        if on_task_failure:
            on_task_failure(oid, lang, last_err or "unknown", 3)
        if on_event:
            on_event("error", "task.failed", {"post_id": oid, "lang": lang, "error": last_err})

    tasks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for lang in target_langs:
            tasks.append(_worker(item, lang))
    if tasks:
        await asyncio.gather(*tasks)

    assert_all_target_langs_filled(out, target_langs, job_type="news")
    return out, stats
