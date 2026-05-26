"""Blog export translation (from pipeline.py translate-blog-export)."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import LANG_NAMES, get_settings
from app.content_chunks import content_chunk_threshold, split_html_content
from app.translation_guard import (
    _block_echoes_english,
    assert_all_target_langs_filled,
    translation_block_filled,
)

EventCallback = Callable[[str, str, dict], None] | None


def _lang_display_name(code: str) -> str:
    return LANG_NAMES.get(code, f"{code} (language code)")


def _load_prompt_base(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Blog prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def _make_system_instruction(base_prompt: str, target_lang: str) -> str:
    lang = _lang_display_name(target_lang)
    rtl = (
        "\n\nArabic (ar): use natural RTL phrasing; keep numbers/currencies/dates as in source "
        "unless localization clearly requires a format change."
        if target_lang == "ar"
        else ""
    )
    return (
        base_prompt
        + rtl
        + f"\n\n---\nThis API call translates **one post** into **{lang}** (code `{target_lang}`) only.\n"
        "INPUT (JSON user message): a single object with keys "
        "`title`, `content`, `yoast_title`, `yoast_desc`, `acf_fields` (same shape as `english` from the export).\n"
        "OUTPUT: **valid JSON only** (no markdown fences). One object with **exactly** these keys:\n"
        '`"title"`, `"content"`, `"yoast_title"`, `"yoast_desc"`, `"acf_fields"`\n'
        "- `title`, `content`, `yoast_title`, `yoast_desc` are strings.\n"
        "- `acf_fields`: if input is `[]` or empty object, return the same; otherwise mirror keys/structure and "
        "translate string values only.\n"
        "Respect Yoast limits from the prompt: yoast_title ≤ 60 chars, yoast_desc ≤ 160 chars (count characters "
        "in the target language).\n"
    )


def _script_notes(target_lang: str) -> str:
    if target_lang in ("hi", "ha", "tl"):
        return (
            f"\n\nFor {target_lang}: use natural phrasing in the target script; "
            "translate the full body — do not leave content empty or in English.\n"
        )
    return ""


def _chunk_body_instruction() -> str:
    return (
        "\n\n---\nCHUNK MODE: INPUT is JSON with `content_chunk` (one HTML fragment), "
        "`chunk_index` (0-based), and `chunk_total`.\n"
        "OUTPUT: valid JSON with **only** `{\"content\": \"...\"}` — the translated fragment, "
        "preserving all HTML tags and structure.\n"
    )


def _metadata_only_instruction() -> str:
    return (
        "\n\n---\nMETADATA MODE: INPUT includes `title`, `yoast_title`, `yoast_desc`, `acf_fields`; "
        "`content` is empty — do not translate body HTML in this call.\n"
        "OUTPUT: same keys as usual; set `content` to an empty string.\n"
    )


def _truncate_chars(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    return s if len(s) <= max_len else s[:max_len]


def _english_to_payload(english: dict) -> dict:
    acf = english.get("acf_fields")
    if acf is None:
        acf = []
    return {
        "title": english.get("title", "") if isinstance(english.get("title"), str) else "",
        "content": english.get("content", "") if isinstance(english.get("content"), str) else "",
        "yoast_title": english.get("yoast_title", "") if isinstance(english.get("yoast_title"), str) else "",
        "yoast_desc": english.get("yoast_desc", "") if isinstance(english.get("yoast_desc"), str) else "",
        "acf_fields": copy.deepcopy(acf),
    }


def _strip_fences(text: str) -> str:
    if text is None:
        raise ValueError("Model returned null output text")
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()
    return text


def _safe_parse_json_any(text: str | None) -> Any:
    if text is None:
        raise ValueError("Model returned null output text")
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        from json_repair import repair_json

        return json.loads(repair_json(text))


def _extract_retry_delay(error_str: str) -> int:
    match = re.search(r"retryDelay.*?['\"](\d+)s['\"]", error_str)
    return int(match.group(1)) + 3 if match else 60


async def _gemini_raw_json_payload(payload: dict, prompt: str, model_name: str) -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or get_settings().gemini_api_key
    if not api_key:
        raise KeyError("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=model_name,
        contents=json.dumps(payload, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=prompt,
            temperature=0.1,
            max_output_tokens=65536,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw_text = getattr(response, "text", None)
    if not raw_text:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = candidates[0].content.parts
            texts = [getattr(p, "text", None) for p in parts]
            raw_text = "\n".join([t for t in texts if t])
    data = _safe_parse_json_any(raw_text)
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        else:
            raise ValueError(f"Expected JSON object; got list length {len(data)}")
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    return data


def _normalize_key_map(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        if isinstance(k, str):
            out[k.strip().lower().replace(" ", "_")] = v
        else:
            out[k] = v
    return out


def _coerce_translation_dict(data: dict, target_lang: str | None = None) -> dict:
    d = _normalize_key_map(data)
    need = ("title", "content", "yoast_title", "yoast_desc", "acf_fields")

    def _has_all(x: dict) -> bool:
        return all(k in x for k in need)

    if _has_all(d):
        return d
    if target_lang:
        tr = d.get("translations")
        if isinstance(tr, dict) and target_lang in tr and isinstance(tr[target_lang], dict):
            inner = _normalize_key_map(tr[target_lang])
            if "title" in inner and "content" in inner:
                return inner
    for wrap in ("translation", "result", "data", "output", "response", "payload", "article", "post", "body"):
        inner = d.get(wrap)
        if isinstance(inner, dict):
            inner = _normalize_key_map(inner)
            if "title" in inner and "content" in inner:
                return inner if _has_all(inner) else d
    if len(d) == 1:
        sole = next(iter(d.values()))
        if isinstance(sole, dict):
            sole = _normalize_key_map(sole)
            if "title" in sole and "content" in sole:
                return sole
    return d


def _validate_translation(
    data: dict,
    target_lang: str | None = None,
    *,
    require_content: bool = True,
) -> dict:
    data = _coerce_translation_dict(data, target_lang=target_lang)
    for key in ("title", "content", "yoast_title", "yoast_desc"):
        if key not in data:
            raise ValueError(f"Missing key '{key}' in model output")
        if not isinstance(data[key], str):
            raise ValueError(f"Expected '{key}' to be a string")
    if require_content and not data["content"].strip():
        raise ValueError("content must be a non-empty string")
    if "acf_fields" not in data:
        raise ValueError("Missing key 'acf_fields'")
    data["yoast_title"] = _truncate_chars(data["yoast_title"], 60)
    data["yoast_desc"] = _truncate_chars(data["yoast_desc"], 160)
    return data


def _extract_chunk_content(data: dict) -> str:
    content = data.get("content")
    if isinstance(content, str) and content.strip():
        return content
    alt = data.get("content_chunk")
    if isinstance(alt, str) and alt.strip():
        return alt
    raise ValueError("chunk response missing non-empty content")


async def _translate_chunked_payload(
    payload: dict,
    lang: str,
    gemini_model: str,
    system_instruction: str,
) -> dict:
    """Long posts: metadata in one call, HTML body split into sequential chunk calls."""
    chunks = split_html_content(payload.get("content") or "")
    meta_payload = {**payload, "content": ""}
    meta_si = system_instruction + _metadata_only_instruction() + _script_notes(lang)
    meta_raw = await _gemini_raw_json_payload(meta_payload, meta_si, gemini_model)
    meta = _validate_translation(meta_raw, target_lang=lang, require_content=False)

    chunk_si = system_instruction + _chunk_body_instruction() + _script_notes(lang)
    translated_parts: list[str] = []
    total = len(chunks)
    for index, chunk in enumerate(chunks):
        if not chunk.strip():
            translated_parts.append(chunk)
            continue
        chunk_payload = {
            "content_chunk": chunk,
            "chunk_index": index,
            "chunk_total": total,
        }
        raw = await _gemini_raw_json_payload(chunk_payload, chunk_si, gemini_model)
        translated_parts.append(_extract_chunk_content(raw))

    merged = {
        "title": meta["title"],
        "content": "".join(translated_parts),
        "yoast_title": meta["yoast_title"],
        "yoast_desc": meta["yoast_desc"],
        "acf_fields": meta["acf_fields"],
    }
    out = _validate_translation(merged, target_lang=lang, require_content=True)
    if _block_echoes_english(
        {"title": payload.get("title", ""), "content": payload.get("content", "")},
        out,
    ):
        raise ValueError("Model output still matches English source")
    return out


async def _translate_one_lang(
    payload: dict,
    lang: str,
    gemini_model: str,
    system_instruction: str,
) -> dict:
    content = payload.get("content") or ""
    si = system_instruction + _script_notes(lang)
    if len(content) > content_chunk_threshold():
        return await _translate_chunked_payload(payload, lang, gemini_model, si)

    raw = await _gemini_raw_json_payload(payload, si, gemini_model)
    out = _validate_translation(raw, target_lang=lang, require_content=True)
    if _block_echoes_english(
        {"title": payload.get("title", ""), "content": content},
        out,
    ):
        raise ValueError("Model output still matches English source")
    return out


async def run_blog_export(
    *,
    export_doc: dict,
    target_langs: list[str],
    prompt_path: Path | None = None,
    gemini_model: str | None = None,
    max_concurrency: int | None = None,
    on_event: EventCallback = None,
    on_task_failure: Callable[[int | None, str, str, int], None] | None = None,
) -> tuple[dict, dict]:
    """
    Returns (filled_export_doc, stats).
    stats: tasks_total, tasks_ok, tasks_failed
    """
    settings = get_settings()
    prompt_path = prompt_path or settings.prompt_path
    primary_model = gemini_model or settings.gemini_model
    fallback_model = settings.gemini_model_fallback
    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)
    max_concurrency = max_concurrency or settings.max_concurrency
    base_prompt = _load_prompt_base(prompt_path)

    out = copy.deepcopy(export_doc)
    items = out.get("items") or []
    sem = asyncio.Semaphore(max_concurrency)
    stats = {"tasks_total": 0, "tasks_ok": 0, "tasks_failed": 0}

    async def _translate_with_model(
        payload: dict,
        lang: str,
        model_name: str,
        si: str,
    ) -> tuple[dict | None, str | None]:
        """Up to 3 attempts on one model; retries only on 429/503."""
        last_err: str | None = None
        for attempt in range(1, 4):
            async with sem:
                stats["tasks_total"] += 1
                try:
                    result = await _translate_one_lang(payload, lang, model_name, si)
                    return result, None
                except Exception as exc:
                    last_err = str(exc)
                    if attempt < 3 and ("429" in last_err or "503" in last_err):
                        await asyncio.sleep(
                            _extract_retry_delay(last_err) if "429" in last_err else 5
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
        if translation_block_filled(item, lang):
            return
        payload = _english_to_payload(english)
        content = payload.get("content") or ""
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
            result, model_err = await _translate_with_model(payload, lang, model_name, si)
            if result is not None:
                item.setdefault("translations", {})
                if not isinstance(item["translations"], dict):
                    item["translations"] = {}
                item["translations"][lang] = {
                    "title": result["title"],
                    "content": result["content"],
                    "yoast_title": result["yoast_title"],
                    "yoast_desc": result["yoast_desc"],
                    "acf_fields": copy.deepcopy(result["acf_fields"]),
                }
                stats["tasks_ok"] += 1
                if on_event:
                    meta = {"post_id": oid, "lang": lang, "model": model_name}
                    if model_index > 0:
                        meta["used_fallback"] = True
                    on_event("info", "task.ok", meta)
                return
            last_err = model_err or f"{model_name} failed after retries"
            if model_index == 0 and len(content) > content_chunk_threshold() and on_event:
                on_event(
                    "warn",
                    "task.chunked_attempt_failed",
                    {
                        "post_id": oid,
                        "lang": lang,
                        "model": model_name,
                        "content_chars": len(content),
                        "chunks": len(split_html_content(content)),
                        "error": last_err[:500],
                    },
                )

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

    assert_all_target_langs_filled(out, target_langs)

    return out, stats
