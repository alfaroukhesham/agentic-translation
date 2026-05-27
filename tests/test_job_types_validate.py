from app.validate_export import validate_export_payload


def test_news_requires_title_only():
    doc = {
        "job_type": "news",
        "items": [
            {
                "original_post_id": 1,
                "english": {
                    "id": 1,
                    "title": "Headline",
                    "slug": "headline",
                    "content": "<p>body</p>",
                },
            }
        ],
    }
    assert validate_export_payload(doc, "news") == []


def test_page_acf_requires_acf_fields():
    doc = {
        "job_type": "page_acf",
        "items": [
            {
                "original_post_id": 12,
                "english": {"id": 12, "title": "Page", "acf_fields": {"hero": "Hello"}},
            }
        ],
    }
    assert validate_export_payload(doc, "page_acf") == []


def test_page_acf_rejects_empty_acf():
    doc = {
        "items": [
            {
                "original_post_id": 12,
                "english": {"id": 12, "title": "Page", "acf_fields": {}},
            }
        ],
    }
    errs = validate_export_payload(doc, "page_acf")
    assert any("acf_fields" in e for e in errs)
