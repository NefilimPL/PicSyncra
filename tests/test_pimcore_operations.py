from concurrent.futures import Future

from picsyncra.pimcore_operations import PimcoreOperationRegistry
from picsyncra.services.pimcore_service import PimcoreApiError, run_test_create


class ImmediateExecutor:
    def submit(self, callback, *args, **kwargs):
        future = Future()
        try:
            future.set_result(callback(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


def test_registry_numbers_events_and_returns_only_new_entries():
    persisted = []
    registry = PimcoreOperationRegistry(executor=ImmediateExecutor())

    def worker(emit):
        emit("validate", "info", "Walidacja")
        emit("create", "success", "Utworzono", object_id=42, elapsed_ms=11)
        return {"status": "completed", "object_id": 42}

    started = registry.start(
        operation_type="test",
        username="admin",
        values={"EAN": "5904804578169"},
        cleanup_policy="keep",
        worker=worker,
        persist=persisted.append,
    )
    first = registry.status(started["operation_id"], after_sequence=0)
    second = registry.status(started["operation_id"], after_sequence=1)

    assert [item["sequence"] for item in first["events"]] == [1, 2, 3, 4]
    assert [item["sequence"] for item in second["events"]] == [2, 3, 4]
    assert first["status"] == "completed"
    assert first["total_ms"] >= 0
    assert persisted[0]["operation_id"] == started["operation_id"]


def test_registry_redacts_secrets_from_values_events_and_results():
    persisted = []
    registry = PimcoreOperationRegistry(executor=ImmediateExecutor())
    started = registry.start(
        operation_type="test",
        username="admin",
        values={"EAN": "5904804578169", "api_key": "never-store"},
        cleanup_policy="keep",
        worker=lambda emit: (
            emit("request", "info", "Wysylanie", authorization="Bearer never-store")
            or {"status": "completed", "cookie": "never-store"}
        ),
        persist=persisted.append,
    )

    report = registry.status(started["operation_id"])

    assert report["values"]["api_key"] == "[REDACTED]"
    assert report["events"][1]["authorization"] == "[REDACTED]"
    assert report["result"]["cookie"] == "[REDACTED]"


def test_registry_redacts_manual_update_operations():
    persisted = []
    registry = PimcoreOperationRegistry(executor=ImmediateExecutor())
    started = registry.start(
        operation_type="manual_update",
        username="operator",
        values={"EAN": "5904804578169", "api_key": "never-store"},
        cleanup_policy="",
        worker=lambda emit: (
            emit("update", "info", "PUT", authorization="Bearer never-store")
            or {"status": "completed", "secret": "never-store"}
        ),
        persist=persisted.append,
    )

    report = registry.status(started["operation_id"])

    assert report["operation_type"] == "manual_update"
    assert report["values"]["api_key"] == "[REDACTED]"
    assert report["events"][1]["authorization"] == "[REDACTED]"
    assert report["result"]["secret"] == "[REDACTED]"


class PimcoreTestClient:
    def __init__(self, *, delete_error=None):
        self.deleted = []
        self.delete_error = delete_error

    def server_info(self):
        return {"data": {"version": "6.6.11"}}

    def classes(self):
        return {"data": [{"id": 1, "name": "Product"}]}

    def class_definition(self, class_id):
        return {"data": {"children": [{"fieldtype": "input", "name": "EAN"}]}}

    def object_list(self, query_filter=None, object_class="", limit=2, offset=0):
        assert object_class == "Product"
        assert query_filter in (
            {"EAN": "0000000000000"},
            {"EAN": "5904804578169"},
        )
        return {"data": []}

    def create_object(self, payload):
        assert payload["published"] is False
        return {"data": {"id": 77}}

    def object_by_id(self, object_id):
        return {
            "data": {
                "id": object_id,
                "fullPath": "/Produkty/test-77",
                "elements": [{"name": "EAN", "value": "5904804578169"}],
            }
        }

    def delete_object(self, object_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(object_id)
        return {"success": True}


def test_delete_cleanup_creates_verifies_and_deletes():
    events = []
    result = run_test_create(
        {
            "base_url": "http://pimcore.test",
            "api_key": "test-key",
            "class_name": "Product",
            "parent_id": "123",
            "object_key_template": "{EAN}",
            "field_mappings": [
                {
                    "source": "EAN",
                    "pimcore_field": "EAN",
                    "type": "input",
                    "required": True,
                    "parser": "text",
                }
            ],
        },
        {"EAN": "5904804578169"},
        "delete",
        client=PimcoreTestClient(),
        emit=lambda stage, severity, message, **details: events.append(
            {"stage": stage, **details}
        ),
    )

    assert result["status"] == "completed"
    assert result["object_id"] == 77
    assert result["object_path"] == "/Produkty/test-77"
    assert result["cleanup_result"] == "deleted"
    stages = [event["stage"] for event in events]
    assert "preflight" in stages
    assert stages[-6:] == ["validate", "payload", "duplicate_check", "create", "verify", "delete"]


def test_delete_failure_is_partial_and_keeps_manual_cleanup_identity():
    error = PimcoreApiError(
        "Brak uprawnienia delete.",
        "/webservice/rest/object/id/77",
        status_code=403,
        kind="http",
    )

    result = run_test_create(
        {
            "base_url": "http://pimcore.test",
            "api_key": "test-key",
            "class_name": "Product",
            "parent_id": "123",
            "object_key_template": "{EAN}",
            "field_mappings": [
                {
                    "source": "EAN",
                    "pimcore_field": "EAN",
                    "type": "input",
                    "required": True,
                    "parser": "text",
                }
            ],
        },
        {"EAN": "5904804578169"},
        "delete",
        client=PimcoreTestClient(delete_error=error),
        emit=lambda *args, **kwargs: None,
    )

    assert result["status"] == "partial"
    assert result["cleanup_result"] == "delete_failed"
    assert result["object_id"] == 77
    assert result["object_key"] == "5904804578169"
    assert result["object_path"] == "/Produkty/test-77"


def test_fetch_failure_is_partial_but_still_runs_selected_delete():
    class FetchFailureClient(PimcoreTestClient):
        def object_by_id(self, object_id):
            if str(object_id) == "123":
                return {"success": True, "data": {"id": 123, "type": "folder"}}
            raise PimcoreApiError(
                "Odczyt kontrolny nie powiodl sie.",
                f"/webservice/rest/object/id/{object_id}",
                status_code=500,
                kind="http",
            )

    client = FetchFailureClient()
    result = run_test_create(
        {
            "base_url": "http://pimcore.test",
            "api_key": "test-key",
            "class_name": "Product",
            "parent_id": "123",
            "object_key_template": "{EAN}",
            "field_mappings": [
                {
                    "source": "EAN",
                    "pimcore_field": "EAN",
                    "type": "input",
                    "required": True,
                    "parser": "text",
                }
            ],
        },
        {"EAN": "5904804578169"},
        "delete",
        client=client,
        emit=lambda *args, **kwargs: None,
    )

    assert result["status"] == "partial"
    assert result["cleanup_result"] == "deleted"
    assert client.deleted == [77]


def test_keep_cleanup_retains_unpublished_object():
    client = PimcoreTestClient()
    result = run_test_create(
        {
            "base_url": "http://pimcore.test",
            "api_key": "test-key",
            "class_name": "Product",
            "parent_id": "123",
            "object_key_template": "{EAN}",
            "field_mappings": [
                {
                    "source": "EAN",
                    "pimcore_field": "EAN",
                    "type": "input",
                    "required": True,
                    "parser": "text",
                }
            ],
        },
        {"EAN": "5904804578169"},
        "keep",
        client=client,
        emit=lambda *args, **kwargs: None,
    )

    assert result["status"] == "completed"
    assert result["cleanup_result"] == "kept"
    assert client.deleted == []
