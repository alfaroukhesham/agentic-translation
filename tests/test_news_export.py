import pytest
from unittest.mock import patch

from app.news_export import run_news_export


def _news_doc():
    return {
        "job_type": "news",
        "items": [
            {
                "original_post_id": 7189,
                "english": {
                    "id": 7189,
                    "title": "UAE family visa guide",
                    "slug": "uae-family-visa-guide",
                    "content": "<p>english body</p>",
                },
                "translations": {"fr": {"title": ""}},
            }
        ],
    }


@pytest.mark.asyncio
async def test_news_fills_title_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    async def fake_translate(title, lang, model_name, si):
        return {"title": "Guide du visa familial"}

    prompt = tmp_path / "prompt-news.md"
    prompt.write_text("Translate news titles.", encoding="utf-8")

    with patch("app.news_export._translate_title", side_effect=fake_translate):
        out, stats = await run_news_export(
            export_doc=_news_doc(),
            target_langs=["fr"],
            prompt_path=prompt,
        )

    assert stats["tasks_ok"] == 1
    block = out["items"][0]["translations"]["fr"]
    assert block == {"title": "Guide du visa familial"}
    assert "content" not in block
    assert "missing_languages" not in out["items"][0]
    assert out["items"][0]["english"]["content"] == "<p>english body</p>"
