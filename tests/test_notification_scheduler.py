import threading

from picsyncra import sqlite_store
from picsyncra.data_store import SqliteDataStoreAdapter
from picsyncra.notification_scheduler import WakeableDeadlineScheduler
from picsyncra.sqlite_store import SqliteStore


def seed_pending_delivery(store, delivery_id, next_attempt_at):
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_deliveries (
                id, severity, status, primary_channel, message_json,
                created_at, updated_at, next_attempt_at
            ) VALUES (?, 'warning', 'pending', 'smtp', '{}', ?, ?, ?)
            """,
            (
                delivery_id,
                "2026-07-27T10:00:00Z",
                "2026-07-27T10:00:00Z",
                next_attempt_at,
            ),
        )


def test_next_notification_due_at_returns_oldest_pending(tmp_path):
    """Selecting anything but the nearest pending deadline delays durable work."""
    store = SqliteStore(str(tmp_path / "notifications.sqlite"))
    store.initialize()
    seed_pending_delivery(
        store, delivery_id="late", next_attempt_at="2026-07-27T12:00:00Z"
    )
    seed_pending_delivery(
        store, delivery_id="early", next_attempt_at="2026-07-27T11:00:00Z"
    )

    assert store.next_notification_due_at() == "2026-07-27T11:00:00Z"


def test_blank_next_attempt_is_due_immediately_even_with_future_created_at(
    monkeypatch, tmp_path
):
    """Using created_at for a blank deadline can defer already-eligible work."""
    monkeypatch.setattr(
        sqlite_store, "_now_iso", lambda: "2026-07-27T10:30:00.000Z"
    )
    store = SqliteStore(str(tmp_path / "notifications.sqlite"))
    store.initialize()
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_deliveries (
                id, severity, status, primary_channel, message_json,
                created_at, updated_at, next_attempt_at
            ) VALUES (
                'blank', 'warning', 'pending', 'smtp', '{}',
                '2026-07-27T12:00:00.000Z', '2026-07-27T12:00:00.000Z', ''
            )
            """
        )

    assert store.next_notification_due_at() == "2026-07-27T10:30:00.000Z"


def test_sqlite_adapter_delegates_next_notification_due_at():
    """Bypassing the SQLite store would hide its durable worker deadline."""

    class Store:
        def next_notification_due_at(self):
            return "2026-07-27T11:00:00Z"

    adapter = object.__new__(SqliteDataStoreAdapter)
    adapter.store = Store()

    assert adapter.next_notification_due_at() == "2026-07-27T11:00:00Z"


def test_scheduler_latches_wake_after_generation_capture():
    """A wake after state inspection must survive until the waiter is armed."""
    scheduler = WakeableDeadlineScheduler(max_idle_seconds=60)
    generation = scheduler.capture_generation()

    scheduler.wake()

    assert (
        scheduler.wait(
            threading.Event(),
            delay_seconds=60,
            since_generation=generation,
        )
        == "wake"
    )


def test_scheduler_wake_interrupts_wait():
    """A missing generation change would leave newly scheduled work delayed."""
    scheduler = WakeableDeadlineScheduler(max_idle_seconds=60)
    stop = threading.Event()
    result = []
    thread = threading.Thread(
        target=lambda: result.append(scheduler.wait(stop, delay_seconds=60))
    )

    thread.start()
    assert scheduler.wait_until_waiting(timeout=1.0)
    scheduler.wake()
    thread.join(timeout=1.0)

    assert result == ["wake"]


def test_scheduler_stop_interrupts_wait():
    """A shutdown signal must not wait for the scheduler's fallback timeout."""
    scheduler = WakeableDeadlineScheduler(max_idle_seconds=60)
    stop = threading.Event()
    result = []
    thread = threading.Thread(
        target=lambda: result.append(scheduler.wait(stop, delay_seconds=60))
    )

    thread.start()
    assert scheduler.wait_until_waiting(timeout=1.0)
    stop.set()
    scheduler.wake()
    thread.join(timeout=1.0)

    assert result == ["stop"]


def test_scheduler_caps_long_deadline_at_maximum_idle_timeout():
    """A long deadline must still provide a periodic 60-second fallback."""
    condition = FakeCondition()
    scheduler = WakeableDeadlineScheduler(max_idle_seconds=60, condition=condition)

    result = scheduler.wait(threading.Event(), delay_seconds=120)

    assert result == "deadline"
    assert condition.timeouts == [60.0]


class FakeCondition:
    def __init__(self):
        self.timeouts = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def notify_all(self):
        return None

    def wait_for(self, predicate, timeout):
        self.timeouts.append(timeout)
        return predicate()
