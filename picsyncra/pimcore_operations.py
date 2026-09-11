from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
import secrets
import threading
import time
from typing import Callable

from .redaction import sanitize_free_text

TERMINAL_STATUSES = {"completed", "partial", "failed"}
SENSITIVE_LOG_KEYS = {
    "api_key",
    "x-api-key",
    "authorization",
    "cookie",
    "set-cookie",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
}


def redact_pimcore_log_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).casefold() in SENSITIVE_LOG_KEYS
                else redact_pimcore_log_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_pimcore_log_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_free_text(value)
    return value


class PimcoreOperationRegistry:
    def __init__(
        self,
        *,
        executor: Executor | None = None,
        retention_seconds: int = 6 * 60 * 60,
    ) -> None:
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="pimcore",
        )
        self._retention_seconds = retention_seconds
        self._items: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def _event(
        self,
        operation_id: str,
        stage: str,
        severity: str,
        message: str,
        **details: object,
    ) -> None:
        with self._lock:
            operation = self._items.get(operation_id)
            if not operation:
                return
            sequence = len(operation["events"]) + 1
            now = time.time()
            event = {
                "sequence": sequence,
                "timestamp": now,
                "elapsed_ms": int(
                    max(0, now - float(operation["started_at"] or now)) * 1000
                ),
                "stage": stage,
                "severity": severity,
                "message": sanitize_free_text(message),
            }
            event.update(redact_pimcore_log_value(details))
            operation["events"].append(event)

    def start(
        self,
        *,
        operation_type: str,
        username: str,
        values: dict[str, object],
        cleanup_policy: str,
        worker: Callable[[Callable[..., None]], dict[str, object]],
        persist: Callable[[dict[str, object]], object],
    ) -> dict[str, object]:
        self.cleanup()
        operation_id = secrets.token_hex(12)
        created_at = time.time()
        operation = {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "username": username,
            "values": redact_pimcore_log_value(dict(values)),
            "cleanup_policy": cleanup_policy,
            "status": "queued",
            "created_at": created_at,
            "started_at": 0.0,
            "finished_at": 0.0,
            "total_ms": 0,
            "events": [],
            "result": {},
            "error": "",
        }
        with self._lock:
            self._items[operation_id] = operation
        self._executor.submit(self._run, operation_id, worker, persist)
        return {"operation_id": operation_id, "status": "queued"}

    def _run(self, operation_id, worker, persist) -> None:
        with self._lock:
            operation = self._items[operation_id]
            operation["status"] = "running"
            operation["started_at"] = time.time()
        self._event(operation_id, "start", "info", "Rozpoczeto operacje Pimcore.")
        try:
            result = worker(
                lambda stage, severity, message, **details: self._event(
                    operation_id,
                    stage,
                    severity,
                    message,
                    **details,
                )
            )
            status = str(result.get("status") or "completed")
            if status not in {"completed", "partial"}:
                status = "completed"
            with self._lock:
                operation = self._items[operation_id]
                operation["status"] = status
                operation["result"] = redact_pimcore_log_value(dict(result))
            self._event(
                operation_id,
                "finish",
                "warning" if status == "partial" else "success",
                "Zakonczono operacje Pimcore.",
            )
        except Exception as exc:
            with self._lock:
                operation = self._items[operation_id]
                operation["status"] = "failed"
                operation["error"] = sanitize_free_text(
                    str(exc) or exc.__class__.__name__
                )
            self._event(
                operation_id,
                "finish",
                "error",
                sanitize_free_text(str(exc) or exc.__class__.__name__),
            )
        finally:
            with self._lock:
                operation = self._items[operation_id]
                operation["finished_at"] = time.time()
                operation["total_ms"] = int(
                    max(0, operation["finished_at"] - operation["started_at"]) * 1000
                )
                snapshot = self._snapshot(operation, after_sequence=0)
            persist(snapshot)

    def _snapshot(
        self,
        operation: dict[str, object],
        after_sequence: int,
    ) -> dict[str, object]:
        return {
            key: value
            for key, value in operation.items()
            if key != "events"
        } | {
            "events": [
                dict(item)
                for item in operation["events"]
                if int(item["sequence"]) > after_sequence
            ]
        }

    def status(
        self,
        operation_id: str,
        *,
        after_sequence: int = 0,
    ) -> dict[str, object] | None:
        self.cleanup()
        with self._lock:
            operation = self._items.get(operation_id)
            if not operation:
                return None
            return self._snapshot(operation, max(0, int(after_sequence)))

    def cleanup(self, now: float | None = None) -> None:
        cutoff = (time.time() if now is None else now) - self._retention_seconds
        with self._lock:
            for operation_id, item in list(self._items.items()):
                if (
                    item["status"] in TERMINAL_STATUSES
                    and float(item["finished_at"] or 0) < cutoff
                ):
                    self._items.pop(operation_id, None)
