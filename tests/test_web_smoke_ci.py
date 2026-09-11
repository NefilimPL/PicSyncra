"""CI smoke tests for the FastAPI web panel."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import gc
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
import io
from pathlib import Path

os.environ.setdefault("PICSYNCRA_HEADLESS", "1")
os.environ.setdefault("PICSYNCRA_WEB_AUTH", "0")

try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - depends on CI test dependencies
    TestClient = None
    TEST_CLIENT_IMPORT_ERROR = exc
else:
    TEST_CLIENT_IMPORT_ERROR = None

from picsyncra import web_data
from picsyncra import observability
from picsyncra.web import app as web_app


def _reset_web_test_storage() -> None:
    web_app._invalidate_health_integration_cache()
    web_app.data_store.reset_active_store_cache()
    gc.collect()


@contextmanager
def _temporary_web_data_directory():
    directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        yield directory.name
    finally:
        _reset_web_test_storage()
        deadline = time.monotonic() + 5.0
        while True:
            gc.collect()
            try:
                shutil.rmtree(directory.name)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        directory.cleanup()


@unittest.skipIf(
    TestClient is None,
    f"FastAPI TestClient unavailable: {TEST_CLIENT_IMPORT_ERROR}",
)
class WebSmokeCiTests(unittest.TestCase):
    def test_list_remove_route_serializes_blocking_products(self) -> None:
        client = TestClient(web_app.app)
        usage = [{"product_id": "PRD-1", "ean": "5901234567890", "fields": "NAZWA"}]
        error = web_data.ListValueInUseError("names", "MAGGIORE", usage)
        with (
            patch.object(web_app, "_require_user", return_value={"username": "operator"}),
            patch.object(web_app, "remove_list_value", side_effect=error),
        ):
            response = client.request(
                "DELETE", "/api/lists/names", json={"value": "MAGGIORE"}
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            {
                "message": str(error),
                "list_key": "names",
                "value": "MAGGIORE",
                "used_by": usage,
            },
        )

    def setUp(self) -> None:
        os.environ["PICSYNCRA_WEB_AUTH"] = "0"
        self._web_data_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._web_data_directory.cleanup)
        data_path_patch = patch.object(
            web_app.settings, "AC", self._web_data_directory.name
        )
        data_path_patch.start()
        self.addCleanup(data_path_patch.stop)
        bootstrap_settings_patch = patch.object(
            web_app.storage_settings,
            "load_bootstrap_settings",
            return_value={"data_mode": "legacy"},
        )
        bootstrap_settings_patch.start()
        self.addCleanup(bootstrap_settings_patch.stop)
        web_app.data_store.reset_active_store_cache()
        self.addCleanup(_reset_web_test_storage)
        web_app._RATE_LIMITS.clear()

    def tearDown(self) -> None:
        web_app._RATE_LIMITS.clear()

    def test_default_admin_can_log_in_with_isolated_test_storage(self) -> None:
        """Authentication smoke tests must not depend on a developer's data path."""

        with patch.dict(os.environ, {"PICSYNCRA_WEB_AUTH": "1"}):
            client = TestClient(web_app.app)
            response = client.post(
                "/api/login",
                data={"username": "admin", "password": "admin"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["user"]["role"], "admin")

    def test_health_endpoint_returns_versioned_ok_payload(self) -> None:
        client = TestClient(web_app.app)

        with (
            _temporary_web_data_directory() as temp_dir,
            patch.object(
                web_app.storage_settings,
                "resolve_sqlite_path",
                return_value=os.path.join(temp_dir, "health.sqlite"),
            ),
            patch.object(
                web_app,
                "notification_worker_health",
                return_value={
                    "status": "online",
                    "observed_at": "2026-07-17T08:00:00.000Z",
                },
            ),
        ):
            web_app._invalidate_health_integration_cache()
            response = client.get("/api/health")
        web_app._invalidate_health_integration_cache()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["application"], "picsyncra")
        self.assertTrue(str(payload["version"]).strip())
        self.assertTrue(str(payload["time"]).strip())
        self.assertEqual(payload["components"]["backend"]["status"], "online")
        self.assertIn(payload["components"]["sqlite"]["status"], {"online", "critical"})
        self.assertIn(
            payload["components"]["job_processor"]["status"],
            {"online", "critical"},
        )
        self.assertEqual(
            payload["components"]["notification_worker"]["status"], "online"
        )
        self.assertIn("resources", payload)

    def test_add_user_route_forwards_email(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(web_app, "_current_user_payload", return_value=admin),
            patch.object(web_app, "add_user", return_value=[]) as add_user,
        ):
            response = client.post(
                "/api/users",
                json={
                    "username": "operator",
                    "password": "secret",
                    "role": "user",
                    "email": "operator@example.com",
                },
            )

        self.assertEqual(response.status_code, 200)
        add_user.assert_called_once_with(
            "operator",
            "secret",
            "user",
            "operator@example.com",
        )

    def test_add_user_route_defaults_omitted_email_to_empty_string(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(web_app, "_current_user_payload", return_value=admin),
            patch.object(
                web_data,
                "load_user_records",
                return_value=[web_data._default_admin()],
            ),
            patch.object(
                web_data,
                "save_users",
                side_effect=lambda records: [
                    web_data._public_user(record) for record in records
                ],
            ),
            patch.object(web_app, "add_user", wraps=web_data.add_user) as add_user,
        ):
            response = client.post(
                "/api/users",
                json={
                    "username": "operator",
                    "password": "secret",
                    "role": "user",
                },
            )

        self.assertEqual(response.status_code, 200)
        add_user.assert_called_once_with("operator", "secret", "user", "")
        self.assertEqual(response.json()["users"][0]["email"], "")

    def test_update_user_route_forwards_email(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(web_app, "_current_user_payload", return_value=admin),
            patch.object(web_app, "update_user", return_value=[]) as update_user,
        ):
            response = client.patch(
                "/api/users/operator",
                json={"email": ""},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(update_user.call_args.kwargs["email"], "")

    def test_client_error_route_requires_auth_and_csrf_and_emits_redacted_critical(self) -> None:
        class EventStore:
            supports_atomic_incident_event = True

            def __init__(self) -> None:
                self.events = []

            def append_operational_event(self, event):
                self.events.append(dict(event))
                return dict(event)

            def coalesce_incident(self, incident, *, source_event=None):
                if source_event is not None:
                    self.events.append(dict(source_event))
                return {
                    **dict(incident),
                    "notification_due": False,
                    "notification_claim_at": "",
                }

        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        store = EventStore()
        try:
            client = TestClient(web_app.app)
            payload = {
                "kind": "error",
                "message": "Frontend exploded",
                "source": "app.js",
                "line": 42,
                "column": 7,
                "stack": "Error: Frontend exploded",
                "token": "browser-secret",
            }

            anonymous = client.post("/api/observability/client-errors", json=payload)
            self.assertEqual(anonymous.status_code, 401)

            login = client.post(
                "/api/login",
                data={"username": "admin", "password": "admin"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertEqual(login.status_code, 200)
            csrf = login.json()["csrf_token"]
            forged = client.post(
                "/api/observability/client-errors",
                json=payload,
                headers={"X-PicSyncra-CSRF": "bad"},
            )
            self.assertEqual(forged.status_code, 403)

            with patch.object(observability, "observability_store", return_value=store):
                response = client.post(
                    "/api/observability/client-errors",
                    json=payload,
                    headers={"X-PicSyncra-CSRF": csrf},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            event = store.events[-1]
            self.assertEqual(event["severity"], "critical")
            self.assertEqual(event["event_type"], "frontend.unhandled_error")
            self.assertEqual(event["details"]["token"], "[REDACTED]")
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_unhandled_backend_error_returns_only_safe_correlation_payload(self) -> None:
        test_app = web_app.create_app()

        @test_app.get("/api/test-unhandled-error")
        def fail_for_test():
            raise RuntimeError("database password=top-secret")

        client = TestClient(test_app, raise_server_exceptions=False)
        with (
            patch.object(web_app, "emit_event") as emit_event,
            patch.object(web_app, "log_error") as log_error,
        ):
            response = client.get("/api/test-unhandled-error")

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["detail"], "Wystapil nieoczekiwany blad aplikacji.")
        self.assertTrue(payload["correlation_id"])
        self.assertNotIn("password", response.text)
        self.assertEqual(emit_event.call_args.kwargs["severity"], "critical")
        self.assertEqual(
            emit_event.call_args.kwargs["correlation_id"], payload["correlation_id"]
        )
        self.assertIsInstance(emit_event.call_args.kwargs["exception"], RuntimeError)
        self.assertIn(payload["correlation_id"], log_error.call_args.args[0])

    def test_synchronous_process_endpoint_persists_correlated_success(self) -> None:
        snapshot = web_app._ProcessFormSnapshot(
            fields={"ean": "5901234567890", "name": "Created product"}
        )
        result = {
            "timing": {"stages": [{"key": "prepare", "elapsed_ms": 12}]},
            "ftp": {},
            "sql": {},
            "local_delete": {},
            "skipped_slots": [],
            "entry": {"product_id": "123"},
        }
        client = TestClient(web_app.app)

        with (
            patch.object(web_app, "_materialize_process_form", return_value=snapshot),
            patch.object(web_app, "_process_upload_snapshot", return_value=result) as process,
            patch.object(web_app, "record_job") as record_job,
            patch.object(web_app, "emit_event") as emit_event,
        ):
            response = client.post("/api/process", data={})

        self.assertEqual(response.status_code, 200)
        job_id = process.call_args.kwargs["job_id"]
        self.assertTrue(job_id)
        self.assertEqual(
            [call.args[0]["status"] for call in record_job.call_args_list],
            ["running", "completed"],
        )
        self.assertTrue(
            all(call.args[0]["id"] == job_id for call in record_job.call_args_list)
        )
        result_event = emit_event.call_args_list[-1]
        self.assertEqual(result_event.kwargs["event_type"], "process.completed")
        self.assertEqual(result_event.kwargs["severity"], "info")
        self.assertEqual(result_event.kwargs["job_id"], job_id)

    def test_synchronous_process_failure_is_job_correlated_and_returns_safe_500(self) -> None:
        snapshot = web_app._ProcessFormSnapshot(fields={"ean": "5901234567890"})
        client = TestClient(web_app.app, raise_server_exceptions=False)

        with (
            patch.object(web_app, "_materialize_process_form", return_value=snapshot),
            patch.object(
                web_app,
                "_process_upload_snapshot",
                side_effect=RuntimeError("database password=top-secret"),
            ) as process,
            patch.object(web_app, "record_job") as record_job,
            patch.object(web_app, "emit_event") as emit_event,
            patch.object(web_app, "log_error"),
        ):
            response = client.post("/api/process", data={})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Wystapil nieoczekiwany blad aplikacji.")
        job_id = process.call_args.kwargs["job_id"]
        self.assertTrue(job_id)
        self.assertEqual(record_job.call_args_list[-1].args[0]["status"], "failed")
        self.assertEqual(record_job.call_args_list[-1].args[0]["id"], job_id)
        process_failure = next(
            call
            for call in emit_event.call_args_list
            if call.kwargs["event_type"] == "process.failed"
        )
        self.assertEqual(process_failure.kwargs["severity"], "critical")
        self.assertEqual(process_failure.kwargs["job_id"], job_id)
        backend_failure = next(
            call
            for call in emit_event.call_args_list
            if call.kwargs["event_type"] == "backend.unhandled_error"
        )
        self.assertEqual(
            backend_failure.kwargs["correlation_id"], response.json()["correlation_id"]
        )


    def test_public_pages_and_static_assets_are_served(self) -> None:
        client = TestClient(web_app.app)

        index = client.get("/")
        login = client.get("/login")
        app_js = client.get("/static/app.js")
        app_css = client.get("/static/app.css")

        self.assertEqual(index.status_code, 200)
        self.assertIn("PicSyncra Web", index.text)
        self.assertIn('id="productForm"', index.text)
        self.assertIn('id="slotGrid"', index.text)
        self.assertIn(login.status_code, {200, 303})
        self.assertEqual(app_js.status_code, 200)
        self.assertIn("const state", app_js.text)
        self.assertEqual(app_css.status_code, 200)
        self.assertIn(".slot-grid", app_css.text)

    def test_critical_backend_routes_remain_registered(self) -> None:
        route_paths = {
            getattr(route, "path", "")
            for route in web_app.app.routes
        }

        expected_paths = {
            "/",
            "/login",
            "/api/health",
            "/api/resource-monitor/simulate-safe",
            "/api/resource-monitor/real-test",
            "/api/login",
            "/api/logout",
            "/api/bootstrap",
            "/api/data",
            "/api/github/repository",
            "/api/process",
            "/api/upload-cache",
            "/api/browser-extension/download",
            "/api/browser-extension/imports",
            "/api/browser-extension/ping",
            "/api/browser-extension/upload-cache",
            "/api/web-images/scan",
            "/api/web-images/cache",
            "/api/entries/search",
            "/api/entries/save",
            "/api/entries/photos",
            "/api/file",
            "/api/thumbnail",
            "/api/settings",
            "/api/settings/email/test",
            "/api/settings/email/test-suite",
            "/api/settings/sqlite/repair",
            "/api/settings/sqlite/backup",
            "/api/settings/sqlite/backups",
            "/api/settings/sqlite/backup-diff",
            "/api/settings/sqlite/restore",
            "/api/settings/sql-columns/detect",
            "/api/server/presence",
            "/api/server/presence/leave",
            "/api/users",
        }
        self.assertEqual(expected_paths - route_paths, set())

    def test_web_does_not_expose_legacy_profile_import_endpoint(self) -> None:
        """A folder submitted over HTTP must no longer reach filesystem migration code."""

        route_paths = {getattr(route, "path", "") for route in web_app.app.routes}

        self.assertNotIn("/api/settings/import-legacy", route_paths)

    def test_email_test_route_returns_only_redacted_delivery_summary(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        result = {
            "status": "fallback",
            "used_channel": "smtp",
            "message_id": "must-not-be-returned",
            "attempts": [
                {
                    "channel": "entra",
                    "status": "error",
                    "code": "delivery_failed",
                    "category": "delivery",
                    "message": "token=TOP-SECRET server=mail.internal",
                    "raw_response": "client_secret=LEAK",
                },
                {
                    "channel": "smtp",
                    "status": "sent",
                    "code": "sent",
                    "category": "delivery",
                    "message": "smtp password=LEAK",
                },
            ],
        }
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(web_app, "send_test_message", return_value=result) as sender,
        ):
            response = client.post(
                "/api/settings/email/test",
                json={
                    "recipient": "admin@example.com",
                    "channel": "entra",
                    "use_fallback": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"ok", "status", "used_channel", "attempts", "elapsed_ms"},
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "fallback")
        self.assertEqual(payload["used_channel"], "smtp")
        self.assertGreaterEqual(payload["elapsed_ms"], 0)
        self.assertNotIn("TOP-SECRET", response.text)
        self.assertNotIn("mail.internal", response.text)
        self.assertNotIn("LEAK", response.text)
        self.assertNotIn("message_id", response.text)
        sender.assert_called_once_with(
            channel="entra",
            recipient="admin@example.com",
            use_fallback=True,
        )

    def test_email_test_suite_returns_safe_scenario_summaries(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        result = {
            "scenarios": [
                {
                    "kind": "pimcore_rejection",
                    "severity": "warning",
                    "status": "sent",
                    "used_channel": "entra",
                    "recipient_count": 2,
                    "message_id": "must-not-be-returned",
                    "attempts": [{"channel": "entra", "status": "sent"}],
                },
                {
                    "kind": "ftp_failure",
                    "severity": "error",
                    "status": "fallback",
                    "used_channel": "smtp",
                    "recipient_count": 1,
                    "message_id": "ftp-private-message-id",
                    "recipients": ["ftp-recipient@example.com"],
                    "exception_attachment": {
                        "filename": "ftp-exception.txt",
                        "content": "TASK4-UNIQUE-SECRET-SENTINEL",
                    },
                    "attempts": [
                        {
                            "channel": "entra",
                            "status": "error",
                            "code": "untrusted_secret_code",
                            "category": "delivery",
                            "message": "password=LEAK",
                        },
                        {"channel": "smtp", "status": "sent"},
                    ],
                },
                {
                    "kind": "photo_location_unavailable",
                    "severity": "error",
                    "status": "skipped",
                    "used_channel": "smtp",
                    "recipient_count": 0,
                    "attempts": [],
                },
                {
                    "kind": "backend_exception",
                    "severity": "critical",
                    "status": "sent",
                    "used_channel": "entra",
                    "recipient_count": 1,
                    "attempts": [{"channel": "entra", "status": "sent"}],
                },
                {
                    "kind": "entra_secret_expiry",
                    "severity": "critical",
                    "status": "sent",
                    "used_channel": "entra",
                    "recipient_count": 1,
                    "attempts": [{"channel": "entra", "status": "sent"}],
                },
            ]
        }
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(web_app, "send_test_notification_suite", return_value=result) as sender,
        ):
            response = client.post(
                "/api/settings/email/test-suite",
                json={"channel": "entra", "use_fallback": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {"ok", "scenarios", "elapsed_ms"})
        self.assertTrue(payload["ok"])
        self.assertEqual(
            [scenario["kind"] for scenario in payload["scenarios"]],
            [
                "pimcore_rejection",
                "ftp_failure",
                "photo_location_unavailable",
                "backend_exception",
                "entra_secret_expiry",
            ],
        )
        for scenario in payload["scenarios"]:
            self.assertEqual(
                set(scenario),
                {"kind", "severity", "status", "used_channel", "recipient_count", "attempts"},
            )
        self.assertEqual(payload["scenarios"][1]["attempts"][0]["code"], "delivery_failed")
        self.assertNotIn("LEAK", response.text)
        self.assertNotIn("ftp-recipient@example.com", response.text)
        self.assertNotIn("ftp-private-message-id", response.text)
        self.assertNotIn("TASK4-UNIQUE-SECRET-SENTINEL", response.text)
        self.assertNotIn("message_id", response.text)
        sender.assert_called_once_with(channel="entra", use_fallback=True)

    def test_email_test_route_resolves_primary_and_maps_delivery_error_to_502(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(
                web_app,
                "settings_snapshot",
                return_value={
                    "email_notifications": {"primary_channel": "smtp"}
                },
            ),
            patch.object(
                web_app,
                "send_test_message",
                return_value={
                    "status": "error",
                    "used_channel": "smtp",
                    "attempts": [
                        {
                            "channel": "smtp",
                            "status": "error",
                            "code": "transport_unavailable",
                            "category": "transport",
                            "message": "host=smtp.secret.example password=hunter2",
                        }
                    ],
                },
            ) as sender,
        ):
            response = client.post(
                "/api/settings/email/test",
                json={
                    "recipient": "admin@example.com",
                    "channel": "primary",
                    "use_fallback": False,
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["ok"])
        self.assertNotIn("smtp.secret.example", response.text)
        self.assertNotIn("hunter2", response.text)
        sender.assert_called_once_with(
            channel="smtp",
            recipient="admin@example.com",
            use_fallback=False,
        )

    def test_email_test_route_replaces_untrusted_attempt_codes_from_api(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        untrusted_codes = [
            "ToPSeCrEt123",
            {"nested": {"token": "LEAK"}},
            "server_password_token_" + ("X" * 200),
        ]

        for raw_code in untrusted_codes:
            with self.subTest(raw_code=raw_code):
                with (
                    patch.object(web_app, "_require_admin", return_value=admin),
                    patch.object(
                        web_app,
                        "send_test_message",
                        return_value={
                            "status": "error",
                            "used_channel": "entra",
                            "attempts": [
                                {
                                    "channel": "entra",
                                    "status": "error",
                                    "code": raw_code,
                                    "category": "delivery",
                                    "message": "token=TOPSECRET123",
                                }
                            ],
                        },
                    ),
                ):
                    response = client.post(
                        "/api/settings/email/test",
                        json={
                            "recipient": "admin@example.com",
                            "channel": "entra",
                            "use_fallback": False,
                        },
                    )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json(),
                    {
                        "ok": False,
                        "status": "error",
                        "used_channel": "entra",
                        "attempts": [
                            {
                                "channel": "entra",
                                "status": "error",
                                "code": "delivery_failed",
                                "category": "delivery",
                                "message": "Kanal nie wyslal wiadomosci.",
                            }
                        ],
                        "elapsed_ms": response.json()["elapsed_ms"],
                    },
                )
                self.assertNotIn("TOPSECRET", response.text.upper())
                self.assertNotIn("SERVER_PASSWORD", response.text.upper())

    def test_email_test_route_rejects_invalid_payload_without_sending(self) -> None:
        client = TestClient(web_app.app)
        admin = {"username": "admin", "role": "admin"}
        with (
            patch.object(web_app, "_require_admin", return_value=admin),
            patch.object(web_app, "send_test_message") as sender,
        ):
            bad_channel = client.post(
                "/api/settings/email/test",
                json={
                    "recipient": "admin@example.com",
                    "channel": "exchange",
                    "use_fallback": False,
                },
            )
            bad_flag = client.post(
                "/api/settings/email/test",
                json={
                    "recipient": "admin@example.com",
                    "channel": "smtp",
                    "use_fallback": "yes",
                },
            )

        self.assertEqual(bad_channel.status_code, 400)
        self.assertEqual(bad_flag.status_code, 400)
        sender.assert_not_called()

    def test_email_test_route_requires_admin_session_and_csrf(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            client = TestClient(web_app.app)
            request_payload = {
                "recipient": "admin@example.com",
                "channel": "smtp",
                "use_fallback": False,
            }
            anonymous = client.post(
                "/api/settings/email/test", json=request_payload
            )
            self.assertEqual(anonymous.status_code, 401)

            login = client.post(
                "/api/login",
                data={"username": "admin", "password": "admin"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertEqual(login.status_code, 200)
            forged = client.post(
                "/api/settings/email/test",
                json=request_payload,
                headers={"X-PicSyncra-CSRF": "bad"},
            )
            self.assertEqual(forged.status_code, 403)

            with patch.object(
                web_app,
                "send_test_message",
                return_value={
                    "status": "sent",
                    "used_channel": "smtp",
                    "attempts": [{"channel": "smtp", "status": "sent"}],
                },
            ):
                accepted = client.post(
                    "/api/settings/email/test",
                    json=request_payload,
                    headers={"X-PicSyncra-CSRF": login.json()["csrf_token"]},
                )
            self.assertEqual(accepted.status_code, 200)
            self.assertTrue(accepted.json()["ok"])
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_github_repository_endpoint_returns_status_payload(self) -> None:
        client = TestClient(web_app.app)
        payload = {
            "available": True,
            "private": False,
            "repository": {"full_name": "NefilimPL/PicSyncra"},
            "latest_release": {"tag_name": "v1.2.3"},
            "license": {"spdx_id": "MIT"},
            "owner": {"login": "NefilimPL"},
            "contributors": [],
            "current_version": "dev",
            "update_available": True,
            "message": "",
            "checked_at": "2026-07-09T00:00:00Z",
        }

        with patch.object(web_app, "github_repository_status", return_value=payload):
            response = client.get("/api/github/repository")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_sqlite_repair_endpoint_returns_summary(self) -> None:
        client = TestClient(web_app.app)
        with (
            patch.object(web_app.storage_settings, "resolve_sqlite_path", return_value="C:/Data/app.sqlite"),
            patch.object(web_app.storage_settings, "resolve_backup_dir", return_value="C:/Data/BACKUP"),
            patch.object(web_app, "repair_sqlite_database", return_value={"ok": True, "integrity_check": "ok"}),
            patch.object(web_app, "settings_snapshot", return_value={"data_mode": "sqlite"}),
        ):
            response = client.post("/api/settings/sqlite/repair")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_sqlite_backup_history_endpoint_lists_backups(self) -> None:
        client = TestClient(web_app.app)
        with (
            patch.object(web_app.storage_settings, "resolve_backup_dir", return_value="C:/Data/BACKUP"),
            patch.object(web_app.sqlite_backup, "list_backups", return_value=[{"backup_path": "copy.sqlite"}]),
        ):
            response = client.get("/api/settings/sqlite/backups")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["backup_path"], "copy.sqlite")

    def test_sqlite_backup_restore_rejects_path_outside_trusted_directories(self) -> None:
        client = TestClient(web_app.app)
        with (
            patch.object(web_app.storage_settings, "resolve_sqlite_path", return_value="C:/Data/app.sqlite"),
            patch.object(web_app.storage_settings, "resolve_backup_dir", return_value="C:/Data/BACKUP"),
            patch.object(web_app.storage_settings, "resolve_backup_dirs", return_value=["C:/Data/BACKUP"]),
            patch.object(web_app.sqlite_backup, "restore_backup", side_effect=ValueError("Wybrana kopia nie znajduje sie w dozwolonym katalogu.")),
        ):
            response = client.post("/api/settings/sqlite/restore", json={"backup_path": "C:/secret.sqlite"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("dozwolonym katalogu", response.json()["detail"])

    def test_backup_scheduler_runs_due_slots(self) -> None:
        backup_settings = {
            "enabled": True,
            "days": ["mon"],
            "hours": [8],
            "max_copies": 2,
            "last_run_slots": [],
        }
        with (
            patch.object(
                web_app.storage_settings,
                "load_backup_settings",
                return_value=backup_settings,
            ),
            patch.object(
                web_app.sqlite_backup,
                "due_schedule_slots",
                return_value=["2026-06-22T08"],
            ) as due_schedule_slots,
            patch.object(web_app.sqlite_backup, "create_backup", return_value={"ok": True}),
            patch.object(web_app.storage_settings, "resolve_sqlite_path", return_value="C:/Data/app.sqlite"),
            patch.object(web_app.storage_settings, "resolve_backup_dir", return_value="C:/Data/BACKUP"),
            patch.object(
                web_app.sqlite_backup,
                "mark_schedule_slots_run",
                return_value={
                    "enabled": True,
                    "days": ["mon"],
                    "hours": [8],
                    "max_copies": 2,
                    "last_run_slots": ["2026-06-22T08"],
                },
            ),
            patch.object(web_app.storage_settings, "save_backup_settings") as save_backup_settings,
            patch.dict(
                web_app.config.CONFIG,
                {"web_display": {"time_zone": "Europe/Warsaw"}},
                clear=False,
            ),
        ):
            result = web_app._run_due_sqlite_backups_once()

        self.assertEqual(result["created"], 1)
        due_schedule_slots.assert_called_once_with(
            backup_settings,
            time_zone_name="Europe/Warsaw",
        )
        save_backup_settings.assert_called_once()

    def test_live_event_pruning_runs_no_more_than_hourly(self) -> None:
        with (
            patch.object(web_app, "prune_live_events", return_value=3) as prune,
            patch.object(web_app.time, "monotonic", side_effect=[100.0, 200.0, 3701.0]),
        ):
            web_app._LIVE_EVENT_LAST_PRUNED = 0.0
            self.assertEqual(web_app._prune_live_events_if_due(force=True), 3)
            self.assertEqual(web_app._prune_live_events_if_due(), 0)
            self.assertEqual(web_app._prune_live_events_if_due(), 3)

        self.assertEqual(prune.call_count, 2)

    def test_failed_live_event_pruning_retries_without_throttle(self) -> None:
        with (
            patch.object(
                web_app,
                "prune_live_events",
                side_effect=[RuntimeError("database busy"), 3],
            ) as prune,
            patch.object(web_app.time, "monotonic", side_effect=[100.0, 101.0]),
        ):
            web_app._LIVE_EVENT_LAST_PRUNED = 0.0
            with self.assertRaises(RuntimeError):
                web_app._prune_live_events_if_due(force=True)
            self.assertEqual(web_app._LIVE_EVENT_LAST_PRUNED, 0.0)
            self.assertEqual(web_app._prune_live_events_if_due(), 3)

        self.assertEqual(prune.call_count, 2)

    def test_sql_column_detection_endpoint_updates_settings(self) -> None:
        client = TestClient(web_app.app)
        cfg = {
            web_app.SQL_AVAILABLE_COLUMNS_KEY: [],
            web_app.H: {},
            web_app.P: {},
            web_app.K: {},
        }

        with (
            patch.object(web_app.config, "CONFIG", cfg),
            patch.object(
                web_app,
                "detect_available_columns",
                return_value={
                    "ok": True,
                    "columns": ["img_01", "img_02"],
                    "table": "object_query_1",
                    "preview": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS",
                    "message": "Wykryto 2 pola SQL.",
                },
            ),
            patch.object(web_app.config, "save_config") as save_config,
            patch.object(
                web_app,
                "settings_snapshot",
                return_value={"sql_available_columns": ["img_01", "img_02"]},
            ),
        ):
            response = client.post("/api/settings/sql-columns/detect")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["columns"], ["img_01", "img_02"])
        self.assertEqual(cfg[web_app.SQL_AVAILABLE_COLUMNS_KEY], ["img_01", "img_02"])
        save_config.assert_called_once()

    def test_auth_enabled_protects_routes_and_logout_clears_a_stale_session(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            with _temporary_web_data_directory() as temp_dir:
                with patch.object(web_app.settings, "AC", temp_dir):
                    client = TestClient(web_app.app)

                    stale_cookie = "stale-session-from-before-legacy-import"
                    client.cookies.set(web_app.SESSION_COOKIE, stale_cookie)
                    stale_logout = client.post("/api/logout")
                    self.assertEqual(stale_logout.status_code, 200)
                    self.assertIn("Max-Age=0", stale_logout.headers["set-cookie"])
                    self.assertEqual(client.get("/api/bootstrap").status_code, 401)

                    login = client.post(
                        "/api/login",
                        data={"username": "admin", "password": "admin"},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )
                    self.assertEqual(login.status_code, 200)
                    csrf_headers = {"X-PicSyncra-CSRF": login.json()["csrf_token"]}
                    presence = client.get("/api/server/presence")
                    self.assertEqual(presence.status_code, 200)
                    self.assertEqual(presence.json(), {"enabled": False, "users": []})

                    authenticated = client.post("/api/logout", headers=csrf_headers)
                    self.assertEqual(authenticated.status_code, 200)
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_session_v2_payload_uses_user_id_not_username(self) -> None:
        user = {
            "id": "7c8e1b5e-4c50-4da4-9b37-51b9db4600fa",
            "username": "operator",
            "enabled": True,
            "locked": False,
            "session_version": 3,
        }
        with patch.object(web_app, "find_user_by_id", return_value=user):
            token = web_app._make_session_token(user)
            payload = (
                base64.urlsafe_b64decode(token.encode("ascii"))
                .decode("utf-8")
                .rsplit("|", 1)[0]
            )
            resolved = web_app._read_session_token(token)

        self.assertTrue(
            payload.startswith("session-v2|7c8e1b5e-4c50-4da4-9b37-51b9db4600fa|3|")
        )
        self.assertNotIn("operator", payload)
        self.assertEqual(resolved, "operator")

    def test_signed_pre_v2_session_cookie_is_rejected(self) -> None:
        payload = f"session|admin|0|{int(time.time())}|legacy-nonce"
        token = base64.urlsafe_b64encode(
            f"{payload}|{web_app._sign(payload)}".encode("utf-8")
        ).decode("ascii")

        with patch.object(
            web_app,
            "find_user",
            return_value={
                "username": "admin",
                "enabled": True,
                "locked": False,
                "session_version": 0,
            },
        ):
            self.assertIsNone(web_app._read_session_token(token))

    def test_security_headers_include_strict_csp(self) -> None:
        client = TestClient(web_app.app)

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        csp = response.headers.get("content-security-policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)

    def test_login_rate_limit_is_per_ip(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            with _temporary_web_data_directory() as temp_dir:
                with (
                    patch.object(web_app.settings, "AC", temp_dir),
                    patch.object(web_app, "RATE_LIMIT_LOGIN_ATTEMPTS", 2),
                    patch.object(web_app, "RATE_LIMIT_LOGIN_WINDOW_SECONDS", 60),
                ):
                    web_app._RATE_LIMITS.clear()
                    client = TestClient(web_app.app)
                    for _index in range(2):
                        response = client.post(
                            "/api/login",
                            data={"username": "admin", "password": "bad"},
                            headers={"X-Requested-With": "XMLHttpRequest"},
                        )
                        self.assertEqual(response.status_code, 401)

                    limited = client.post(
                        "/api/login",
                        data={"username": "admin", "password": "bad"},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )

            self.assertEqual(limited.status_code, 429)
            self.assertIn("Retry-After", limited.headers)
        finally:
            web_app._RATE_LIMITS.clear()
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_failed_admin_login_is_logged_and_locked_until_manual_unlock(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            with _temporary_web_data_directory() as temp_dir:
                with (
                    patch.object(web_app.settings, "AC", temp_dir),
                    patch.object(web_app.settings, "LOG_DIR", temp_dir),
                ):
                    client = TestClient(web_app.app)
                    response = None
                    for _index in range(web_data.LOGIN_FAILURE_LIMIT):
                        response = client.post(
                            "/api/login",
                            data={"username": "admin", "password": "bad"},
                            headers={"X-Requested-With": "XMLHttpRequest"},
                        )

                    self.assertIsNotNone(response)
                    self.assertEqual(response.status_code, 423)
                    log_text = (web_app._web_events_log_path()).read_text(encoding="utf-8")
                    self.assertIn("LOGIN_FAILED", log_text)
                    self.assertIn("Konto administratora zablokowane", log_text)
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_password_change_invalidates_current_session(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            with _temporary_web_data_directory() as temp_dir:
                with patch.object(web_app.settings, "AC", temp_dir):
                    client = TestClient(web_app.app)
                    login = client.post(
                        "/api/login",
                        data={"username": "admin", "password": "admin"},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )
                    self.assertEqual(login.status_code, 200)
                    headers = {"X-PicSyncra-CSRF": login.json()["csrf_token"]}
                    response = client.patch(
                        "/api/users/admin",
                        json={"password": "new-admin"},
                        headers=headers,
                    )

                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["session_invalidated"])
                    self.assertEqual(client.get("/api/bootstrap").status_code, 401)
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_browser_extension_token_version_can_be_revoked(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            with _temporary_web_data_directory() as temp_dir:
                with patch.object(web_app.settings, "AC", temp_dir):
                    client = TestClient(web_app.app)
                    login = client.post(
                        "/api/login",
                        data={"username": "admin", "password": "admin"},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )
                    self.assertEqual(login.status_code, 200)
                    headers = {"X-PicSyncra-CSRF": login.json()["csrf_token"]}
                    archive_response = client.get("/api/browser-extension/download")
                    self.assertEqual(archive_response.status_code, 200)
                    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
                        defaults = archive.read(
                            "picsyncra-browser-extension/defaults.js"
                        ).decode("utf-8")
                    self.assertIn("tokenVersion", defaults)
                    token = defaults.split('"apiToken": "', 1)[1].split('"', 1)[0]
                    ping = client.get(
                        "/api/browser-extension/ping",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    self.assertEqual(ping.status_code, 200)
                    self.assertEqual(ping.json()["token_version"], 0)

                    revoked = client.patch(
                        "/api/users/admin",
                        json={"revoke_extension_token": True},
                        headers=headers,
                    )
                    self.assertEqual(revoked.status_code, 200)
                    rejected = client.get(
                        "/api/browser-extension/ping",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    self.assertEqual(rejected.status_code, 401)
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous

    def test_app_secret_change_returns_relogin_response_instead_of_401(self) -> None:
        previous = os.environ.get("PICSYNCRA_WEB_AUTH")
        os.environ["PICSYNCRA_WEB_AUTH"] = "1"
        try:
            with _temporary_web_data_directory() as temp_dir:
                with patch.object(web_app.settings, "AC", temp_dir):
                    client = TestClient(web_app.app)
                    with patch.object(web_app.common, "APP_SECRET", "old-session-secret"):
                        login = client.post(
                            "/api/login",
                            data={"username": "admin", "password": "admin"},
                            headers={"X-Requested-With": "XMLHttpRequest"},
                        )
                        self.assertEqual(login.status_code, 200)
                        headers = {"X-PicSyncra-CSRF": login.json()["csrf_token"]}

                        def fake_update_settings(_payload):
                            web_app.common.APP_SECRET = "new-session-secret"
                            return {"version": "test", "processing": {}}

                        with patch.object(
                            web_app, "update_settings", side_effect=fake_update_settings
                        ):
                            response = client.post(
                                "/api/settings",
                                json={"app": {"app_secret": "new-session-secret"}},
                                headers=headers,
                            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["session_invalidated"])
            self.assertIn("Zaloguj", payload["session_message"])
        finally:
            if previous is None:
                os.environ.pop("PICSYNCRA_WEB_AUTH", None)
            else:
                os.environ["PICSYNCRA_WEB_AUTH"] = previous


if __name__ == "__main__":
    unittest.main()
