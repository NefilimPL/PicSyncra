"""Admission policy for ordinary mutating WEB requests during maintenance."""

from __future__ import annotations

from ..installation.maintenance import MaintenanceGate, MaintenanceLease


class MaintenanceRequestAdmission:
    """Make in-flight writes visible to installed update draining.

    Installed-operation routes own the maintenance state machine themselves, so
    they remain callable to report progress and request a force cancellation.
    """

    _READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, gate: MaintenanceGate) -> None:
        self._gate = gate

    def requires_admission(self, method: str, path: str) -> bool:
        # These endpoints own staging/running leases in ProcessQueueService.
        # A synchronous request can wait for a queued job across maintenance;
        # counting that wait as a writer would deadlock the drain.
        return (method.upper() not in self._READ_METHODS
                and not path.startswith("/api/installation/")
                and path not in {'/api/process', '/api/process/background'})

    def admit(self, method: str, path: str) -> MaintenanceLease | None:
        if not self.requires_admission(method, path):
            return None
        return self._gate.try_admit("http_write")


__all__ = ["MaintenanceRequestAdmission"]
