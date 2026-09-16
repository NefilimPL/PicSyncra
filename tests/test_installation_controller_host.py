from pathlib import Path

import pytest

from picsyncra.installation.contracts import InstallContext, OperationRequest


def _context(tmp_path: Path) -> InstallContext:
    program = tmp_path / "program"
    state = tmp_path / "state"
    (program / "versions" / "41" / "web").mkdir(parents=True)
    state.mkdir()
    (program / "versions" / "41" / "web" / "PicSyncra-WEB.exe").write_bytes(b"web")
    (program / "active.json").write_text(
        '{"schema":1,"installation_id":"site-1","release_id":41}', encoding="utf-8"
    )
    return InstallContext("site-1", program, state, state / "config", state / "data.sqlite")


def test_controller_host_resolves_only_the_web_executable_in_the_active_bundle(tmp_path: Path) -> None:
    from picsyncra.installation.controller_host import active_web_executable

    assert active_web_executable(_context(tmp_path)) == tmp_path / "program" / "versions" / "41" / "web" / "PicSyncra-WEB.exe"


def test_controller_host_rejects_a_missing_or_linked_active_web_executable(tmp_path: Path) -> None:
    from picsyncra.installation.controller_host import ControllerHostError, active_web_executable

    context = _context(tmp_path)
    (context.program_root / "versions" / "41" / "web" / "PicSyncra-WEB.exe").unlink()
    with pytest.raises(ControllerHostError, match="executable"):
        active_web_executable(context)


def test_controller_host_starts_and_stops_only_its_owned_web_process(tmp_path: Path) -> None:
    from picsyncra.installation.controller_host import ActiveBackendSupervisor

    created: list[FakeProcess] = []
    jobs: list[FakeJob] = []

    def create_process(command: list[str]) -> "FakeProcess":
        assert command[:2] == [
            str(tmp_path / "program" / "versions" / "41" / "web" / "PicSyncra-WEB.exe"),
            "--service-run",
        ]
        process = FakeProcess()
        created.append(process)
        return process

    def create_job() -> "FakeJob":
        job = FakeJob()
        jobs.append(job)
        return job

    supervisor = ActiveBackendSupervisor(
        _context(tmp_path),
        process_factory=create_process,
        port_in_use=lambda: False,
        job_factory=create_job,
    )

    supervisor.start_backend()
    assert supervisor.snapshot() == {"backend_running": True, "autostart": True}
    assert supervisor.stop_backend(force=False) is True
    assert created[0].terminated is True
    assert supervisor.snapshot()["backend_running"] is False
    assert supervisor._job is None
    assert jobs[0].assigned is created[0]
    assert jobs[0].closed is True


def test_controller_host_never_stops_a_foreign_listener(tmp_path: Path) -> None:
    from picsyncra.installation.controller_host import ActiveBackendSupervisor

    supervisor = ActiveBackendSupervisor(
        _context(tmp_path),
        process_factory=lambda _command: pytest.fail("must not launch over a foreign listener"),
        port_in_use=lambda: True,
    )

    assert supervisor.listener_owner(8010) == "foreign-listener"
    assert supervisor.stop_backend(force=True) is False


def test_controller_host_defers_restart_until_the_pipe_can_reply() -> None:
    from picsyncra.installation.controller_host import DeferredRestartController

    work: list[object] = []
    delegate = FakeController()
    controller = DeferredRestartController(delegate, schedule=work.append)

    assert controller.restart_backend() is True
    assert controller.restart_backend() is False
    assert delegate.restart_calls == 0

    work.pop()()
    assert delegate.restart_calls == 1
    assert controller.restart_backend() is True


def test_deferred_restart_reports_the_actual_restart_result_to_handoff_finalizer() -> None:
    from picsyncra.installation.controller_host import DeferredRestartController

    work: list[object] = []
    completed: list[bool] = []
    delegate = FakeController()
    controller = DeferredRestartController(
        delegate, schedule=work.append, complete_restart=completed.append
    )

    assert controller.restart_backend() is True
    work.pop()()

    assert completed == [True]


def test_controller_commits_handoff_only_after_a_ready_backend(tmp_path: Path) -> None:
    from picsyncra.installation.controller_host import _complete_restart_handoff
    from picsyncra.installation.journal import OperationJournal
    from picsyncra.installation.restart_handoff import create_restart_handoff, read_restart_handoff
    from picsyncra.installation.session_epoch import read_session_epoch

    value = _context(tmp_path)
    journal = OperationJournal(value.state_root / "operations.json")
    operation = journal.submit(OperationRequest("restart-1", "restart", None, None, False), actor_id="admin")
    journal.transition(operation.operation_id, "draining")
    journal.transition(operation.operation_id, "stopping")
    journal.transition(operation.operation_id, "installing")
    journal.transition(operation.operation_id, "validating")
    create_restart_handoff(value, operation_id=operation.operation_id, previous_release=41, target_release=41, previous_ocr_marker=None)

    _complete_restart_handoff(value, FakeController(), True, readiness_check=lambda _controller: True)

    assert OperationJournal(value.state_root / "operations.json").read(operation.operation_id).state == "committed"
    assert read_session_epoch(value) == 1
    assert read_restart_handoff(value) is None


def test_controller_rolls_back_handoff_when_new_backend_never_becomes_ready(tmp_path: Path) -> None:
    from picsyncra.installation.controller_host import _complete_restart_handoff
    from picsyncra.installation.journal import OperationJournal
    from picsyncra.installation.restart_handoff import create_restart_handoff, read_restart_handoff
    from picsyncra.installation.update_helper import activate_release, read_active_release

    value = _context(tmp_path)
    (value.program_root / "versions" / "42").mkdir()
    activate_release(value, 42)
    journal = OperationJournal(value.state_root / "operations.json")
    operation = journal.submit(OperationRequest("update-1", "update", 42, None, False), actor_id="admin")
    journal.transition(operation.operation_id, "draining")
    journal.transition(operation.operation_id, "backing_up")
    journal.transition(operation.operation_id, "installing")
    journal.transition(operation.operation_id, "validating")
    create_restart_handoff(value, operation_id=operation.operation_id, previous_release=41, target_release=42, previous_ocr_marker=None)
    checks = iter((False, True))

    _complete_restart_handoff(value, FakeController(), True, readiness_check=lambda _controller: next(checks))

    assert OperationJournal(value.state_root / "operations.json").read(operation.operation_id).state == "rolled_back"
    assert read_active_release(value) == 41
    assert read_restart_handoff(value) is None


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float) -> int:
        assert timeout > 0
        if self.returncode is None:
            raise TimeoutError
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1


class FakeJob:
    def __init__(self) -> None:
        self.assigned: FakeProcess | None = None
        self.closed = False

    def assign(self, process: FakeProcess) -> None:
        self.assigned = process

    def close(self) -> None:
        self.closed = True


class FakeController:
    def __init__(self) -> None:
        self.restart_calls = 0

    def restart_backend(self) -> bool:
        self.restart_calls += 1
        return True

    def start_backend(self) -> None:
        pass

    def stop_backend(self, *, force: bool) -> bool:
        return force

    def set_autostart(self, enabled: bool) -> bool:
        return enabled

    def snapshot(self) -> dict[str, bool]:
        return {"backend_running": True, "autostart": True}
