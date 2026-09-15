"""Installed OCR components are resolved only from the active managed bundle."""

from __future__ import annotations

import json
from pathlib import Path

from picsyncra.installation.contracts import InstallContext
from picsyncra.installation.ocr_component import (
    resolve_active_ocr_component,
    resolve_ocr_component,
)
from picsyncra.installation.ocr_runtime import (
    StagedInstalledOcrWorker,
    create_installed_ocr_worker,
)


class _FakeRuntime:
    def __init__(self) -> None:
        self.commands: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.limit: int | None = None
        self.started = False

    def start(self) -> None:
        self.started = True

    def submit(self, payload: dict[str, object]) -> None:
        self.commands.append(dict(payload))

    def poll(self) -> list[dict[str, object]]:
        events = list(self.events)
        self.events.clear()
        return events

    def update_limits(self, *, cpu_percent: int) -> None:
        self.limit = cpu_percent

    def stop(self, *, force: bool) -> None:
        self.commands.append({"kind": "stop", "force": force})

    def status(self) -> dict[str, object]:
        return {"alive": True, "exit_code": None}


def _context(tmp_path: Path) -> InstallContext:
    program_root = tmp_path / "program"
    state_root = tmp_path / "state"
    program_root.mkdir()
    state_root.mkdir()
    (program_root / "active.json").write_text(
        json.dumps({"schema": 1, "installation_id": "primary", "release_id": 12}),
        encoding="utf-8",
    )
    return InstallContext(
        installation_id="primary",
        program_root=program_root,
        state_root=state_root,
        config_root=state_root / "config",
        database_path=state_root / "data" / "picsyncra.sqlite",
    )


def test_resolve_ocr_component_accepts_only_the_active_component_for_the_release(
    tmp_path: Path,
) -> None:
    """Catches loading an arbitrary OCR executable from a component directory."""

    context = _context(tmp_path)
    component = context.program_root / "components" / "ocr" / "ocr-12"
    component.mkdir(parents=True)
    (component / "PicSyncra-OCR.exe").write_bytes(b"runtime")
    marker = component.parent / "active.json"
    marker.write_text(
        json.dumps(
            {
                "schema": 1,
                "release_id": 12,
                "component_id": "ocr-12",
                "build_id": "release-12",
                "protocol": 1,
            }
        ),
        encoding="utf-8",
    )

    assert resolve_ocr_component(context) == component
    active = resolve_active_ocr_component(context)
    assert active is not None
    assert active.directory == component
    assert active.build_id == "release-12"
    assert active.component_id == "ocr-12"


def test_resolve_ocr_component_rejects_a_marker_for_another_release(tmp_path: Path) -> None:
    """Catches mixing an OCR runtime with an incompatible active build."""

    context = _context(tmp_path)
    component_root = context.program_root / "components" / "ocr"
    component = component_root / "ocr-11"
    component.mkdir(parents=True)
    (component / "PicSyncra-OCR.exe").write_bytes(b"runtime")
    (component_root / "active.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "release_id": 11,
                "component_id": "ocr-11",
                "build_id": "release-11",
                "protocol": 1,
            }
        ),
        encoding="utf-8",
    )

    assert resolve_ocr_component(context) is None


def test_staged_worker_copies_the_source_into_a_run_directory_before_submission(
    tmp_path: Path,
) -> None:
    """Catches giving the component a direct portable or network source path."""

    source = tmp_path / "portable" / "image.png"
    source.parent.mkdir()
    source.write_bytes(b"image")
    runtime = _FakeRuntime()
    worker = StagedInstalledOcrWorker(
        runtime=runtime,
        staging_root=tmp_path / "state" / "cache" / "ocr-jobs",
    )

    worker.start()
    worker.submit(
        run_id="run-1",
        path=str(source),
        profile_ids=["fast"],
        resource_settings={"ignored": True},
    )

    command = runtime.commands[0]
    staged_path = Path(str(command["path"]))
    assert runtime.started is True
    assert staged_path.read_bytes() == b"image"
    assert staged_path.parent == tmp_path / "state" / "cache" / "ocr-jobs" / "run-1"
    assert command["work_root"] == str(staged_path.parent)
    assert str(source) != str(staged_path)


def test_staged_worker_deletes_only_its_completed_run_directory(tmp_path: Path) -> None:
    """Catches cache cleanup deleting data outside the controlled OCR staging root."""

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    runtime = _FakeRuntime()
    staging_root = tmp_path / "state" / "cache" / "ocr-jobs"
    worker = StagedInstalledOcrWorker(runtime=runtime, staging_root=staging_root)
    worker.submit(
        run_id="run-1", path=str(source), profile_ids=["fast"], resource_settings=None
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime.events.append({"kind": "result", "run_id": "run-1", "diagnostics": {}})

    assert worker.poll_events() == [
        {"kind": "result", "run_id": "run-1", "diagnostics": {}}
    ]
    assert not (staging_root / "run-1").exists()
    assert outside.exists()


def test_installed_worker_factory_uses_only_the_verified_component_and_state_root(
    tmp_path: Path,
) -> None:
    """Catches installed WEB launching OCR from an unregistered program path."""

    context = _context(tmp_path)
    component = context.program_root / "components" / "ocr" / "ocr-12"
    component.mkdir(parents=True)
    (component / "PicSyncra-OCR.exe").write_bytes(b"runtime")
    (component.parent / "active.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "release_id": 12,
                "component_id": "ocr-12",
                "build_id": "release-12",
                "protocol": 1,
            }
        ),
        encoding="utf-8",
    )

    worker = create_installed_ocr_worker(context)

    assert isinstance(worker, StagedInstalledOcrWorker)
