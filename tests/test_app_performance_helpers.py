"""Unit tests for lightweight GUI performance helpers."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    from picsyncra import app as app_module
    from picsyncra.app import App, SLOT_GRID_COLUMNS, THUMBNAIL_MEMORY_ROWS
    from picsyncra.common import d, n
    from picsyncra.desktop_data_loader import DesktopDataSnapshot
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local test env
    App = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None
    THUMBNAIL_QUEUE_MAXSIZE = getattr(app_module, "THUMBNAIL_QUEUE_MAXSIZE", None)


class _ComboboxStub:
    def __init__(self) -> None:
        self.assignments: list[tuple[str, tuple[str, ...]]] = []

    def __setitem__(self, key: str, value) -> None:
        self.assignments.append((key, tuple(value)))
        setattr(self, key, tuple(value))


class _VariableStub:
    def __init__(self, value=None, **_kwargs) -> None:
        self.value = value if value is not None else ""

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value

    def trace_add(self, _mode: str, _callback) -> None:
        return None


class _ButtonStub:
    def __init__(self, *, text="", command=None, state="normal") -> None:
        self.text = text
        self.command = command
        self.state = state

    def configure(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def invoke(self) -> None:
        if self.command is not None:
            self.command()


class _LoaderCancelStub:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class _FtpTempManagerStub:
    def __init__(self, *_args, **_kwargs) -> None:
        self.close_calls = 0
        self.released_paths: list[str] = []

    def release(self, path: str) -> bool:
        self.released_paths.append(path)
        return True

    def close(self) -> None:
        self.close_calls += 1


class _FtpPreviewControllerStub:
    def __init__(self, *_args, **_kwargs) -> None:
        self.cancel_calls = 0
        self.close_calls = 0

    def cancel_current(self) -> None:
        self.cancel_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _ProductActionRouteHarness:
    _desktop_product_actions_available = App._desktop_product_actions_available

    def __init__(self, *, data_loading: bool, desktop_data_ready: bool) -> None:
        self.data_loading = data_loading
        self.desktop_data_ready = desktop_data_ready
        self.is_processing = False
        self.var_ean = _VariableStub("590")
        self.var_product_id = _VariableStub("")
        self.entries = {"590": {"NAZWA": "ALFA"}}
        self.entries_by_id = {}
        self.combo_name = object()
        self.loaded_records = []
        self.new_entry_modes = []
        self.focused_widgets = []

    def _load_entry_record(self, record) -> None:
        self.loaded_records.append(record)

    def _activate_new_entry_mode(self, keep_values=True) -> None:
        self.new_entry_modes.append(keep_values)

    def _focus_widget(self, widget) -> None:
        self.focused_widgets.append(widget)


class _LookupCancellationHarness:
    _cancel_existing_lookup = App._cancel_existing_lookup

    def __init__(self) -> None:
        self._load_existing_after_id = app_module.I
        self._existing_lookup_cancel_event = threading.Event()
        self._ftp_preview_temp_dir = "C:/temp/managed-preview"
        self._ftp_temp_manager = _FtpTempManagerStub()
        self._load_existing_request_id = 7
        self._existing_lookup_lock = threading.Lock()
        self._retry_existing_lookup = True
        self._existing_lookup_running = True
        self._existing_lookup_active_request_id = 7
        self._existing_lookup_busy = True
        self.slot_activity_calls: list[bool] = []
        self.busy_calls: list[tuple[str, bool]] = []

    def _update_all_slot_activity(self, *, active: bool) -> None:
        self.slot_activity_calls.append(active)

    def _set_busy_state(self, message: str, *, active: bool) -> None:
        self.busy_calls.append((message, active))


class _BlockedCommitHarness:
    _desktop_product_actions_available = App._desktop_product_actions_available

    def __init__(self, *, data_loading: bool, desktop_data_ready: bool) -> None:
        self.data_loading = data_loading
        self.desktop_data_ready = desktop_data_ready
        self.var_name = _VariableStub("")
        self.var_type = _VariableStub("")
        self.var_model = _VariableStub("")
        self.var_color1 = _VariableStub("")
        self.var_color2 = _VariableStub("")
        self.var_color3 = _VariableStub("")
        self.var_extra = _VariableStub("")
        self.route_calls = []

    def _cancel_existing_lookup(self) -> None:
        self.route_calls.append("cancel_lookup")

    def _normalize_color_vars(self):
        self.route_calls.append("normalize_colors")
        return "", "", ""

    def _commit_matches_snapshot(self, *_args) -> bool:
        self.route_calls.append("commit_snapshot")
        return True

    def _normalize_entry_part(self, value, **_kwargs):
        return value

    def _missing_required_product_fields(self):
        self.route_calls.append("submit_validation")
        return ["name"]

    def _required_product_fields_message(self, message):
        return message

    def after_idle(self, callback) -> None:
        callback()

    def _should_skip_ean_focus_out_warning(self) -> bool:
        return False

    def _warn_about_ean_conflict(self, **_kwargs) -> None:
        self.route_calls.append("ean_conflict")


class _StyleStub:
    def theme_use(self, _theme: str) -> None:
        return None

    def configure(self, *_args, **_kwargs) -> None:
        return None


class _FileIndexStub:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def load_cache(self) -> bool:
        return False


class _HeadlessStartupApp(App):
    """App constructor harness with Tk widgets replaced at the display boundary."""

    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.handled_errors: list[tuple[object, object, object, str]] = []
        super().__init__()

    def title(self, _value: str) -> None:
        return None

    def geometry(self, _value: str) -> None:
        return None

    def minsize(self, _width: int, _height: int) -> None:
        return None

    def bind_class(self, *_args) -> None:
        return None

    def protocol(self, *_args) -> None:
        return None

    def after(self, delay_ms: int, callback):
        self.after_calls.append((delay_ms, callback))
        return f"job-{len(self.after_calls)}"

    def after_cancel(self, _job_id: str) -> None:
        return None

    def _configure_styles(self) -> None:
        return None

    def _load_slot_config(self) -> None:
        self.slot_definitions = []

    def _build_form(self) -> None:
        self.main_view = object()
        self.btn_submit = _ButtonStub(text="submit")
        self.btn_search_entry = _ButtonStub(
            text="search",
            command=self._search_current_entry,
        )
        self.btn_new_search = _ButtonStub(text="new")
        self.btn_edit_lists = _ButtonStub(text="lists")
        self.combo_name = _ComboboxStub()
        self.combo_type = _ComboboxStub()
        self.combo_model = _ComboboxStub()
        self.combo_color1 = _ComboboxStub()
        self.combo_color2 = _ComboboxStub()
        self.combo_color3 = _ComboboxStub()
        self.combo_extra = _ComboboxStub()

    def _build_slots(self) -> None:
        self.slots = []

    def _refresh_name_values_from_index(self) -> None:
        return None

    def _refresh_commit_snapshot(self) -> None:
        return None

    def _update_dashboard_summary(self) -> None:
        return None

    def _thumbnail_worker_loop(self) -> None:
        return None

    def _install_exception_handlers(self) -> None:
        return None

    def _handle_exception(self, exc_type, exc, tb, context="") -> None:
        self.handled_errors.append((exc_type, exc, tb, context))

    def run_ui_callbacks(self) -> None:
        callbacks = [
            callback
            for _delay, callback in self.after_calls
            if getattr(callback, "__name__", "") == "_deliver_pending_result"
        ]
        self.after_calls = [
            item
            for item in self.after_calls
            if getattr(item[1], "__name__", "") != "_deliver_pending_result"
        ]
        for callback in callbacks:
            callback()


@contextmanager
def _headless_app_environment():
    with ExitStack() as stack:
        image_root = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.object(app_module, "l", image_root))
        stack.enter_context(patch.object(app_module.BU.Tk, "__init__", return_value=None))
        stack.enter_context(patch.object(app_module.C, "Style", return_value=_StyleStub()))
        stack.enter_context(patch.object(app_module.F, "StringVar", _VariableStub))
        stack.enter_context(patch.object(app_module.F, "BooleanVar", _VariableStub))
        stack.enter_context(patch.object(app_module.F, "IntVar", _VariableStub))
        stack.enter_context(patch.object(app_module, "LocalFileIndex", _FileIndexStub))
        stack.enter_context(patch.object(app_module.data_store, "get_active_store", return_value=object()))
        stack.enter_context(patch.object(app_module, "prepare_excel_lists", return_value={}))
        stack.enter_context(patch.object(app_module, "set_app"))
        stack.enter_context(
            patch.object(
                app_module,
                "FtpTempManager",
                side_effect=_FtpTempManagerStub,
                create=True,
            )
        )
        yield


class _CanvasStub:
    def __init__(self) -> None:
        self.scroll_calls: list[tuple[int, str]] = []
        self.moveto_calls: list[float] = []
        self.content_height = 1000.0
        self.viewport_height = 200.0
        self.fraction = 0.0

    def bbox(self, _tag: str):
        return (0, 0, 100, int(self.content_height))

    def winfo_height(self) -> int:
        return int(self.viewport_height)

    def yview(self):
        return (
            self.fraction,
            min(1.0, self.fraction + (self.viewport_height / self.content_height)),
        )

    def yview_moveto(self, fraction: float) -> None:
        max_fraction = (self.content_height - self.viewport_height) / self.content_height
        self.fraction = max(0.0, min(max_fraction, float(fraction)))
        self.moveto_calls.append(self.fraction)

    def yview_scroll(self, steps: int, unit: str) -> None:
        self.scroll_calls.append((steps, unit))

    def update_idletasks(self) -> None:
        return None


class _ListHarness:
    _normalize_list_value = App._normalize_list_value if App is not None else None
    _invalidate_list_filter_cache = (
        App._invalidate_list_filter_cache if App is not None else None
    )
    _refresh_list_value_set = App._refresh_list_value_set if App is not None else None

    def __init__(self) -> None:
        self.lists = {
            n: ["ALFA"],
            d: ["NO_LED"],
        }
        self._list_filter_cache = {}


class _ScrollHarness:
    _get_slots_scroll_metrics = (
        App._get_slots_scroll_metrics if App is not None else None
    )
    _get_slots_scroll_offset = App._get_slots_scroll_offset if App is not None else None
    _set_slots_scroll_offset = App._set_slots_scroll_offset if App is not None else None
    _mark_slots_scroll_active = (
        App._mark_slots_scroll_active if App is not None else None
    )
    _flush_slots_scroll = App._flush_slots_scroll if App is not None else None
    _scroll_slots_by_pixels = App._scroll_slots_by_pixels if App is not None else None
    _finish_slots_scroll = App._finish_slots_scroll if App is not None else None

    def __init__(self) -> None:
        self._slots_canvas = _CanvasStub()
        self._slots_scroll_job = None
        self._slots_scroll_end_job = None
        self._slots_scroll_target_px = 0.0
        self._slots_scroll_active = False
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled: list[str] = []
        self.refreshes = 0

    def after(self, delay_ms: int, callback):
        self.after_calls.append((delay_ms, callback))
        return f"job-{len(self.after_calls)}"

    def after_cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)

    def _schedule_slots_canvas_refresh(self) -> None:
        self.refreshes += 1

    def _prefetch_visible_slot_thumbnails(self) -> None:
        return None


class _ThumbnailHarness:
    _next_thumbnail_token = App._next_thumbnail_token if App is not None else None

    def __init__(self, maxsize: int = 0) -> None:
        self._thumb_request_queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._thumb_result_queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._thumb_request_seq = 0
        self._thumb_pending_paths: dict[int, tuple[str, bool]] = {}
        self._thumb_pending_tokens: dict[int, int] = {}
        self._thumb_tokens: dict[int, int] = {}
        self._thumb_pending_lock = threading.Lock()
        self._slots_scroll_active = False
        self._thumb_poll_job = None
        self.slots = [{}, {}, {"preview_path": "new.png"}]
        self.preview_updates: list[tuple[int, str, object, bool]] = []

    def _is_slot_content_fit_enabled(self, _idx: int) -> bool:
        return False

    def _get_cached_thumbnail(self, _path: str, _content_fit: bool):
        return None, None

    def _set_slot_preview(
        self, idx: int, path: str, thumb: object, *, content_fit: bool
    ) -> None:
        self.preview_updates.append((idx, path, thumb, content_fit))

    def _load_slot_thumbnail(self, path: str, *, content_fit: bool):
        return (path, content_fit)

    def _get_slot_preview_path(self, slot: dict[str, object]) -> str:
        return str(slot.get("preview_path") or "")

    def winfo_exists(self) -> bool:
        return False


class _ObservedLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.waiter_started = threading.Event()

    def __enter__(self):
        if self._lock.locked():
            self.waiter_started.set()
        self._lock.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self._lock.release()


class _PublishedBeforeReturnQueue(queue.Queue):
    def __init__(self) -> None:
        super().__init__(maxsize=1)
        self.published = threading.Event()
        self.allow_return = threading.Event()

    def put_nowait(self, item) -> None:
        super().put_nowait(item)
        self.published.set()
        self.allow_return.wait(timeout=2)


@unittest.skipIf(App is None, f"App import unavailable: {APP_IMPORT_ERROR}")
class AppPerformanceHelperTests(unittest.TestCase):
    def test_desktop_start_skips_refresh_when_file_index_cache_is_fresh(self) -> None:
        class Index:
            def __init__(self) -> None:
                self.force_values: list[bool] = []

            def refresh_if_stale(self, *, force: bool = False) -> bool:
                self.force_values.append(force)
                return False

            def get_status(self) -> dict[str, str]:
                return {"state": "cached"}

        class Harness:
            def __init__(self) -> None:
                self._local_file_index_enabled = True
                self._file_index = Index()
                self.statuses: list[dict[str, str]] = []

            def _on_file_index_status_change(self, status: dict[str, str]) -> None:
                self.statuses.append(status)

        harness = Harness()

        started = App._start_file_index_refresh(harness)

        self.assertFalse(started)
        self.assertEqual(harness._file_index.force_values, [False])
        self.assertEqual(harness.statuses, [{"state": "cached"}])

    def test_app_builds_main_view_before_desktop_data_is_ready(self) -> None:
        load_started = threading.Event()
        release_load = threading.Event()
        record = {"EAN": "590", "NAZWA": "ALFA", "ID PRODUKTU": "P-1"}
        snapshot = DesktopDataSnapshot(
            lists={
                "NAZWY": ["ALFA"],
                "TYPY": [],
                "MODELE": [],
                "KOLORY": [],
                "DODATKI": [],
                "ENTRIES": {"590": record},
                "__ENTRY_RECORDS__": [record],
            },
            entries=(record,),
        )

        def slow_load():
            load_started.set()
            release_load.wait(timeout=2.0)
            return snapshot

        with _headless_app_environment(), patch.object(
            app_module,
            "load_desktop_data",
            slow_load,
            create=True,
        ):
            app = _HeadlessStartupApp()
            try:
                self.assertTrue(load_started.wait(timeout=1.0))
                self.assertIsNotNone(app.main_view)
                self.assertTrue(app.data_loading)
                self.assertEqual(app.btn_submit.state, "disabled")
                self.assertEqual(app.btn_search_entry.state, "disabled")
                self.assertEqual(app.btn_new_search.state, "disabled")
                self.assertEqual(app.btn_edit_lists.state, "disabled")
            finally:
                release_load.set()

            app._desktop_data_loader.join_for_test(timeout=1.0)
            self.assertTrue(app.data_loading)
            app.run_ui_callbacks()

        self.assertFalse(app.data_loading)
        self.assertTrue(app.desktop_data_ready)
        self.assertEqual(app.lists["NAZWY"], ["ALFA"])
        self.assertEqual(app.entry_records, [record])
        self.assertEqual(app.btn_submit.state, "normal")
        self.assertEqual(app.btn_search_entry.state, "normal")
        self.assertEqual(app.btn_new_search.state, "normal")
        self.assertEqual(app.btn_edit_lists.state, "normal")

    def test_desktop_data_failure_keeps_ui_available_and_retryable(self) -> None:
        retry_started = threading.Event()
        release_retry = threading.Event()
        attempts = 0
        snapshot = DesktopDataSnapshot(lists={"NAZWY": ["BETA"]}, entries=())

        def fail_then_load():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("data unavailable")
            retry_started.set()
            release_retry.wait(timeout=2.0)
            return snapshot

        with _headless_app_environment(), patch.object(
            app_module,
            "load_desktop_data",
            fail_then_load,
            create=True,
        ):
            app = _HeadlessStartupApp()
            app._desktop_data_loader.join_for_test(timeout=1.0)
            app.run_ui_callbacks()

            self.assertIsNotNone(app.main_view)
            self.assertFalse(app.data_loading)
            self.assertFalse(app.desktop_data_ready)
            self.assertEqual(app.btn_submit.state, "disabled")
            self.assertEqual(app.btn_search_entry.state, "normal")
            self.assertEqual(app.btn_new_search.state, "disabled")
            self.assertEqual(len(app.handled_errors), 1)

            app.btn_search_entry.invoke()
            try:
                self.assertTrue(retry_started.wait(timeout=1.0))
                self.assertTrue(app.data_loading)
                self.assertEqual(app.btn_search_entry.state, "disabled")
            finally:
                release_retry.set()

            app._desktop_data_loader.join_for_test(timeout=1.0)
            app.run_ui_callbacks()

        self.assertEqual(attempts, 2)
        self.assertFalse(app.data_loading)
        self.assertTrue(app.desktop_data_ready)
        self.assertEqual(app.lists["NAZWY"], ["BETA"])

    def test_ean_return_and_new_search_routes_are_blocked_while_loading(self) -> None:
        harness = _ProductActionRouteHarness(
            data_loading=True,
            desktop_data_ready=False,
        )

        App._search_current_entry(harness)
        App._start_new_search(harness)

        self.assertEqual(harness.loaded_records, [])
        self.assertEqual(harness.new_entry_modes, [])
        self.assertEqual(harness.focused_widgets, [])

    def test_ean_return_and_new_search_routes_are_blocked_after_load_error(self) -> None:
        harness = _ProductActionRouteHarness(
            data_loading=False,
            desktop_data_ready=False,
        )

        App._search_current_entry(harness)
        App._start_new_search(harness)

        self.assertEqual(harness.loaded_records, [])
        self.assertEqual(harness.new_entry_modes, [])
        self.assertEqual(harness.focused_widgets, [])

    def test_form_commit_routes_are_blocked_while_loading_and_after_error(self) -> None:
        commit_routes = (
            App._on_name_commit,
            App._on_type_commit,
            App._on_model_commit,
            App._on_color_commit,
            App._on_extra_commit,
        )
        for data_loading, desktop_data_ready in ((True, False), (False, False)):
            for route in commit_routes:
                with self.subTest(
                    route=route.__name__,
                    data_loading=data_loading,
                ):
                    harness = _BlockedCommitHarness(
                        data_loading=data_loading,
                        desktop_data_ready=desktop_data_ready,
                    )
                    route(harness)
                    self.assertEqual(harness.route_calls, [])

    def test_submit_route_is_blocked_while_loading_and_after_error(self) -> None:
        with patch.object(app_module.O, "showwarning") as showwarning:
            for data_loading, desktop_data_ready in ((True, False), (False, False)):
                with self.subTest(data_loading=data_loading):
                    harness = _BlockedCommitHarness(
                        data_loading=data_loading,
                        desktop_data_ready=desktop_data_ready,
                    )
                    App._on_submit(harness)
                    self.assertEqual(harness.route_calls, [])
            showwarning.assert_not_called()

    def test_edit_routes_are_blocked_while_loading_and_after_error(self) -> None:
        for data_loading, desktop_data_ready in ((True, False), (False, False)):
            with self.subTest(data_loading=data_loading):
                harness = _BlockedCommitHarness(
                    data_loading=data_loading,
                    desktop_data_ready=desktop_data_ready,
                )
                App._on_key_release(harness, object())
                App._on_ean_focus_out(harness)
                self.assertEqual(harness.route_calls, [])

    def test_destroy_cancels_desktop_data_delivery_poll(self) -> None:
        with _headless_app_environment(), patch.object(
            app_module,
            "load_desktop_data",
            return_value=DesktopDataSnapshot(lists={}, entries=()),
            create=True,
        ), patch.object(
            app_module.BU.Tk,
            "destroy",
            return_value=None,
            create=True,
        ):
            app = _HeadlessStartupApp()
            loader = _LoaderCancelStub()
            app._desktop_data_loader = loader
            app.destroy()

        self.assertEqual(loader.cancel_calls, 1)

    def test_destroy_closes_desktop_ftp_preview_controller(self) -> None:
        with _headless_app_environment(), patch.object(
            app_module.BU.Tk,
            "destroy",
            return_value=None,
            create=True,
        ), patch.object(
            app_module,
            "DesktopFtpPreviewController",
            side_effect=_FtpPreviewControllerStub,
        ):
            app = _HeadlessStartupApp()
            controller = app._desktop_ftp_preview
            app.destroy()

        self.assertEqual(controller.close_calls, 1)

    def test_cancel_existing_lookup_stops_request_and_releases_preview_dir(self) -> None:
        harness = _LookupCancellationHarness()

        App._cancel_existing_lookup(harness)

        self.assertTrue(harness._existing_lookup_cancel_event.is_set())
        self.assertEqual(
            harness._ftp_temp_manager.released_paths,
            ["C:/temp/managed-preview"],
        )
        self.assertIs(harness._ftp_preview_temp_dir, app_module.I)
        self.assertEqual(harness._load_existing_request_id, 8)

    def test_thumbnail_queue_capacity_covers_two_visible_memory_windows(self) -> None:
        self.assertEqual(
            THUMBNAIL_QUEUE_MAXSIZE,
            SLOT_GRID_COLUMNS * THUMBNAIL_MEMORY_ROWS * 2,
        )

    def test_queue_thumbnail_retries_after_full_queue_without_stale_pending_state(
        self,
    ) -> None:
        harness = _ThumbnailHarness(maxsize=1)
        harness._thumb_request_queue.put_nowait((0, "old.png", 1, False))

        attempt = threading.Thread(
            target=App._queue_thumbnail,
            args=(harness, 2, "new.png"),
            daemon=True,
        )
        attempt.start()
        attempt.join(timeout=1)

        self.assertFalse(attempt.is_alive(), "thumbnail enqueue must be non-blocking")
        self.assertEqual(harness._thumb_pending_paths, {})
        self.assertEqual(harness._thumb_pending_tokens, {})
        self.assertEqual(harness._thumb_tokens[2], 1)

        harness._thumb_request_queue.get_nowait()
        App._queue_thumbnail(harness, 2, "new.png")

        self.assertEqual(
            harness._thumb_request_queue.get_nowait(),
            (2, "new.png", 2, False),
        )
        self.assertEqual(harness._thumb_pending_paths, {2: ("new.png", False)})
        self.assertEqual(harness._thumb_pending_tokens, {2: 2})

    def test_queue_thumbnail_publishes_pending_before_worker_can_drop_result(
        self,
    ) -> None:
        harness = _ThumbnailHarness()
        harness._thumb_pending_lock = _ObservedLock()
        harness._thumb_request_queue = _PublishedBeforeReturnQueue()
        harness._thumb_result_queue = queue.Queue(maxsize=1)
        harness._thumb_result_queue.put_nowait((0, "old.png", 1, object(), False))
        producer = threading.Thread(
            target=App._queue_thumbnail,
            args=(harness, 2, "new.png"),
            daemon=True,
        )
        worker = threading.Thread(
            target=App._thumbnail_worker_loop,
            args=(harness,),
            daemon=True,
        )
        producer.start()
        self.assertTrue(harness._thumb_request_queue.published.wait(timeout=1))
        worker.start()
        worker_synchronized = harness._thumb_pending_lock.waiter_started.wait(timeout=1)
        harness._thumb_request_queue.allow_return.set()
        producer.join(timeout=2)
        harness._thumb_request_queue.put(None, timeout=2)
        worker.join(timeout=2)

        self.assertTrue(worker_synchronized)
        self.assertFalse(producer.is_alive())
        self.assertFalse(worker.is_alive())
        self.assertEqual(harness._thumb_pending_paths, {})
        self.assertEqual(harness._thumb_pending_tokens, {})

    def test_thumbnail_worker_drops_result_when_result_queue_is_full(self) -> None:
        harness = _ThumbnailHarness(maxsize=1)
        harness._thumb_result_queue.put_nowait((0, "old.png", 1, object(), False))
        harness._thumb_pending_paths[2] = ("new.png", False)
        harness._thumb_pending_tokens[2] = 2
        harness._thumb_tokens[2] = 2
        harness._thumb_request_queue.put_nowait((2, "new.png", 2, False))
        worker = threading.Thread(
            target=App._thumbnail_worker_loop, args=(harness,), daemon=True
        )
        worker.start()
        harness._thumb_request_queue.put(None, timeout=2)
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(harness._thumb_result_queue.qsize(), 1)
        self.assertEqual(harness._thumb_pending_paths, {})
        self.assertEqual(harness._thumb_pending_tokens, {})

    def test_dropped_stale_thumbnail_result_preserves_newer_pending_request(
        self,
    ) -> None:
        harness = _ThumbnailHarness(maxsize=1)
        harness._thumb_result_queue.put_nowait((0, "old.png", 1, object(), False))
        harness._thumb_pending_paths[2] = ("new.png", False)
        harness._thumb_pending_tokens[2] = 3
        harness._thumb_tokens[2] = 3
        harness._thumb_request_queue.put_nowait((2, "new.png", 2, False))
        worker = threading.Thread(
            target=App._thumbnail_worker_loop, args=(harness,), daemon=True
        )
        worker.start()
        harness._thumb_request_queue.put(None, timeout=2)
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(harness._thumb_pending_paths, {2: ("new.png", False)})
        self.assertEqual(harness._thumb_pending_tokens, {2: 3})

    def test_poll_stale_thumbnail_result_preserves_newer_same_path_pending(
        self,
    ) -> None:
        harness = _ThumbnailHarness()
        harness._thumb_pending_paths[2] = ("new.png", False)
        harness._thumb_pending_tokens[2] = 2
        harness._thumb_tokens[2] = 2
        harness._thumb_result_queue.put_nowait((2, "new.png", 1, "old", False))

        App._poll_thumbnail_results(harness)

        self.assertEqual(harness._thumb_pending_paths, {2: ("new.png", False)})
        self.assertEqual(harness._thumb_pending_tokens, {2: 2})
        self.assertEqual(harness.preview_updates, [])

    def test_poll_matching_thumbnail_result_clears_pending(self) -> None:
        harness = _ThumbnailHarness()
        harness._thumb_pending_paths[2] = ("new.png", False)
        harness._thumb_pending_tokens[2] = 2
        harness._thumb_tokens[2] = 2
        harness._thumb_result_queue.put_nowait((2, "new.png", 2, "current", False))

        App._poll_thumbnail_results(harness)

        self.assertEqual(harness._thumb_pending_paths, {})
        self.assertEqual(harness._thumb_pending_tokens, {})
        self.assertEqual(
            harness.preview_updates,
            [(2, "new.png", "current", False)],
        )

    def test_clear_thumbnail_pending_removes_path_and_token_together(self) -> None:
        harness = _ThumbnailHarness()
        harness._thumb_pending_paths = {
            1: ("one.png", False),
            2: ("two.png", True),
        }
        harness._thumb_pending_tokens = {1: 4, 2: 5}
        clear_pending = getattr(App, "_clear_thumbnail_pending", None)

        self.assertIsNotNone(clear_pending)
        clear_pending(harness, 1)

        self.assertEqual(harness._thumb_pending_paths, {2: ("two.png", True)})
        self.assertEqual(harness._thumb_pending_tokens, {2: 5})

    def test_set_combobox_values_skips_identical_payload(self) -> None:
        combo = _ComboboxStub()

        App._set_combobox_values(None, combo, ["A", "B"])
        App._set_combobox_values(None, combo, ["A", "B"])
        App._set_combobox_values(None, combo, ["A", "C"])

        self.assertEqual(
            combo.assignments,
            [
                ("values", ("A", "B")),
                ("values", ("A", "C")),
            ],
        )

    def test_list_membership_uses_refreshed_normalized_set(self) -> None:
        harness = _ListHarness()
        harness._list_value_sets = App._build_list_value_sets(harness)

        self.assertTrue(App._list_has_value(harness, n, "alfa"))
        self.assertTrue(App._list_has_value(harness, d, "NO-LED"))

        harness.lists[n].append("BETA")
        App._refresh_list_value_set(harness, n)

        self.assertTrue(App._list_has_value(harness, n, "beta"))

    def test_slot_scroll_uses_smooth_pixel_target(self) -> None:
        harness = _ScrollHarness()

        App._scroll_slots(harness, 10)
        App._flush_slots_scroll(harness)

        self.assertTrue(harness._slots_scroll_active)
        self.assertEqual(harness._slots_canvas.scroll_calls, [])
        self.assertAlmostEqual(harness._slots_scroll_target_px, 300.0)
        self.assertAlmostEqual(harness._slots_canvas.moveto_calls[-1], 0.084)
        self.assertIsNotNone(harness._slots_scroll_job)


if __name__ == "__main__":
    unittest.main()
