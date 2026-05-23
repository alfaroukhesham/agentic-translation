from app.config import SUPPORTED_LANGS


def validate_export_payload(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["payload must be a JSON object"]
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        errors.append("items must be a non-empty array")
        return errors
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{i}] must be an object")
            continue
        if "original_post_id" not in item:
            errors.append(f"items[{i}] missing original_post_id")
        english = item.get("english")
        if not isinstance(english, dict):
            errors.append(f"items[{i}] missing english object")
            continue
        for field in ("title", "content"):
            val = english.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"items[{i}].english.{field} must be a non-empty string")
    return errors


def validate_target_langs(langs: list[str]) -> list[str]:
    if not langs:
        return ["target_langs must be non-empty"]
    errors: list[str] = []
    for lang in langs:
        if lang not in SUPPORTED_LANGS:
            errors.append(f"unsupported language: {lang}")
    return errors
