"""Presence for maintenance decisions is session-based but counts other people."""

from __future__ import annotations

from picsyncra.installation.maintenance import MaintenanceCoordinator, MaintenanceGate
from picsyncra.installation.presence import PresenceRegistry


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_heartbeat_expiry_uses_sixty_second_ttl() -> None:
    clock = Clock()
    presence = PresenceRegistry(clock=clock, ttl_seconds=60)
    presence.heartbeat("user-a", "tab-1")
    clock.now = 59.9
    assert presence.other_user_count("admin") == 1
    clock.now = 60.0
    assert presence.other_user_count("admin") == 0


def test_multiple_tabs_of_initiator_do_not_delay_maintenance() -> None:
    presence = PresenceRegistry(clock=Clock())
    presence.heartbeat("admin", "tab-1")
    presence.heartbeat("admin", "tab-2")
    presence.heartbeat("other", "tab-3")
    assert presence.other_user_count("admin") == 1


def test_coordinator_starts_immediately_when_no_other_user_or_task_exists() -> None:
    clock = Clock()
    coordinator = MaintenanceCoordinator(MaintenanceGate(), PresenceRegistry(clock=clock), clock=clock)
    coordinator.begin("operation-1", initiator_id="admin")
    assert coordinator.advance()["state"] == "ready"
    assert coordinator.snapshot()["deadline_utc"] is None


def test_coordinator_waits_for_drain_then_counts_down_exactly_two_minutes() -> None:
    clock = Clock()
    gate = MaintenanceGate()
    presence = PresenceRegistry(clock=clock)
    task = gate.try_admit("upload")
    assert task is not None
    presence.heartbeat("other", "tab-1")
    coordinator = MaintenanceCoordinator(gate, presence, clock=clock)
    coordinator.begin("operation-1", initiator_id="admin")
    assert coordinator.advance()["state"] == "draining"
    task.finish()
    assert coordinator.advance()["state"] == "countdown"
    assert coordinator.snapshot()["deadline_utc"] == 120.0
    clock.now = 119.9
    assert coordinator.advance()["state"] == "countdown"
    clock.now = 120.0
    assert coordinator.advance()["state"] == "ready"


def test_countdown_is_not_shortened_when_the_last_user_leaves() -> None:
    clock = Clock()
    presence = PresenceRegistry(clock=clock)
    presence.heartbeat("other", "tab-1")
    coordinator = MaintenanceCoordinator(MaintenanceGate(), presence, clock=clock)
    coordinator.begin("operation-1", initiator_id="admin")
    assert coordinator.advance()["state"] == "countdown"
    presence.remove("other", "tab-1")
    clock.now = 1
    assert coordinator.advance()["state"] == "countdown"


def test_force_stays_in_draining_until_cancelled_task_releases_its_lease() -> None:
    clock = Clock()
    gate = MaintenanceGate()
    cancelled = []
    lease = gate.try_admit("ftp", on_cancel=lambda: cancelled.append(True))
    assert lease is not None
    coordinator = MaintenanceCoordinator(gate, PresenceRegistry(clock=clock), clock=clock)
    coordinator.begin("operation-1", initiator_id="admin")
    assert coordinator.force()["force_requested"] is True
    assert cancelled == [True]
    assert coordinator.advance()["state"] == "draining"
    lease.finish()
    assert coordinator.advance()["state"] == "ready"
