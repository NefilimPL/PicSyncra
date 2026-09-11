"""Thread-safe active web-client state with serialized background persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Callable


ClientRecord = dict[str, object]
Serializer = Callable[[list[ClientRecord]], str]


def _clean_client_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^0-9A-Za-z_.-]+", "", text)[:80]


def _client_key(item: ClientRecord) -> str:
    username = str(item.get("username") or "")
    client_id = _clean_client_id(item.get("client_id"))
    if client_id:
        return "|".join([username, "client", client_id])
    return "|".join(
        [
            username,
            str(item.get("remote_address") or ""),
            str(item.get("user_agent") or ""),
        ]
    )


def _last_seen(item: ClientRecord) -> float:
    try:
        return float(item.get("last_seen_epoch") or 0)
    except (TypeError, ValueError):
        return 0.0


def _default_serializer(payload: list[ClientRecord]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


class ActiveClientRegistry:
    """Own active-client memory and persist snapshots on one worker thread."""

    def __init__(
        self,
        path: Path,
        *,
        serializer: Serializer = _default_serializer,
        max_age_seconds: float = 180.0,
        flush_interval_seconds: float = 15.0,
        clock: Callable[[], float] = time.time,
        retry_delay_seconds: float = 1.0,
        deferred_flush_delay_seconds: float | None = None,
    ) -> None:
        self._path = Path(path)
        self._serializer = serializer
        self._max_age_seconds = float(max_age_seconds)
        self._flush_interval_seconds = max(15.0, float(flush_interval_seconds))
        self._clock = clock
        self._retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self._deferred_flush_delay_seconds = (
            None
            if deferred_flush_delay_seconds is None
            else max(0.0, float(deferred_flush_delay_seconds))
        )
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="picsyncra-active-clients",
        )
        self._clients: dict[str, ClientRecord] = {}
        self._generation = 0
        self._persisted_generation = 0
        self._write_scheduled = False
        self._flush_timer: threading.Timer | None = None
        self._last_flush = float("-inf")
        self._accepting_mutations = True
        self._closed = False
        self._last_write_error: Exception | None = None
        self._load_from_disk()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def record(self, item: ClientRecord, *, now: float | None = None) -> None:
        copied = dict(item)
        with self._condition:
            self._ensure_accepting_mutations_locked()
            if now is not None:
                self._prune_locked(float(now))
            self._clients[_client_key(copied)] = copied
            self._generation += 1

    def remove(
        self,
        username: str,
        client_id: str,
        *,
        now: float | None = None,
    ) -> int:
        clean_username = str(username or "").strip()
        clean_client_id = _clean_client_id(client_id)
        if not clean_username or not clean_client_id:
            return 0
        now_value = self._clock() if now is None else float(now)
        with self._condition:
            self._ensure_accepting_mutations_locked()
            self._prune_locked(now_value)
            matching = [
                key
                for key, item in self._clients.items()
                if str(item.get("username") or "").strip() == clean_username
                and _clean_client_id(item.get("client_id")) == clean_client_id
            ]
            for key in matching:
                self._clients.pop(key, None)
            if matching:
                self._generation += 1
            return len(matching)

    def snapshot(self, *, now: float | None = None) -> list[ClientRecord]:
        now_value = self._clock() if now is None else float(now)
        with self._condition:
            self._ensure_accepting_mutations_locked()
            self._prune_locked(now_value)
            return self._snapshot_locked()

    def runtime_summary(self, *, now: float | None = None) -> dict[str, int]:
        """Return one atomic generation/count projection without client details."""

        now_value = self._clock() if now is None else float(now)
        with self._condition:
            self._ensure_accepting_mutations_locked()
            self._prune_locked(now_value)
            usernames = {
                username
                for item in self._clients.values()
                if (username := str(item.get("username") or "").strip())
                and username != "niezalogowany"
            }
            return {
                "generation": self._generation,
                "active_user_count": len(usernames),
            }

    def schedule_flush(self, *, force: bool = False) -> bool:
        with self._condition:
            self._ensure_open_locked()
            if self._write_scheduled:
                return True
            if self._generation <= self._persisted_generation:
                self._cancel_flush_timer_locked()
                return False
            if not force:
                remaining = self._flush_interval_seconds - (
                    self._clock() - self._last_flush
                )
                if remaining > 0:
                    self._schedule_flush_timer_locked(
                        delay=(
                            remaining
                            if self._deferred_flush_delay_seconds is None
                            else self._deferred_flush_delay_seconds
                        ),
                        force=False,
                    )
                    return False
            self._cancel_flush_timer_locked()
            payload = self._snapshot_locked()
            generation = self._generation
            self._write_scheduled = True
        try:
            self._executor.submit(self._write_snapshots, payload, generation)
        except RuntimeError:
            with self._condition:
                self._write_scheduled = False
                self._condition.notify_all()
            return False
        return True

    def flush(self, *, force: bool = False, timeout: float | None = None) -> bool:
        target_generation = self.generation
        scheduled = self.schedule_flush(force=force)
        if not scheduled:
            return self._persisted_at_least(target_generation)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._write_scheduled:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return self._persisted_generation >= target_generation

    def wait_until_idle(self, *, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._write_scheduled or self._flush_timer is not None:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, *, timeout: float = 5.0) -> bool:
        with self._condition:
            if self._closed:
                return not self._write_scheduled
            self._accepting_mutations = False
            self._cancel_flush_timer_locked()
        flushed = self.flush(force=True, timeout=timeout)
        with self._condition:
            self._closed = True
            self._cancel_flush_timer_locked()
        self._executor.shutdown(wait=False, cancel_futures=False)
        return flushed

    def acquire_lock_for_test(self, *, blocking: bool = True) -> bool:
        return self._lock.acquire(blocking=blocking)

    def release_lock_for_test(self) -> None:
        self._lock.release()

    def _load_from_disk(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, list):
            return
        now_value = self._clock()
        expired = False
        for value in payload:
            if not isinstance(value, dict):
                continue
            item = dict(value)
            last_seen = _last_seen(item)
            if not last_seen or now_value - last_seen > self._max_age_seconds:
                expired = True
                continue
            self._clients[_client_key(item)] = item
        if expired:
            self._generation = 1

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("ActiveClientRegistry is closed")

    def _ensure_accepting_mutations_locked(self) -> None:
        self._ensure_open_locked()
        if not self._accepting_mutations:
            raise RuntimeError("ActiveClientRegistry is closing")

    def _prune_locked(self, now_value: float) -> None:
        expired = [
            key
            for key, item in self._clients.items()
            if now_value - _last_seen(item) > self._max_age_seconds
        ]
        for key in expired:
            self._clients.pop(key, None)
        if expired:
            self._generation += 1

    def _snapshot_locked(self) -> list[ClientRecord]:
        ordered = sorted(self._clients.values(), key=_last_seen, reverse=True)[:100]
        return [dict(item) for item in ordered]

    def _cancel_flush_timer_locked(self) -> None:
        timer = self._flush_timer
        self._flush_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_flush_timer_locked(self, *, delay: float, force: bool) -> None:
        if self._flush_timer is not None:
            return

        def run_scheduled_flush() -> None:
            with self._condition:
                if self._flush_timer is not timer:
                    return
                self._flush_timer = None
                if self._closed:
                    self._condition.notify_all()
                    return
            try:
                self.schedule_flush(force=force)
            except RuntimeError:
                pass

        timer = threading.Timer(max(0.0, delay), run_scheduled_flush)
        timer.daemon = True
        self._flush_timer = timer
        timer.start()

    def _write_snapshots(
        self,
        payload: list[ClientRecord],
        generation: int,
    ) -> None:
        while True:
            try:
                serialized = self._serializer(payload)
                self._path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self._path.with_suffix(".json.tmp")
                temp_path.write_text(serialized, encoding="utf-8")
                os.replace(temp_path, self._path)
            except Exception as exc:
                with self._condition:
                    self._last_write_error = exc
                    self._write_scheduled = False
                    if self._accepting_mutations and self._generation > self._persisted_generation:
                        self._schedule_flush_timer_locked(
                            delay=self._retry_delay_seconds,
                            force=True,
                        )
                    self._condition.notify_all()
                return

            with self._condition:
                self._last_write_error = None
                self._last_flush = self._clock()
                self._persisted_generation = max(self._persisted_generation, generation)
                if self._generation <= self._persisted_generation:
                    self._write_scheduled = False
                    self._condition.notify_all()
                    return
                payload = self._snapshot_locked()
                generation = self._generation
                self._condition.notify_all()

    def _persisted_at_least(self, generation: int) -> bool:
        with self._lock:
            return self._persisted_generation >= generation
