from app.job_types import DEFAULT_JOB_TYPE, JobType, storage_prefix


def export_key(wp_job_id: str, job_type: JobType | str = DEFAULT_JOB_TYPE) -> str:
    prefix = storage_prefix(job_type).strip("/")
    return f"{prefix}/exports/{wp_job_id}/export.json"


def result_key(wp_job_id: str, job_type: JobType | str = DEFAULT_JOB_TYPE) -> str:
    prefix = storage_prefix(job_type).strip("/")
    return f"{prefix}/results/{wp_job_id}/result.json"
