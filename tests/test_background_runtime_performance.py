from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

from picsyncra import notification_service
from picsyncra.notification_scheduler import WakeableDeadlineScheduler
from picsyncra.sqlite_store import SqliteStore
from picsyncra.web.active_clients import ActiveClientRegistry


UTC = timezone.utc


class _FakeWorkerClock:
    def __init__(self) -> None:
        self.elapsed_seconds = 0.0
        self._origin = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._origin + timedelta(seconds=self.elapsed_seconds)

    def advance(self, seconds: float) -> None:
        self.elapsed_seconds += seconds


def test_worker_fake_idle_minute_uses_at_most_two_cycles(monkeypatch) -> None:
    """Returning to a tight poll would exceed the idle minute cycle budget."""
    clock = _FakeWorkerClock()
    stop = threading.Event()
    cycle_times = []

    class Scheduler:
        def __init__(self) -> None:
            self.wait_count = 0

        def capture_generation(self) -> int:
            return 0

        def wait(
            self,
            stop_event,
            delay_seconds,
            *,
            since_generation=None,
        ) -> str:
            del since_generation
            self.wait_count += 1
            if self.wait_count == 1:
                clock.advance(min(60.0, float(delay_seconds)))
                return "deadline"
            stop_event.set()
            return "stop"

    scheduler = Scheduler()

    class Store:
        @staticmethod
        def next_notification_due_at() -> str:
            return ""

    class Service:
        store = Store()

        @staticmethod
        def _settings() -> dict[str, str]:
            return {"daily_summary_time": "16:00"}

        @staticmethod
        def process_pending_batch(limit: int) -> int:
            del limit
            cycle_times.append(clock.elapsed_seconds)
            return 0

    monkeypatch.setattr(notification_service, "_WORKER_SCHEDULER", scheduler)
    monkeypatch.setattr(notification_service, "_utc_now", clock.now)
    monkeypatch.setattr(
        notification_service,
        "_WORKER_LAST_ENTRA_MONITOR_AT",
        clock.now(),
    )

    notification_service._worker_loop(Service(), stop)

    idle_cycles = [value for value in cycle_times if value <= 60.0]
    assert len(idle_cycles) <= 2


def _notification_settings() -> dict[str, object]:
    return {
        "primary_channel": "smtp",
        "fallback_enabled": False,
        "entra": {
            "tenant_id": "tenant",
            "client_id": "client",
            "client_secret": "secret",
            "from_address": "alerts@example.com",
        },
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "security": "starttls",
            "username": "sender",
            "password": "secret",
            "from_address": "alerts@example.com",
            "from_name": "PicSyncra",
        },
        "rules": {},
    }


def _delivery_record(delivery_id: str) -> dict[str, object]:
    return {
        "id": delivery_id,
        "incident_id": "",
        "event_id": "",
        "severity": "warning",
        "status": "pending",
        "primary_channel": "smtp",
        "used_channel": "",
        "recipients": ["ops@example.com"],
        "message": {
            "message_id": delivery_id,
            "subject": "wake benchmark",
            "text_body": "durable wake path",
            "html_body": "<p>durable wake path</p>",
        },
        "attempts": [],
        "created_at": "2026-07-27T10:00:00.000Z",
        "updated_at": "2026-07-27T10:00:00.000Z",
        "next_attempt_at": "",
    }


def test_durable_enqueue_wakes_real_worker_before_fallback(monkeypatch, tmp_path) -> None:
    """Dropping SQLite's wake hook would defer a durable delivery for 60 seconds."""
    store = SqliteStore(str(tmp_path / "wake.sqlite"))
    store.initialize()
    scheduler = WakeableDeadlineScheduler(max_idle_seconds=60.0)
    stop = threading.Event()
    any_delivery_processed = threading.Event()
    woken_delivery_processed = threading.Event()
    sent_message_ids = []
    wake_calls = []

    class Transport:
        @staticmethod
        def send(message):
            sent_message_ids.append(message.message_id)
            any_delivery_processed.set()
            if message.message_id == "durable-woken":
                woken_delivery_processed.set()
            return {"status": "sent", "elapsed_ms": 1}

    service = notification_service.NotificationService(
        store=store,
        transport_factory=lambda _channel, _settings: Transport(),
        settings_loader=_notification_settings,
        user_lookup=lambda _username: None,
        event_emitter=lambda **_kwargs: None,
        now=lambda: datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
    )
    real_wake_notification_worker = notification_service.wake_notification_worker

    def observe_real_wake() -> None:
        wake_calls.append(time.perf_counter())
        real_wake_notification_worker()

    monkeypatch.setattr(notification_service, "_WORKER_SCHEDULER", scheduler)
    monkeypatch.setattr(
        notification_service,
        "_WORKER_LAST_ENTRA_MONITOR_AT",
        datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        notification_service,
        "process_due_entra_secret_reminders",
        lambda: None,
    )
    monkeypatch.setattr(
        notification_service,
        "wake_notification_worker",
        observe_real_wake,
    )
    worker = threading.Thread(
        target=notification_service._worker_loop,
        args=(service, stop),
        name="durable-wake-benchmark",
    )
    worker.start()
    try:
        assert scheduler.wait_until_waiting(timeout=1.0)

        original_store_wake = store._wake_notification_worker
        monkeypatch.setattr(store, "_wake_notification_worker", lambda: None)
        store.enqueue_notification_delivery(_delivery_record("durable-unwoken"))
        assert not any_delivery_processed.wait(timeout=0.15)

        monkeypatch.setattr(store, "_wake_notification_worker", original_store_wake)
        enqueue_started = time.perf_counter()
        store.enqueue_notification_delivery(_delivery_record("durable-woken"))
        assert woken_delivery_processed.wait(timeout=0.75)
        enqueue_to_process_seconds = time.perf_counter() - enqueue_started
    finally:
        stop.set()
        scheduler.wake()
        worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert len(wake_calls) == 1
    assert "durable-woken" in sent_message_ids
    assert enqueue_to_process_seconds < 1.0


def test_real_scheduler_stop_interrupts_sixty_second_wait_in_under_one_second() -> None:
    """Shutdown must notify the real condition instead of waiting for fallback."""
    scheduler = WakeableDeadlineScheduler(max_idle_seconds=60.0)
    stop = threading.Event()
    outcomes = []
    waiter = threading.Thread(
        target=lambda: outcomes.append(scheduler.wait(stop, delay_seconds=60.0))
    )
    waiter.start()
    assert scheduler.wait_until_waiting(timeout=1.0)

    started = time.perf_counter()
    stop.set()
    scheduler.wake()
    waiter.join(timeout=1.0)
    stop_elapsed = time.perf_counter() - started

    assert not waiter.is_alive()
    assert outcomes == ["stop"]
    assert stop_elapsed < 1.0


def test_five_real_javascript_pollers_stay_within_active_and_hidden_budgets() -> None:
    """Duplicate timers or unchanged-version refreshes would exceed request budgets."""
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the runtime poller benchmark"
    module_path = (
        Path(__file__).parents[1]
        / "picsyncra"
        / "web"
        / "static"
        / "runtime-status.js"
    )
    script = """
global.window = { PicSyncra: {} };
require(__MODULE__);

class FakeTimer {
  constructor() {
    this.now = 0;
    this.nextId = 0;
    this.pending = new Map();
  }

  setTimeout(callback, delay) {
    const id = ++this.nextId;
    this.pending.set(id, { callback, due: this.now + Number(delay) });
    return id;
  }

  clearTimeout(id) {
    this.pending.delete(id);
  }

  async runUntil(target, inclusive, poller) {
    while (true) {
      const ready = [...this.pending.entries()]
        .filter(([, item]) => inclusive ? item.due <= target : item.due < target)
        .sort((left, right) => left[1].due - right[1].due)[0];
      if (!ready) break;
      const [id, item] = ready;
      this.pending.delete(id);
      this.now = item.due;
      item.callback();
      if (poller.inFlight) await poller.inFlight;
    }
    this.now = target;
  }
}

async function simulateClient() {
  const timerApi = new FakeTimer();
  let hidden = false;
  let visibilityHandler;
  let activeRequests = 0;
  let hiddenRequests = 0;
  let inFlight = 0;
  let maxInFlight = 0;
  let detailRefreshes = 0;
  const poller = new window.PicSyncra.RuntimeStatusPoller({
    fetchStatus: async () => {
      if (hidden) hiddenRequests += 1;
      else activeRequests += 1;
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await Promise.resolve();
      inFlight -= 1;
      return {
        versions: {
          file_index: "index-1",
          process_queue: 7,
          active_clients: 3,
        },
      };
    },
    onVersionChanged: async () => {
      detailRefreshes += 1;
    },
    activeIntervalMs: 5000,
    hiddenIntervalMs: 30000,
    isHidden: () => hidden,
    timerApi,
    visibilityTarget: {
      addEventListener: (_name, callback) => {
        visibilityHandler = callback;
      },
    },
  });

  await poller.start();
  await timerApi.runUntil(60000, false, poller);
  hidden = true;
  visibilityHandler();
  await timerApi.runUntil(120000, true, poller);
  return {
    activeRequests,
    hiddenRequests,
    maxInFlight,
    detailRefreshes,
  };
}

(async () => {
  const clients = [];
  for (let index = 0; index < 5; index += 1) {
    clients.push(await simulateClient());
  }
  process.stdout.write(JSON.stringify(clients));
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
""".replace("__MODULE__", json.dumps(str(module_path)))

    completed = subprocess.run(
        [node, "-e", script],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        # The Node simulation normally completes in a few seconds, but the
        # subprocess startup and its pipe readers can be delayed on a busy CI
        # worker while the complete pytest suite is running.  This is only a
        # watchdog for a genuinely stuck poller; the request-budget assertions
        # below remain the performance contract.
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    clients = json.loads(completed.stdout)
    assert len(clients) == 5
    assert all(client["activeRequests"] <= 12 for client in clients)
    assert all(client["hiddenRequests"] <= 2 for client in clients)
    assert all(client["maxInFlight"] == 1 for client in clients)
    assert all(client["detailRefreshes"] == 0 for client in clients)


def _client_record(index: int, *, sequence: int) -> dict[str, object]:
    return {
        "username": f"user-{index}",
        "client_id": f"browser-{index}",
        "last_seen_epoch": float(index + 1),
        "last_seen": "2026-07-27 10:00:00",
        "method": "GET",
        "path": "/",
        "status_code": 200,
        "remote_address": "127.0.0.1",
        "remote_port": 12345,
        "user_agent": "benchmark",
        "sequence": sequence,
    }


def test_registry_records_one_hundred_updates_while_serialization_is_blocked(
    tmp_path,
) -> None:
    """Holding the registry lock during JSON work would stall all 100 updates."""
    write_started = threading.Event()
    release_write = threading.Event()
    updates_finished = threading.Event()
    serialized_payloads = []
    record_waits = []
    update_errors = []

    def serializer(payload):
        serialized_payloads.append(payload)
        if len(serialized_payloads) == 1:
            write_started.set()
            assert release_write.wait(timeout=5.0)
        return json.dumps(payload)

    path = tmp_path / "active.json"
    registry = ActiveClientRegistry(path, serializer=serializer)

    def record_updates() -> None:
        try:
            for index in range(100):
                started = time.perf_counter()
                registry.record(_client_record(index, sequence=index))
                record_waits.append(time.perf_counter() - started)
        except Exception as exc:  # pragma: no cover - asserted below
            update_errors.append(exc)
        finally:
            updates_finished.set()

    updater = threading.Thread(target=record_updates)
    try:
        registry.record(_client_record(0, sequence=-1))
        assert registry.schedule_flush(force=True)
        assert write_started.wait(timeout=1.0)

        updater.start()
        completed_while_writer_was_blocked = updates_finished.wait(timeout=1.0)
        generation_after_updates = registry.generation
    finally:
        release_write.set()
        updater.join(timeout=5.0)

    try:
        assert registry.flush(force=True, timeout=5.0)
    finally:
        registry.close(timeout=5.0)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert completed_while_writer_was_blocked
    assert update_errors == []
    assert len(record_waits) == 100
    assert max(record_waits) < 0.1
    assert generation_after_updates == 101
    assert {item["username"] for item in persisted} == {
        f"user-{index}" for index in range(100)
    }
    assert len(serialized_payloads) == 2
