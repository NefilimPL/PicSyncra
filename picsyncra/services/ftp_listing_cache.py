"""Process-local cache for complete FTP directory listings."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Callable, Mapping


_PROCESS_CACHE_SECRET = secrets.token_bytes(32)


@dataclass(frozen=True)
class RemoteFileRecord:
    """One remote file returned by a complete FTP listing."""

    name: str


@dataclass
class _CachedListing:
    records: list[RemoteFileRecord]
    refreshed_at: float


def _location_key(config: Mapping[str, object]) -> str:
    material = json.dumps(
        [
            str(config.get("host") or ""),
            int(config.get("port") or 21),
            str(config.get("user") or ""),
            str(config.get("pass") or ""),
            str(config.get("path") or ""),
            bool(config.get("pasv", True)),
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_PROCESS_CACHE_SECRET, material, hashlib.sha256).hexdigest()


class RemoteListingCache:
    """Reuse an FTP listing for a bounded period without storing credentials."""

    def __init__(self, ttl_seconds: float = 60) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._listings: dict[str, _CachedListing] = {}
        self._condition = threading.Condition()
        self._refreshing: set[str] = set()
        self._refresh_generations: dict[str, int] = {}
        self._refresh_errors: dict[str, BaseException] = {}
        self._wildcard_capabilities: dict[str, str] = {}

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(ttl_seconds={self._ttl_seconds!r}, "
            f"entries={len(self._listings)})"
        )

    def diagnostic_key(self, config: Mapping[str, object]) -> str:
        """Return a non-secret identifier suitable for diagnostic output."""
        return f"ftp:{_location_key(config)[:16]}"

    def get_if_fresh(
        self,
        config: Mapping[str, object],
        *,
        now: float | None = None,
    ) -> list[RemoteFileRecord] | None:
        """Return a full snapshot only when it is still inside its TTL."""
        checked_at = time.monotonic() if now is None else float(now)
        key = _location_key(config)
        with self._condition:
            cached = self._listings.get(key)
            if (
                cached is None
                or checked_at - cached.refreshed_at >= self._ttl_seconds
            ):
                return None
            return list(cached.records)

    def wildcard_capability(self, config: Mapping[str, object]) -> str:
        """Return whether this FTP location accepts targeted wildcard ``NLST``."""
        key = _location_key(config)
        with self._condition:
            return self._wildcard_capabilities.get(key, "unknown")

    def set_wildcard_capability(
        self,
        config: Mapping[str, object],
        capability: str,
    ) -> None:
        """Record a tested targeted-listing capability for this location."""
        if capability not in {"unknown", "supported", "unsupported"}:
            raise ValueError("unsupported FTP wildcard capability state")
        key = _location_key(config)
        with self._condition:
            self._wildcard_capabilities[key] = capability

    def get_or_refresh(
        self,
        config: Mapping[str, object],
        loader: Callable[[], list[RemoteFileRecord]],
        *,
        now: float | None = None,
    ) -> list[RemoteFileRecord]:
        """Return the current snapshot, loading it only after its TTL expires."""
        refreshed_at = time.monotonic() if now is None else float(now)
        key = _location_key(config)
        with self._condition:
            while True:
                cached = self._listings.get(key)
                if (
                    cached is not None
                    and refreshed_at - cached.refreshed_at < self._ttl_seconds
                ):
                    return list(cached.records)
                if key not in self._refreshing:
                    self._refreshing.add(key)
                    break
                generation_before_wait = self._refresh_generations.get(key, 0)
                while key in self._refreshing:
                    self._condition.wait()
                if self._refresh_generations.get(key, 0) != generation_before_wait:
                    cached = self._listings.get(key)
                    if cached is not None:
                        return list(cached.records)
                    error = self._refresh_errors.get(key)
                    if error is not None:
                        raise error

        try:
            records = list(loader())
        except BaseException as exc:
            with self._condition:
                self._refreshing.discard(key)
                self._refresh_generations[key] = (
                    self._refresh_generations.get(key, 0) + 1
                )
                self._refresh_errors[key] = exc
                cached = self._listings.get(key)
                if cached is not None:
                    cached.refreshed_at = refreshed_at
                self._condition.notify_all()
            if cached is not None and isinstance(exc, Exception):
                return list(cached.records)
            raise

        with self._condition:
            self._listings[key] = _CachedListing(
                records=records,
                refreshed_at=refreshed_at,
            )
            self._refreshing.discard(key)
            self._refresh_generations[key] = self._refresh_generations.get(key, 0) + 1
            self._refresh_errors.pop(key, None)
            self._condition.notify_all()
        return list(records)

    def apply_uploaded(
        self,
        config: Mapping[str, object],
        records: list[RemoteFileRecord],
    ) -> None:
        """Merge files confirmed by FTP ``STOR`` into the cached snapshot."""
        key = _location_key(config)
        with self._condition:
            cached = self._listings.get(key)
            if cached is None:
                return
            replacements = {record.name: record for record in records}
            updated = [
                replacements.pop(record.name, record)
                for record in cached.records
            ]
            updated.extend(replacements.values())
            cached.records = updated

    def apply_deleted(
        self,
        config: Mapping[str, object],
        names: list[str],
    ) -> None:
        """Remove files confirmed by FTP ``DELE`` from the cached snapshot."""
        key = _location_key(config)
        with self._condition:
            cached = self._listings.get(key)
            if cached is None:
                return
            deleted = set(names)
            cached.records = [
                record for record in cached.records if record.name not in deleted
            ]

    def invalidate(self, config: Mapping[str, object]) -> None:
        """Require the next lookup for this location to refresh its snapshot."""
        key = _location_key(config)
        with self._condition:
            cached = self._listings.get(key)
            if cached is not None:
                cached.refreshed_at = float("-inf")
