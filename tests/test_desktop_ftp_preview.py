from __future__ import annotations

from dataclasses import dataclass
import threading

import pytest

from picsyncra.desktop_ftp_preview import DesktopFtpPreviewController


@dataclass(frozen=True)
class PreviewResult:
    ean: str
    files: tuple[str, ...]


def preview_result(ean: str) -> PreviewResult:
    return PreviewResult(ean=ean, files=(f"{ean}_01.jpg",))


class ControlledDownloader:
    def __init__(self) -> None:
        self.requests: dict[int, tuple[str, object, object]] = {}

    def __call__(self, request_id, ean, cancel_event, complete) -> None:
        self.requests[request_id] = (ean, cancel_event, complete)

    def finish(self, request_id: int, result: PreviewResult) -> None:
        self.requests[request_id][2](result)


class FakeTempManager:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class TrackingTempManager(FakeTempManager):
    def __init__(self) -> None:
        super().__init__()
        self.created_paths: list[str] = []
        self.released_paths: list[str] = []
        self.creation_started = threading.Event()
        self.allow_creation = threading.Event()
        self.block_creation = False

    def create_request_dir(self, request_id: int) -> str:
        path = f"temp/{request_id}"
        self.created_paths.append(path)
        if self.block_creation:
            self.creation_started.set()
            self.allow_creation.wait(timeout=1)
        return path

    def release(self, path: str) -> None:
        self.released_paths.append(path)

    def close(self) -> None:
        super().close()
        self.released_paths.extend(
            path for path in self.created_paths if path not in self.released_paths
        )


def test_preview_controller_publishes_only_latest_request() -> None:
    scheduled = []
    results = []
    errors = []
    downloader = ControlledDownloader()
    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=FakeTempManager(),
        schedule=lambda: scheduled.append(None),
    )

    first = controller.request("5901", on_success=results.append, on_error=errors.append)
    second = controller.request("5902", on_success=results.append, on_error=errors.append)
    downloader.finish(first, preview_result("5901"))
    downloader.finish(second, preview_result("5902"))
    controller.drain()

    assert [item.ean for item in results] == ["5902"]
    assert errors == []


def test_preview_controller_requires_and_forwards_a_string_ean() -> None:
    received_eans = []

    def downloader(_request_id, ean, _cancel_event, _complete) -> None:
        received_eans.append(ean)

    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=FakeTempManager(),
        schedule=lambda: None,
    )

    controller.request("5901", on_success=lambda _result: None, on_error=lambda _error: None)

    assert received_eans == ["5901"]
    with pytest.raises(TypeError, match="ean must be a string"):
        controller.request(
            {"ean": "5902"},
            on_success=lambda _result: None,
            on_error=lambda _error: None,
        )


def test_preview_controller_close_cancels_request_and_closes_temp_manager_once() -> None:
    downloader = ControlledDownloader()
    temp_manager = FakeTempManager()
    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=temp_manager,
        schedule=lambda: None,
    )

    request_id = controller.request("5901", on_success=lambda _result: None, on_error=lambda _error: None)
    controller.close()
    controller.close()

    assert downloader.requests[request_id][1].is_set()
    assert temp_manager.close_calls == 1


def test_preview_controller_schedules_stale_request_cleanup() -> None:
    scheduled = []
    discarded = []
    downloader = ControlledDownloader()
    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=FakeTempManager(),
        schedule=lambda: scheduled.append(None),
    )

    first = controller.request(
        "5901",
        on_success=lambda _result: None,
        on_error=lambda _error: None,
        on_discard=discarded.append,
    )
    controller.request(
        "5902",
        on_success=lambda _result: None,
        on_error=lambda _error: None,
    )
    downloader.finish(first, preview_result("5901"))
    controller.drain()

    assert [item.ean for item in discarded] == ["5901"]


def test_worker_completion_never_invokes_ui_scheduler() -> None:
    scheduled_from_threads = []
    worker_finished = threading.Event()
    callbacks_run_on = []

    def downloader(_request_id, _ean, _cancel_event, complete) -> None:
        def run() -> None:
            complete(preview_result("5901"))
            worker_finished.set()

        threading.Thread(target=run, daemon=True).start()

    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=FakeTempManager(),
        schedule=lambda: scheduled_from_threads.append(threading.get_ident()),
    )
    controller.request(
        "5901",
        on_success=lambda _result: callbacks_run_on.append(threading.get_ident()),
        on_error=lambda _error: None,
    )
    assert worker_finished.wait(timeout=1)

    assert scheduled_from_threads == [threading.get_ident()]
    controller.drain()
    assert callbacks_run_on == [threading.get_ident()]


def test_drain_rejects_non_ui_thread() -> None:
    downloader = ControlledDownloader()
    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=FakeTempManager(),
        schedule=lambda: None,
    )
    request_id = controller.request(
        "5901",
        on_success=lambda _result: None,
        on_error=lambda _error: None,
    )
    downloader.finish(request_id, preview_result("5901"))
    failures = []

    worker = threading.Thread(
        target=lambda: failures.append(
            _drain_failure(controller)
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=1)

    assert failures == [RuntimeError]


def _drain_failure(controller) -> type[BaseException] | None:
    try:
        controller.drain()
    except BaseException as exc:
        return type(exc)
    return None


def test_close_releases_created_temp_directory_once_and_prevents_late_creation() -> None:
    downloader = ControlledDownloader()
    temp_manager = TrackingTempManager()
    controller = DesktopFtpPreviewController(
        downloader=downloader,
        temp_manager=temp_manager,
        schedule=lambda: None,
    )
    temp_manager.block_creation = True

    request_id = controller.request(
        "5901",
        on_success=lambda _result: None,
        on_error=lambda _error: None,
    )
    cancel_event = downloader.requests[request_id][1]
    created = []
    worker = threading.Thread(
        target=lambda: created.append(
            controller.create_request_dir(request_id, cancel_event)
        ),
        daemon=True,
    )
    worker.start()
    assert temp_manager.creation_started.wait(timeout=1)
    closer = threading.Thread(target=controller.close, daemon=True)
    closer.start()
    temp_manager.allow_creation.set()
    worker.join(timeout=1)
    closer.join(timeout=1)

    assert not worker.is_alive()
    assert not closer.is_alive()
    assert created == ["temp/1"]
    assert temp_manager.released_paths == ["temp/1"]
    assert controller.create_request_dir(request_id, cancel_event) is None
    assert temp_manager.released_paths == ["temp/1"]
