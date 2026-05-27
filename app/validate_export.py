from app.config import SUPPORTED_LANGS
from app.job_types import DEFAULT_JOB_TYPE, JobType, normalize_job_type


def validate_export_payload(data: dict, job_type: JobType | str = DEFAULT_JOB_TYPE) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["payload must be a JSON object"]
    try:
        jt = normalize_job_type(job_type)
    except ValueError as exc:
        return [str(exc)]

    doc_type = data.get("job_type")
    if doc_type is not None and str(doc_type).strip():
        try:
            if normalize_job_type(str(doc_type)) != jt:
                errors.append(f"job_type mismatch: request={jt}, export={doc_type}")
        except ValueError:
            errors.append(f"export job_type invalid: {doc_type}")

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

        if jt == "news":
            title = english.get("title")
            if not isinstance(title, str) or not title.strip():
                errors.append(f"items[{i}].english.title must be a non-empty string")
            continue

        if jt == "page_acf":
            acf = english.get("acf_fields")
            if not isinstance(acf, dict) or not acf:
                errors.append(f"items[{i}].english.acf_fields must be a non-empty object")
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
