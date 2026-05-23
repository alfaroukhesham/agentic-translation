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


def _validate_translation(data: dict, target_lang: str | None = None) -> dict:
    data = _coerce_translation_dict(data, target_lang=target_lang)
    for key in ("title", "content", "yoast_title", "yoast_desc"):
        if key not in data:
            raise ValueError(f"Missing key '{key}' in model output")
        if not isinstance(data[key], str):
            raise ValueError(f"Expected '{key}' to be a string")
    if "acf_fields" not in data:
        raise ValueError("Missing key 'acf_fields'")
    data["yoast_title"] = _truncate_chars(data["yoast_title"], 60)
    data["yoast_desc"] = _truncate_chars(data["yoast_desc"], 160)
    return data


async def _translate_one_lang(
    payload: dict,
    lang: str,
    gemini_model: str,
    system_instruction: str,
) -> dict:
    raw = await _gemini_raw_json_payload(payload, system_instruction, gemini_model)
    out = _validate_translation(raw, target_lang=lang)
    if _block_echoes_english(
        {"title": payload.get("title", ""), "content": payload.get("content", "")},
        out,
    ):
        raise ValueError("Model output still matches English source")
    return out


def _translation_filled(item: dict, lang: str) -> bool:
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
    return not _block_echoes_english(english if isinstance(english, dict) else {}, block)


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
    gemini_model = gemini_model or settings.gemini_model
    max_concurrency = max_concurrency or settings.max_concurrency
    base_prompt = _load_prompt_base(prompt_path)

    out = copy.deepcopy(export_doc)
    items = out.get("items") or []
    sem = asyncio.Semaphore(max_concurrency)
    stats = {"tasks_total": 0, "tasks_ok": 0, "tasks_failed": 0}

    async def _worker(item: dict, lang: str) -> None:
        nonlocal stats
        oid = item.get("original_post_id")
        english = item.get("english") or {}
        if not isinstance(english, dict):
            return
        if _translation_filled(item, lang):
            return
        payload = _english_to_payload(english)
        si = _make_system_instruction(base_prompt, lang)
        last_err = None
        for attempt in range(1, 4):
            async with sem:
                stats["tasks_total"] += 1
                try:
                    result = await _translate_one_lang(payload, lang, gemini_model, si)
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
                        on_event("info", "task.ok", {"post_id": oid, "lang": lang})
                    return
                except Exception as exc:
                    last_err = str(exc)
                    if attempt < 3 and ("429" in last_err or "503" in last_err):
                        await asyncio.sleep(_extract_retry_delay(last_err) if "429" in last_err else 5)
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

    for item in items:
        if not isinstance(item, dict):
            continue
        tr = item.get("translations") or {}
        missing = [lang for lang in target_langs if not _translation_filled(item, lang)]
        item["missing_languages"] = missing

    return out, stats
