from app.validate_export import validate_export_payload, validate_target_langs


def test_valid_minimal():
    data = {
        "items": [
            {
                "original_post_id": 1,
                "english": {"title": "T", "content": "<p>x</p>"},
            }
        ]
    }
    assert validate_export_payload(data) == []


def test_missing_items():
    assert validate_export_payload({}) != []


def test_target_langs():
    assert validate_target_langs(["fr", "es"]) == []
    assert validate_target_langs([]) != []
    assert validate_target_langs(["xx"]) != []
