"""Tests for the process-local FTP listing cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

from picsyncra.services.ftp_listing_cache import (
    RemoteFileRecord,
    RemoteListingCache,
)


FTP_CONFIG = {
    "host": "ftp.example.test",
    "port": 21,
    "user": "operator",
    "pass": "test-secret",
    "path": "/photos",
    "pasv": True,
}


def test_listing_cache_reuses_snapshot_within_ttl_without_exposing_password():
    """A cache regression must neither refresh early nor reveal credentials."""
    cache = RemoteListingCache(ttl_seconds=60)
    calls = 0

    def loader() -> list[RemoteFileRecord]:
        nonlocal calls
        calls += 1
        return [RemoteFileRecord(name="5901_01.jpg")]

    first = cache.get_or_refresh(FTP_CONFIG, loader, now=100.0)
    second = cache.get_or_refresh(FTP_CONFIG, loader, now=159.9)

    assert first == [RemoteFileRecord(name="5901_01.jpg")]
    assert second == first
    assert calls == 1
    assert FTP_CONFIG["pass"] not in repr(cache)
    assert FTP_CONFIG["pass"] not in cache.diagnostic_key(FTP_CONFIG)


def test_listing_cache_singleflight_runs_one_loader_for_concurrent_refreshes():
    """Concurrent cache misses must share one full FTP listing request."""
    cache = RemoteListingCache(ttl_seconds=60)
    callers_ready = threading.Barrier(12)
    loader_started = threading.Event()
    release_loader = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def loader() -> list[RemoteFileRecord]:
        nonlocal calls
        with calls_lock:
            calls += 1
        loader_started.set()
        assert release_loader.wait(timeout=5)
        return [RemoteFileRecord(name="5901_01.jpg")]

    def get_listing() -> list[RemoteFileRecord]:
        callers_ready.wait(timeout=5)
        return cache.get_or_refresh(FTP_CONFIG, loader, now=100.0)

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(get_listing) for _ in range(12)]
        assert loader_started.wait(timeout=5)
        release_loader.set()
        listings = [future.result(timeout=5) for future in futures]

    assert calls == 1
    assert listings == [[RemoteFileRecord(name="5901_01.jpg")]] * 12


def test_listing_cache_applies_confirmed_changes_and_can_be_invalidated():
    """Confirmed FTP mutations must update a live snapshot without relisting."""
    cache = RemoteListingCache(ttl_seconds=60)
    calls = 0

    def loader() -> list[RemoteFileRecord]:
        nonlocal calls
        calls += 1
        return [RemoteFileRecord(name="5901_01.jpg")]

    assert cache.get_or_refresh(FTP_CONFIG, loader, now=100.0) == [
        RemoteFileRecord(name="5901_01.jpg")
    ]

    cache.apply_uploaded(FTP_CONFIG, [RemoteFileRecord(name="5901_02.jpg")])
    cache.apply_deleted(FTP_CONFIG, ["5901_01.jpg"])

    assert cache.get_or_refresh(FTP_CONFIG, loader, now=101.0) == [
        RemoteFileRecord(name="5901_02.jpg")
    ]
    assert calls == 1

    cache.invalidate(FTP_CONFIG)

    assert cache.get_or_refresh(FTP_CONFIG, loader, now=102.0) == [
        RemoteFileRecord(name="5901_01.jpg")
    ]
    assert calls == 2


def test_failed_refresh_keeps_previous_snapshot_for_concurrent_callers():
    """A failed refresh must not turn a complete listing into an empty result."""
    cache = RemoteListingCache(ttl_seconds=60)
    previous = [RemoteFileRecord(name="5901_01.jpg")]
    assert cache.get_or_refresh(FTP_CONFIG, lambda: previous, now=0.0) == previous

    callers_ready = threading.Barrier(12)
    loader_started = threading.Event()
    release_loader = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def failing_loader() -> list[RemoteFileRecord]:
        nonlocal calls
        with calls_lock:
            calls += 1
        loader_started.set()
        assert release_loader.wait(timeout=5)
        raise OSError("ftp temporarily unavailable")

    def get_stale_listing() -> list[RemoteFileRecord]:
        callers_ready.wait(timeout=5)
        return cache.get_or_refresh(FTP_CONFIG, failing_loader, now=61.0)

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(get_stale_listing) for _ in range(12)]
        assert loader_started.wait(timeout=5)
        release_loader.set()
        listings = [future.result(timeout=5) for future in futures]

    assert calls == 1
    assert listings == [previous] * 12


def test_listing_cache_exposes_only_fresh_snapshot_and_location_capability():
    """Lookup code may reuse only a fresh full listing and its capability state."""
    cache = RemoteListingCache(ttl_seconds=60)
    records = [RemoteFileRecord(name="5901_01.jpg")]

    assert cache.get_if_fresh(FTP_CONFIG, now=100.0) is None
    assert cache.wildcard_capability(FTP_CONFIG) == "unknown"
    assert cache.get_or_refresh(FTP_CONFIG, lambda: records, now=100.0) == records

    cache.set_wildcard_capability(FTP_CONFIG, "supported")

    assert cache.get_if_fresh(FTP_CONFIG, now=159.9) == records
    assert cache.wildcard_capability(FTP_CONFIG) == "supported"
    assert cache.get_if_fresh(FTP_CONFIG, now=160.0) is None
