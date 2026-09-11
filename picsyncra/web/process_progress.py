"""Rate-limit durable snapshots of in-memory process-job progress."""

from dataclasses import dataclass
import threading


@dataclass
class _PersistedProgress:
    stage: str
    status: str
    at: float


class ProcessProgressGate:
    """Decide when a process-job snapshot represents durable new progress."""

    def __init__(self, min_interval_seconds: float = 0.5):
        self._interval = min_interval_seconds
        self._items: dict[str, _PersistedProgress] = {}
        self._lock = threading.Lock()

    def should_persist(
        self,
        job_id: str,
        *,
        stage: str,
        status: str,
        now: float,
        force: bool = False,
    ) -> bool:
        with self._lock:
            previous = self._items.get(job_id)
            due = (
                force
                or previous is None
                or previous.stage != stage
                or previous.status != status
                or now - previous.at >= self._interval
            )
            if due:
                self._items[job_id] = _PersistedProgress(stage, status, now)
            return due

    def forget(self, job_id: str) -> None:
        with self._lock:
            self._items.pop(job_id, None)
