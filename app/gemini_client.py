"""Shared Gemini JSON translation helpers."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from app.config import get_settings


def strip_fences(text: str) -> str:
    if text is None:
        raise ValueError("Model returned null output text")
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()
    return text


def safe_parse_json_any(text: str | None) -> Any:
    if text is None:
        raise ValueError("Model returned null output text")
    text = strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        from json_repair import repair_json

        return json.loads(repair_json(text))


def extract_retry_delay(error_str: str) -> int:
    match = re.search(r"retryDelay.*?['\"](\d+)s['\"]", error_str)
    return int(match.group(1)) + 3 if match else 60


async def gemini_raw_json_payload(payload: dict, prompt: str, model_name: str) -> dict:
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
    data = safe_parse_json_any(raw_text)
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        else:
            raise ValueError(f"Expected JSON object; got list length {len(data)}")
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    return data
