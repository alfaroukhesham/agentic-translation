from app.config import get_settings


def export_key(wp_job_id: str) -> str:
    prefix = get_settings().storage_prefix.strip("/")
    return f"{prefix}/exports/{wp_job_id}/export.json"


def result_key(wp_job_id: str) -> str:
    prefix = get_settings().storage_prefix.strip("/")
    return f"{prefix}/results/{wp_job_id}/result.json"
