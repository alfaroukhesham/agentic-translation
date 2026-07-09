import pytest
from unittest.mock import patch

from app.blog_export import run_blog_export
from app.translation_guard import IncompleteTranslationsError


def _export_one_post():
    return {
        "items": [
            {
                "original_post_id": 1,
                "english": {"title": "Hello", "content": "<p>world</p>"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_falls_back_to_flash_after_lite_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACK", "gemini-3.5-flash")
    from app.config import get_settings

    get_settings.cache_clear()

    calls: list[str] = []

    async def fake_translate(payload, lang, model_name, si):
        calls.append(model_name)
        if model_name == "gemini-3.1-flash-lite":
            raise ValueError("lite model empty output")
        return {
            "title": "नमस्ते",
            "content": "<p>दुनिया</p>",
            "yoast_title": "",
            "yoast_desc": "",
            "acf_fields": [],
        }

    events: list[tuple] = []

    def on_event(level, event, meta):
        events.append((level, event, meta))

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Translate faithfully.", encoding="utf-8")

    with patch("app.blog_export._translate_one_lang", side_effect=fake_translate):
        out, stats = await run_blog_export(
            export_doc=_export_one_post(),
            target_langs=["hi"],
            prompt_path=prompt,
            on_event=on_event,
        )

    assert calls == ["gemini-3.1-flash-lite", "gemini-3.5-flash"]
    assert stats["tasks_ok"] == 1
    assert stats["tasks_failed"] == 0
    assert out["items"][0]["translations"]["hi"]["title"] == "नमस्ते"
    assert any(e[1] == "task.model_fallback" for e in events)


@pytest.mark.asyncio
async def test_fails_only_after_both_models_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACK", "gemini-3.5-flash")
    from app.config import get_settings

    get_settings.cache_clear()

    async def always_fail(payload, lang, model_name, si):
        raise ValueError(f"{model_name} failed")

    failures: list[tuple] = []

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Translate faithfully.", encoding="utf-8")

    with patch("app.blog_export._translate_one_lang", side_effect=always_fail):
        with pytest.raises(IncompleteTranslationsError):
            await run_blog_export(
                export_doc=_export_one_post(),
                target_langs=["ha"],
                prompt_path=prompt,
                on_task_failure=lambda pid, lang, err, n: failures.append((lang, err)),
            )

    assert failures
    assert failures[0][0] == "ha"
