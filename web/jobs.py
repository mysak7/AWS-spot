import threading
import uuid
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "message": "Starting...",
            "result": None,
            "error": None,
            "created_at": datetime.now(timezone.utc),
        }
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def update_job(job_id: str, **kwargs: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def append_job_line(job_id: str, line: str) -> None:
    """Append a line to job result (list) and update message."""
    with _lock:
        if job_id in _jobs:
            r = _jobs[job_id].get("result")
            if isinstance(r, list):
                r.append(line)
            _jobs[job_id]["message"] = line[:120]
