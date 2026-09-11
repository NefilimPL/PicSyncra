from __future__ import annotations

import json
import threading

from picsyncra.web import active_clients
from picsyncra.web.active_clients import ActiveClientRegistry


def client_record(username: str, generation: int) -> dict[str, object]:
    return {
        "username": username,
        "client_id": f"browser-{generation}",
        "last_seen_epoch": float(generation),
        "last_seen": "2026-07-27 10:00:00",
        "method": "GET",
        "path": "/",
        "status_code": 200,
        "remote_address": "127.0.0.1",
        "remote_port": 12345,
        "user_agent": "test",
    }


def test_writer_serializes_without_holding_registry_lock(tmp_path):
    lock_was_free = []

    def serializer(payload):
        acquired = registry.acquire_lock_for_test(blocking=False)
        lock_was_free.append(acquired)
        if acquired:
            registry.release_lock_for_test()
        return json.dumps(payload)

    registry = ActiveClientRegistry(tmp_path / "active.json", serializer=serializer)
    try:
        registry.record(client_record("alice", generation=1))
        registry.flush(force=True)
    finally:
        registry.close(timeout=5.0)

    assert lock_was_free == [True]


def test_writer_replaces_file_without_holding_registry_lock(tmp_path, monkeypatch):
    lock_was_free = []
    real_replace = active_clients.os.replace

    def replace(source, destination):
        acquired = registry.acquire_lock_for_test(blocking=False)
        lock_was_free.append(acquired)
        if acquired:
            registry.release_lock_for_test()
        real_replace(source, destination)

    monkeypatch.setattr(active_clients.os, "replace", replace)
    registry = ActiveClientRegistry(tmp_path / "active.json")
    try:
        registry.record(client_record("alice", generation=1))
        registry.flush(force=True)
    finally:
        registry.close(timeout=5.0)

    assert lock_was_free == [True]


def test_generation_change_during_io_schedules_one_follow_up_flush(tmp_path):
    write_started = threading.Event()
    release_write = threading.Event()
    serialized_payloads: list[list[dict[str, object]]] = []

    def serializer(payload):
        serialized_payloads.append(payload)
        if len(serialized_payloads) == 1:
            write_started.set()
            assert release_write.wait(timeout=5.0)
        return json.dumps(payload)

    path = tmp_path / "active.json"
    registry = ActiveClientRegistry(path, serializer=serializer)
    try:
        registry.record(client_record("alice", generation=1))
        registry.schedule_flush(force=True)
        assert write_started.wait(timeout=5.0)

        registry.record(client_record("bob", generation=2))
        release_write.set()
        registry.flush(force=True)
    finally:
        release_write.set()
        registry.close(timeout=5.0)

    assert len(serialized_payloads) == 2
    assert {item["username"] for item in serialized_payloads[-1]} == {"alice", "bob"}
    assert {item["username"] for item in json.loads(path.read_text(encoding="utf-8"))} == {
        "alice",
        "bob",
    }


def test_force_flush_bypasses_minimum_ordinary_interval(tmp_path):
    now = [100.0]
    serialized_payloads = []

    def serializer(payload):
        serialized_payloads.append(payload)
        return json.dumps(payload)

    registry = ActiveClientRegistry(
        tmp_path / "active.json",
        serializer=serializer,
        flush_interval_seconds=1.0,
        clock=lambda: now[0],
    )
    try:
        registry.record(client_record("alice", generation=1))
        assert registry.flush(force=True)

        now[0] = 114.0
        registry.record(client_record("bob", generation=2))
        assert not registry.schedule_flush()
        assert len(serialized_payloads) == 1

        assert registry.flush(force=True)
    finally:
        registry.close(timeout=5.0)

    assert len(serialized_payloads) == 2


def test_first_ordinary_flush_is_not_delayed_by_interval(tmp_path):
    path = tmp_path / "active.json"
    registry = ActiveClientRegistry(path, clock=lambda: 0.0)
    try:
        registry.record(client_record("alice", generation=1))
        assert registry.schedule_flush()
        assert registry.flush(force=True)
    finally:
        registry.close(timeout=5.0)

    assert path.exists()


def test_record_with_request_time_prunes_expired_clients_before_scheduling(tmp_path):
    path = tmp_path / "active.json"
    registry = ActiveClientRegistry(path, max_age_seconds=180.0)
    try:
        registry.record(client_record("stale", generation=1))
        registry.record(client_record("fresh", generation=1000), now=1000.0)
        registry.flush(force=True)
    finally:
        registry.close(timeout=5.0)

    assert [item["username"] for item in json.loads(path.read_text(encoding="utf-8"))] == [
        "fresh"
    ]


def test_runtime_summary_counts_all_distinct_usernames_without_snapshot_cap(tmp_path):
    registry = ActiveClientRegistry(
        tmp_path / "active.json",
        max_age_seconds=180.0,
        clock=lambda: 1000.0,
    )
    try:
        for index in range(130):
            item = client_record(f"user-{index}", generation=index)
            item["last_seen_epoch"] = 1000.0
            registry.record(item)
        duplicate = client_record("user-0", generation=1000)
        duplicate["last_seen_epoch"] = 1000.0
        registry.record(duplicate)
        anonymous = client_record("niezalogowany", generation=1001)
        anonymous["last_seen_epoch"] = 1000.0
        registry.record(anonymous)

        summary = registry.runtime_summary()
    finally:
        registry.close(timeout=5.0)

    assert summary == {"generation": 132, "active_user_count": 130}


def test_runtime_summary_prunes_before_capturing_count_and_generation(tmp_path):
    registry = ActiveClientRegistry(
        tmp_path / "active.json",
        max_age_seconds=180.0,
        clock=lambda: 1000.0,
    )
    try:
        stale = client_record("stale", generation=1)
        stale["last_seen_epoch"] = 1.0
        fresh = client_record("fresh", generation=2)
        fresh["last_seen_epoch"] = 1000.0
        registry.record(stale)
        registry.record(fresh)

        summary = registry.runtime_summary()
    finally:
        registry.close(timeout=5.0)

    assert summary == {"generation": 3, "active_user_count": 1}


def test_temporary_write_error_retries_persistence_without_a_request(tmp_path):
    attempts = []
    path = tmp_path / "active.json"

    def serializer(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise OSError("temporary write failure")
        return json.dumps(payload)

    registry = ActiveClientRegistry(
        path,
        serializer=serializer,
        retry_delay_seconds=0.01,
    )
    try:
        registry.record(client_record("alice", generation=1))
        assert registry.schedule_flush(force=True)
        assert registry.wait_until_idle(timeout=1.0)

        payload = json.loads(path.read_text(encoding="utf-8"))
    finally:
        registry.close(timeout=5.0)

    assert len(attempts) == 2
    assert [item["username"] for item in payload] == ["alice"]


def test_dirty_state_flushes_after_interval_without_another_request(tmp_path):
    now = [0.0]
    serialized_payloads = []
    path = tmp_path / "active.json"

    def serializer(payload):
        serialized_payloads.append(payload)
        return json.dumps(payload)

    registry = ActiveClientRegistry(
        path,
        serializer=serializer,
        flush_interval_seconds=15.0,
        deferred_flush_delay_seconds=0.01,
        clock=lambda: now[0],
    )
    try:
        registry.record(client_record("alice", generation=1))
        assert registry.flush(force=True)

        registry.record(client_record("bob", generation=2))
        assert not registry.schedule_flush()
        now[0] = 15.0
        assert registry.wait_until_idle(timeout=1.0)

        payload = json.loads(path.read_text(encoding="utf-8"))
    finally:
        registry.close(timeout=5.0)

    assert len(serialized_payloads) == 2
    assert {item["username"] for item in payload} == {"alice", "bob"}


def test_close_seals_mutations_before_flushing(tmp_path, monkeypatch):
    flush_finished = threading.Event()
    allow_close_to_finish = threading.Event()
    close_errors = []
    path = tmp_path / "active.json"
    registry = ActiveClientRegistry(path)
    registry.record(client_record("alice", generation=1))
    real_flush = registry.flush

    def controlled_flush(*, force=False, timeout=None):
        result = real_flush(force=force, timeout=timeout)
        flush_finished.set()
        assert allow_close_to_finish.wait(timeout=5.0)
        return result

    monkeypatch.setattr(registry, "flush", controlled_flush)

    def close_registry():
        try:
            registry.close(timeout=5.0)
        except Exception as exc:
            close_errors.append(exc)

    close_thread = threading.Thread(target=close_registry)
    close_thread.start()
    assert flush_finished.wait(timeout=5.0)
    try:
        mutation_was_rejected = False
        try:
            registry.record(client_record("bob", generation=2))
        except RuntimeError:
            mutation_was_rejected = True
    finally:
        allow_close_to_finish.set()
        close_thread.join(timeout=5.0)

    assert not close_thread.is_alive()
    assert close_errors == []
    assert mutation_was_rejected
    assert {item["username"] for item in json.loads(path.read_text(encoding="utf-8"))} == {
        "alice"
    }
