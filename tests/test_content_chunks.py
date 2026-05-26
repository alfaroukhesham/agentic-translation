import pytest
from unittest.mock import patch

from app.content_chunks import split_html_content
from app.blog_export import run_blog_export


def test_small_content_single_chunk():
    html = "<p>hello</p>"
    assert split_html_content(html, max_chars=1000) == [html]


def test_splits_on_paragraph_boundary():
    parts = ["<p>" + ("word " * 200) + "</p>"] * 5
    html = "".join(parts)
    chunks = split_html_content(html, max_chars=2000)
    assert len(chunks) >= 2
    assert "".join(chunks) == html


@pytest.mark.asyncio
async def test_long_content_uses_chunked_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTENT_CHUNK_CHARS", "5000")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    big_body = "<p>" + ("Long paragraph. " * 400) + "</p>" * 3
    assert len(big_body) > 5000

    calls: list[str] = []

    async def fake_gemini(payload, prompt, model_name):
        calls.append(
            "meta" if "METADATA MODE" in prompt or payload.get("content") == "" else "chunk"
        )
        if calls[-1] == "meta":
            return {
                "title": "शीर्षक",
                "content": "",
                "yoast_title": "",
                "yoast_desc": "",
                "acf_fields": [],
            }
        return {"content": "【hi】" + (payload.get("content_chunk") or "")}

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Translate.", encoding="utf-8")

    export = {
        "items": [
            {
                "original_post_id": 7675,
                "english": {"title": "Green Visa", "content": big_body},
            }
        ]
    }

    with patch("app.blog_export._gemini_raw_json_payload", side_effect=fake_gemini):
        out, stats = await run_blog_export(
            export_doc=export,
            target_langs=["hi"],
            prompt_path=prompt,
        )

    assert stats["tasks_ok"] == 1
    assert "meta" in calls
    assert calls.count("chunk") >= 2
    assert out["items"][0]["translations"]["hi"]["content"]
