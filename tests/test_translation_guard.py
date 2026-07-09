import pytest

from app.translation_guard import (
    IncompleteTranslationsError,
    assert_all_target_langs_filled,
    finalize_export_translations,
    missing_languages_for_item,
    prune_item_translations,
    translation_block_filled,
)


def _item_with_lang(lang: str, title: str = "T", content: str = "<p>x</p>"):
    return {
        "original_post_id": 1,
        "english": {"title": "English title", "content": "<p>english</p>"},
        "translations": {
            lang: {
                "title": title,
                "content": content,
                "yoast_title": "",
                "yoast_desc": "",
                "acf_fields": [],
            }
        },
    }


def test_translation_block_filled_requires_non_empty():
    item = _item_with_lang("hi", title="", content="")
    assert not translation_block_filled(item, "hi")


def test_prune_removes_empty_requested_lang():
    item = {
        "original_post_id": 1,
        "english": {"title": "E", "content": "<p>e</p>"},
        "translations": {
            "hi": {"title": "", "content": ""},
            "fr": {
                "title": "Bonjour",
                "content": "<p>fr</p>",
                "yoast_title": "",
                "yoast_desc": "",
                "acf_fields": [],
            },
        },
    }
    prune_item_translations(item, ["hi", "fr"])
    assert "hi" not in item["translations"]
    assert "fr" in item["translations"]


def test_assert_all_target_langs_filled_success():
    doc = {
        "items": [
            _item_with_lang("hi"),
            {
                "original_post_id": 2,
                "english": {"title": "E2", "content": "<p>e2</p>"},
                "translations": {
                    "hi": {
                        "title": "H2",
                        "content": "<p>h2</p>",
                        "yoast_title": "",
                        "yoast_desc": "",
                        "acf_fields": [],
                    }
                },
            },
        ]
    }
    assert_all_target_langs_filled(doc, ["hi"])
    assert "missing_languages" not in doc["items"][0]
    assert "missing_languages" not in doc["items"][1]
    assert "hi" in doc["items"][0]["translations"]


def test_assert_fails_when_lang_missing():
    doc = {"items": [_item_with_lang("fr")]}
    with pytest.raises(IncompleteTranslationsError) as exc:
        assert_all_target_langs_filled(doc, ["hi", "fr"])
    assert "hi" in str(exc.value)
    assert doc["items"][0]["missing_languages"] == ["hi"]


def test_subset_only_checks_requested():
    item = _item_with_lang("hi")
    assert missing_languages_for_item(item, ["hi"]) == []
    assert missing_languages_for_item(item, ["hi", "fr"]) == ["fr"]


def test_finalize_omits_missing_languages_when_complete():
    doc = {"items": [_item_with_lang("fr")]}
    details = finalize_export_translations(doc, ["fr"])
    assert details == []
    assert "missing_languages" not in doc["items"][0]


def test_finalize_reports_per_post():
    doc = {
        "items": [
            _item_with_lang("fr"),
            {
                "original_post_id": 2,
                "english": {"title": "E", "content": "<p>e</p>"},
                "translations": {},
            },
        ]
    }
    details = finalize_export_translations(doc, ["fr", "hi"])
    assert len(details) == 2
    assert details[1]["missing"] == ["fr", "hi"]
