"""Unit tests for request-aware existing lookup state transitions."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from picsyncra.common import Aa, AR, I, f
from picsyncra.product_state import ProductState

try:
    from picsyncra.app import App
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local test env
    App = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


class _LookupHarness:
    def __init__(self) -> None:
        self._load_existing_after_id = "lookup-job"
        self._load_existing_request_id = 7
        self._existing_lookup_lock = threading.Lock()
        self._existing_lookup_running = True
        self._existing_lookup_busy = True
        self._existing_lookup_active_request_id = 7
        self._retry_existing_lookup = False
        self.cancelled_after_ids: list[str] = []
        self.busy_updates: list[tuple[str, bool]] = []
        self.slot_updates: list[tuple[bool, object]] = []
        self.after_calls: list[tuple[int, object]] = []
        self.lookup_calls: list[bool] = []

    def after_cancel(self, job_id: str) -> None:
        self.cancelled_after_ids.append(job_id)

    def _set_busy_state(self, text: str, active: bool = True) -> None:
        self.busy_updates.append((text, active))

    def _update_all_slot_activity(self, active: bool = False, status=None) -> None:
        self.slot_updates.append((active, status))

    def after(self, delay_ms: int, callback) -> None:
        self.after_calls.append((delay_ms, callback))

    def _load_existing_files(self, force: bool = False) -> None:
        self.lookup_calls.append(force)


class _StubWidget:
    def __init__(self) -> None:
        self.configured: list[dict[str, object]] = []
        self.place_forget_calls = 0

    def configure(self, **kwargs) -> None:
        self.configured.append(kwargs)

    def place_forget(self) -> None:
        self.place_forget_calls += 1


class _StubProgress(_StubWidget):
    def __init__(self) -> None:
        super().__init__()
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _Var:
    def __init__(self, value="") -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _ClearSlotsHarness:
    def __init__(self) -> None:
        self.pending_additions = {0: "/tmp/new-main.jpg"}
        self.pending_deletions = {1: "/tmp/old-detail.jpg"}
        self.pending_ftp_deletions = {2: "remote-03.jpg"}
        self._thumb_tokens = {0: 123}
        self._product_state = ProductState()
        self._product_state.original_files["01"] = "01.jpg"
        self._product_state.ftp_remote_only["01"] = {
            "filename": "01.jpg",
            "temp_path": "/tmp/01.jpg",
        }
        self._product_state.ftp_presence["01"] = "01.jpg"
        self._product_state.ftp_preview_files["01"] = {
            "filename": "01.jpg",
            "temp_path": "/tmp/01.jpg",
        }
        self._product_state.ftp_downloaded_final.add(0)
        self._product_state.sql_presence = {"01": True}
        self._product_state.sql_values["01"] = "https://sql.example/01.jpg"
        self._slot_status = {"empty": "empty"}
        self.slots = [
            {
                "sql_presence_unknown": True,
                "sql_icon": _StubWidget(),
                "status_label": _StubWidget(),
                "progress": _StubProgress(),
                "marker": "dirty",
            }
        ]
        self.mark_calls: list[tuple[int, object]] = []
        self.cleared_slots: list[int] = []
        self.sync_calls = 0
        self.dashboard_refreshes = 0

    def _clear_slot_preview(self, idx: int) -> None:
        self.cleared_slots.append(idx)

    def _sync_state_refs(self) -> None:
        self.sync_calls += 1

    def _mark_slot(self, idx: int, color) -> None:
        self.mark_calls.append((idx, color))
        self.slots[idx]["marker"] = color

    def _queue_dashboard_refresh(self) -> None:
        self.dashboard_refreshes += 1


class _RemoveFileHarness:
    def __init__(self, *, working_path=None, local_path=None, ftp_path=None) -> None:
        self.is_processing = False
        self.pending_additions = {}
        self.pending_deletions = {}
        self.pending_ftp_deletions = {}
        self.ftp_remote_only = {}
        self.ftp_presence = {}
        self.ftp_preview_files = {}
        self.slots = [
            {
                Aa: "01",
                f: working_path,
                "local_path": local_path,
                "ftp_path": ftp_path,
                "preview_path": working_path or local_path or ftp_path,
                "sql_presence_unknown": False,
            }
        ]
        self.cleared_slots: list[int] = []
        self.sql_refreshes: list[tuple[int, object]] = []
        self.mark_calls: list[tuple[int, object]] = []
        self.dashboard_refreshes = 0
        self.focus_calls = 0

    def _get_slot_preview_path(self, slot):
        return slot.get("preview_path") or slot.get(f)

    def _clear_slot_preview(self, idx: int) -> None:
        self.cleared_slots.append(idx)

    def _refresh_slot_sql_ui(self, idx: int, present=None, state=None) -> None:
        self.sql_refreshes.append((idx, present))

    def _mark_slot(self, idx: int, color) -> None:
        self.mark_calls.append((idx, color))

    def _queue_dashboard_refresh(self) -> None:
        self.dashboard_refreshes += 1

    def focus_force(self) -> None:
        self.focus_calls += 1


@unittest.skipIf(App is None, f"App import unavailable: {APP_IMPORT_ERROR}")
class ExistingLookupStateTests(unittest.TestCase):
    def test_cancel_existing_lookup_invalidates_request_and_clears_busy_state(self) -> None:
        harness = _LookupHarness()

        App._cancel_existing_lookup(harness)

        self.assertEqual(harness.cancelled_after_ids, ["lookup-job"])
        self.assertIsNone(harness._load_existing_after_id)
        self.assertEqual(harness._load_existing_request_id, 8)
        self.assertFalse(harness._existing_lookup_running)
        self.assertFalse(harness._existing_lookup_busy)
        self.assertIsNone(harness._existing_lookup_active_request_id)
        self.assertEqual(harness.busy_updates, [("", False)])
        self.assertEqual(harness.slot_updates, [(False, None)])

    def test_finish_existing_lookup_ignores_stale_request(self) -> None:
        harness = _LookupHarness()
        harness._existing_lookup_active_request_id = 9

        App._finish_existing_lookup(harness, request_id=7)

        self.assertTrue(harness._existing_lookup_running)
        self.assertTrue(harness._existing_lookup_busy)
        self.assertEqual(harness.busy_updates, [])
        self.assertEqual(harness.after_calls, [])

    def test_finish_existing_lookup_matching_request_clears_busy_and_retries(self) -> None:
        harness = _LookupHarness()
        harness._load_existing_after_id = None
        harness._retry_existing_lookup = True

        App._finish_existing_lookup(harness, request_id=7)

        self.assertFalse(harness._existing_lookup_running)
        self.assertFalse(harness._existing_lookup_busy)
        self.assertIsNone(harness._existing_lookup_active_request_id)
        self.assertEqual(harness.busy_updates, [("", False)])
        self.assertEqual(len(harness.after_calls), 1)
        delay_ms, callback = harness.after_calls[0]
        self.assertEqual(delay_ms, 0)
        callback()
        self.assertEqual(harness.lookup_calls, [True])

    def test_clear_all_slots_resets_dirty_marker_state(self) -> None:
        harness = _ClearSlotsHarness()

        App._clear_all_slots(harness)

        self.assertEqual(harness.pending_additions, {})
        self.assertEqual(harness.pending_deletions, {})
        self.assertEqual(harness.pending_ftp_deletions, {})
        self.assertEqual(harness._thumb_tokens, {})
        self.assertEqual(harness._product_state.original_files, {})
        self.assertEqual(harness._product_state.ftp_remote_only, {})
        self.assertEqual(harness._product_state.ftp_presence, {})
        self.assertEqual(harness._product_state.ftp_preview_files, {})
        self.assertEqual(harness._product_state.ftp_downloaded_final, set())
        self.assertIsNone(harness._product_state.sql_presence)
        self.assertEqual(harness._product_state.sql_values, {})
        self.assertEqual(harness.cleared_slots, [0])
        self.assertFalse(harness.slots[0]["sql_presence_unknown"])
        self.assertEqual(harness.mark_calls, [(0, None)])
        self.assertIsNone(harness.slots[0]["marker"])
        self.assertEqual(harness.sync_calls, 1)
        self.assertEqual(harness.dashboard_refreshes, 1)

    def test_remove_file_deletes_local_path_when_filepath_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "_ZDJECIA PRZEROBIONE_"
            processed_dir.mkdir()
            local_file = processed_dir / "5901234567890_01_MAIN.jpg"
            local_file.write_bytes(b"image")
            harness = _RemoveFileHarness(local_path=str(local_file))

            with (
                patch("picsyncra.app.l", str(processed_dir)),
                patch("picsyncra.app.O.askyesno", return_value=True),
            ):
                App._remove_file(harness, 0)

        self.assertEqual(harness.pending_deletions, {0: str(local_file)})
        self.assertEqual(harness.pending_ftp_deletions, {})
        self.assertEqual(harness.cleared_slots, [0])
        self.assertEqual(harness.sql_refreshes, [(0, I)])
        self.assertEqual(harness.mark_calls, [(0, AR)])
        self.assertEqual(harness.dashboard_refreshes, 1)
        self.assertEqual(harness.focus_calls, 1)


@unittest.skipIf(App is None, f"App import unavailable: {APP_IMPORT_ERROR}")
class ProductFieldSettingsTests(unittest.TestCase):
    @staticmethod
    def _harness(**values):
        harness = type("Harness", (), {})()
        defaults = {
            "name": "",
            "type": "",
            "model": "",
            "color1": "",
            "color2": "",
            "color3": "",
            "extra": "",
            "ean": "",
        }
        defaults.update(values)
        for key, value in defaults.items():
            setattr(harness, f"var_{key}", _Var(value))
        harness._get_form_field_raw_value = lambda key: getattr(
            harness, f"var_{key}"
        ).get()
        harness._default_product_field_name = lambda key: {
            "name": "Nazwa",
            "type": "Typ",
            "model": "Model",
            "color1": "Kolor 1",
            "color2": "Kolor 2",
            "color3": "Kolor 3",
            "extra": "Dodatek",
            "ean": "EAN",
        }[key]
        harness._product_field_settings = lambda: App._product_field_settings(harness)
        return harness

    def test_missing_required_fields_use_desktop_custom_label(self) -> None:
        harness = self._harness(type="KOMODA")

        with patch(
            "picsyncra.app.D",
            {
                "product_fields": {
                    "name": {
                        "label": "Kolekcja",
                        "enabled": True,
                        "required": True,
                    },
                    "type": {"enabled": False},
                    "model": {"enabled": True, "required": False},
                    "color1": {"enabled": False},
                }
            },
        ):
            missing = App._missing_required_product_fields(harness)

        self.assertEqual(missing, ["Kolekcja"])

    def test_effective_desktop_values_clear_disabled_fields(self) -> None:
        harness = self._harness(
            name="N",
            type="KOMODA",
            model="M",
            color1="C",
            extra="LED",
            ean="5901234567890",
        )

        with patch(
            "picsyncra.app.D",
            {"product_fields": {"type": {"enabled": False}}},
        ):
            App._clear_disabled_product_field_values(harness)

        self.assertEqual(harness.var_type.get(), "")

    def test_record_from_list_usage_prefers_cached_product_id_and_has_fallback(self) -> None:
        cached = {"PRODUCT_ID": "PRD-1", "EAN": "5901234567890", "NAZWA": "MAGGIORE"}
        harness = type("Harness", (), {"entries_by_id": {"PRD-1": cached}, "entries": {}})()
        self.assertEqual(App._record_from_list_usage(harness, {"product_id": "prd-1"}), cached)
        fallback = App._record_from_list_usage(harness, {
            "product_id": "PRD-2", "ean": "5900000000000", "name": "LUNA",
            "type_name": "STOL", "model": "L-01", "color1": "BIALY",
            "color2": "", "color3": "", "extra": "NO-LED",
        })
        self.assertEqual(fallback["PRODUCT_ID"], "PRD-2")
        self.assertEqual(fallback["NAZWA"], "LUNA")


if __name__ == "__main__":
    unittest.main()
