"""Privacy-bounded aggregation for lightweight frontend runtime polling."""

from __future__ import annotations

from typing import Any, Callable, Mapping


Provider = Callable[[], Mapping[str, Any]]


class RuntimeStatusService:
    """Project existing runtime providers into one small polling snapshot."""

    def __init__(
        self,
        *,
        health_provider: Provider,
        file_index_provider: Provider,
        process_queue_provider: Provider,
        active_clients_provider: Provider,
        clock: Callable[[], str],
    ) -> None:
        self._health_provider = health_provider
        self._file_index_provider = file_index_provider
        self._process_queue_provider = process_queue_provider
        self._active_clients_provider = active_clients_provider
        self._clock = clock

    def snapshot(self, user_context: Mapping[str, Any]) -> dict[str, Any]:
        """Return summaries and stable versions without provider detail lists."""

        health = self._health_snapshot()
        file_index_version, file_index_state = self._file_index_snapshot()
        process_version, process_active = self._process_queue_snapshot()
        presence_allowed = str(user_context.get("role") or "") == "admin"

        versions: dict[str, Any] = {
            "file_index": file_index_version,
            "process_queue": process_version,
            "active_clients": "unknown",
        }
        summary: dict[str, Any] = {
            "file_index_state": file_index_state,
            "process_active": process_active,
            "active_users_enabled": presence_allowed,
        }
        if presence_allowed:
            active_clients_version, active_users_count = self._active_clients_snapshot()
            versions["active_clients"] = active_clients_version
            summary["active_users_count"] = active_users_count

        return {
            "observed_at": self._clock(),
            "health": health,
            "versions": versions,
            "summary": summary,
        }

    def _health_snapshot(self) -> dict[str, Any]:
        try:
            payload = self._health_provider()
            ok = bool(payload.get("ok"))
            status = str(payload.get("status") or ("online" if ok else "degraded"))
            return {"ok": ok, "status": status}
        except Exception:
            return {"ok": False, "status": "unknown"}

    def _file_index_snapshot(self) -> tuple[Any, str]:
        try:
            payload = self._file_index_provider()
            state = str(payload.get("state") or "unknown")
            generated_at = str(payload.get("generated_at") or "")
            version = f"{generated_at}:{state}" if generated_at else state
            return version, state
        except Exception:
            return "unknown", "unknown"

    def _process_queue_snapshot(self) -> tuple[Any, Any]:
        try:
            payload = self._process_queue_provider()
            return (
                _version(payload.get("generation")),
                _count(payload.get("active_count")),
            )
        except Exception:
            return "unknown", "unknown"

    def _active_clients_snapshot(self) -> tuple[Any, Any]:
        try:
            payload = self._active_clients_provider()
            return _version(payload.get("generation")), _count(payload.get("count"))
        except Exception:
            return "unknown", "unknown"


def _version(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return "unknown"
    if isinstance(value, str) and not value.strip():
        return "unknown"
    return value


def _count(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return "unknown"
    return value
