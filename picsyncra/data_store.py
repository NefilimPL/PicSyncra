"""Active application data store resolver."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from . import storage_settings
from .product_queries import (
    ProductSearchCriteria,
    filter_product_records,
    product_record_matches,
)
from .sqlite_store import SqliteStore

_ACTIVE_STORE = None
_ACTIVE_STORE_KEY: tuple[str, str] | None = None
_STORE_REGISTRY_LOCK = threading.RLock()
_SQLITE_STORES: dict[str, SqliteStore] = {}


def get_sqlite_store(database_path: str) -> SqliteStore:
    """Return the initialized SQLite store registered for a canonical path."""

    key = str(Path(database_path).resolve())
    with _STORE_REGISTRY_LOCK:
        store = _SQLITE_STORES.get(key)
        if store is None:
            store = SqliteStore(key)
            store.initialize()
            _SQLITE_STORES[key] = store
        return store


class LegacyDataStore:
    """Marker adapter for the existing file-backed behavior."""

    mode = storage_settings.DATA_MODE_LEGACY

    def load_config(self) -> dict[str, Any]:
        return {}

    def save_config(self, _payload: dict[str, object]) -> None:
        return None

    @staticmethod
    def _product_records() -> list[dict[str, str]]:
        """Read the Excel record cache without retaining a workbook handle."""

        from .excel_utils import ENTRY_RECORDS_KEY, prepare_excel_lists

        payload = prepare_excel_lists()
        records = payload.get(ENTRY_RECORDS_KEY, [])
        return records if isinstance(records, list) else []

    def get_product_by_ean(self, ean: str):
        matches = self.search_product_entries(ProductSearchCriteria(ean=ean), limit=1)
        return matches[0] if matches else None

    def get_product_by_id(self, product_id: str):
        matches = self.search_product_entries(
            ProductSearchCriteria(product_id=product_id), limit=1
        )
        return matches[0] if matches else None

    def search_product_entries(
        self, criteria: ProductSearchCriteria, limit: int = 50
    ) -> list[dict[str, str]]:
        return filter_product_records(self._product_records(), criteria, limit=limit)

    def suggest_product_field(
        self,
        field: str,
        prefix: str,
        context: dict[str, str],
        limit: int = 20,
    ) -> list[str]:
        from .excel_utils import (
            COLOR1_HEADER,
            COLOR2_HEADER,
            COLOR3_HEADER,
            EAN_HEADER,
            EXTRA_HEADER,
            MODEL_HEADER,
            NAME_HEADER,
            PRODUCT_ID_HEADER,
            TYPE_HEADER,
        )

        headers = {
            "product_id": PRODUCT_ID_HEADER,
            "ean": EAN_HEADER,
            "name": NAME_HEADER,
            "type_name": TYPE_HEADER,
            "model": MODEL_HEADER,
            "color1": COLOR1_HEADER,
            "color2": COLOR2_HEADER,
            "color3": COLOR3_HEADER,
            "extra": EXTRA_HEADER,
        }
        header = headers.get(field)
        if header is None:
            return []
        criteria = ProductSearchCriteria(
            product_id=str(context.get("product_id") or ""),
            ean=str(context.get("ean") or ""),
            name=str(context.get("name") or ""),
            type_name=str(context.get("type_name") or ""),
            model=str(context.get("model") or ""),
        )
        values = []
        seen = set()
        normalized_prefix = str(prefix or "").strip().casefold()
        bounded_limit = max(1, min(int(limit), 100))
        for record in self._product_records():
            if not product_record_matches(record, criteria):
                continue
            value = str(record.get(header) or "").strip()
            normalized_value = value.casefold()
            if (
                not value
                or not normalized_value.startswith(normalized_prefix)
                or normalized_value in seen
            ):
                continue
            seen.add(normalized_value)
            values.append(value)
            if len(values) == bounded_limit:
                break
        return values


class SqliteDataStoreAdapter:
    """Adapter exposing SQLite persistence through the active store API."""

    mode = storage_settings.DATA_MODE_SQLITE
    supports_atomic_incident_event = True
    supports_notification_outbox = True

    def __init__(self, database_path: str):
        self.database_path = database_path
        self.store = get_sqlite_store(database_path)

    def load_config(self) -> dict[str, Any]:
        return self.store.load_config()

    def save_config(self, payload: dict[str, object]) -> None:
        self.store.save_config(payload)

    def load_lists(self) -> dict[str, Any]:
        return self.store.load_lists()

    def get_product_by_ean(self, ean: str):
        return self.store.get_product_by_ean(ean)

    def get_product_by_id(self, product_id: str):
        return self.store.get_product_by_id(product_id)

    def search_product_entries(
        self, criteria: ProductSearchCriteria, limit: int = 50
    ):
        return self.store.search_product_entries(criteria, limit=limit)

    def suggest_product_field(
        self,
        field: str,
        prefix: str,
        context: dict[str, str],
        limit: int = 20,
    ):
        return self.store.suggest_product_field(
            field,
            prefix,
            context,
            limit=limit,
        )

    def save_lists(self, payload: dict[str, object]) -> None:
        self.store.save_lists(payload)

    def add_list_value(self, sheet: str, value: object) -> bool:
        return self.store.add_list_value(sheet, value)

    def remove_list_value(self, sheet: str, value: object) -> None:
        self.store.remove_list_value(sheet, value)

    def find_list_value_usage(
        self, sheet: str, value: object, *, limit: int = 100
    ) -> list[dict[str, str]]:
        return self.store.find_list_value_usage(sheet, value, limit=limit)

    def save_product_entry(self, payload: dict[str, object]) -> dict[str, Any]:
        return self.store.save_product_entry(payload)

    def load_users(self) -> list[dict[str, Any]]:
        return self.store.load_users()

    def save_users(self, users: list[dict[str, object]]) -> None:
        self.store.save_users(users)

    def load_history(self) -> list[dict[str, Any]]:
        return self.store.load_history()

    def save_history(self, records: list[dict[str, object]]) -> None:
        self.store.save_history(records)

    def append_history(self, record: dict[str, object]) -> None:
        self.store.append_history(record)

    def append_operational_event(
        self,
        event: dict[str, object],
        *,
        create_notification_intent: bool = False,
    ) -> dict[str, Any]:
        return self.store.append_operational_event(
            event, create_notification_intent=create_notification_intent
        )

    def query_operational_events(
        self,
        *,
        severities=(),
        username: str = "",
        ean: str = "",
        job_id: str = "",
        correlation_id: str = "",
        module: str = "",
        query: str = "",
        after_id: str = "",
        cursor: str = "",
        limit: int = 20,
        since: str = "",
    ) -> dict[str, Any]:
        return self.store.query_operational_events(
            severities=severities,
            username=username,
            ean=ean,
            job_id=job_id,
            correlation_id=correlation_id,
            module=module,
            query=query,
            after_id=after_id,
            cursor=cursor,
            limit=limit,
            since=since,
        )

    def upsert_job_run(self, job: dict[str, object]) -> dict[str, Any]:
        return self.store.upsert_job_run(job)

    def query_job_runs(
        self, *, cursor: str = "", limit: int = 20
    ) -> dict[str, Any]:
        return self.store.query_job_runs(cursor=cursor, limit=limit)

    def upsert_incident(self, incident: dict[str, object]) -> dict[str, Any]:
        return self.store.upsert_incident(incident)

    def find_open_incident(self, fingerprint: str) -> dict[str, Any] | None:
        return self.store.find_open_incident(fingerprint)

    def coalesce_incident(
        self,
        occurrence: dict[str, object],
        notification_window_seconds: int = 15 * 60,
        source_event: dict[str, object] | None = None,
        create_notification_intent: bool = False,
    ) -> dict[str, Any]:
        return self.store.coalesce_incident(
            occurrence,
            notification_window_seconds=notification_window_seconds,
            source_event=source_event,
            create_notification_intent=create_notification_intent,
        )

    def query_incidents(
        self, *, severity: str = "", cursor: str = "", limit: int = 20
    ) -> dict[str, Any]:
        return self.store.query_incidents(
            severity=severity, cursor=cursor, limit=limit
        )

    def query_incident_context(
        self,
        incident_id: str,
        *,
        problem_cursor: str = "",
        problem_limit: int = 20,
        before_limit: int = 5,
        after_limit: int = 5,
    ) -> dict[str, Any] | None:
        return self.store.query_incident_context(
            incident_id,
            problem_cursor=problem_cursor,
            problem_limit=problem_limit,
            before_limit=before_limit,
            after_limit=after_limit,
        )

    def release_incident_notification(
        self,
        incident_id: str,
        *,
        claimed_at: str,
        previous_at: str,
    ) -> bool:
        return self.store.release_incident_notification(
            incident_id,
            claimed_at=claimed_at,
            previous_at=previous_at,
        )

    def enqueue_notification_delivery(
        self, record: dict[str, object]
    ) -> dict[str, Any]:
        return self.store.enqueue_notification_delivery(record)

    def pending_notification_intents(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.pending_notification_intents(limit=limit)

    def notification_intent_context(
        self, intent_id: str
    ) -> dict[str, Any] | None:
        return self.store.notification_intent_context(intent_id)

    def materialize_notification_intent(
        self,
        intent_id: str,
        *,
        delivery: dict[str, object] | None,
        completed_at: str,
    ) -> dict[str, Any]:
        return self.store.materialize_notification_intent(
            intent_id, delivery=delivery, completed_at=completed_at
        )

    def prune_done_notification_intents(self, before: str) -> int:
        return self.store.prune_done_notification_intents(before)

    def pending_notification_deliveries(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.store.pending_notification_deliveries(limit=limit)

    def next_notification_due_at(self) -> str:
        return self.store.next_notification_due_at()

    def update_notification_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        used_channel: str = "",
        attempts=None,
        updated_at: str,
        next_attempt_at: str = "",
    ) -> dict[str, Any]:
        return self.store.update_notification_delivery(
            delivery_id,
            status=status,
            used_channel=used_channel,
            attempts=attempts,
            updated_at=updated_at,
            next_attempt_at=next_attempt_at,
        )

    def query_notification_deliveries(
        self, *, incident_id: str = "", cursor: str = "", limit: int = 20
    ) -> dict[str, Any]:
        return self.store.query_notification_deliveries(
            incident_id=incident_id,
            cursor=cursor,
            limit=limit,
        )

    def notification_deliveries_for_incidents(
        self, incident_ids: list[str], *, per_incident_limit: int = 5
    ) -> list[dict[str, Any]]:
        return self.store.notification_deliveries_for_incidents(
            incident_ids, per_incident_limit=per_incident_limit
        )

    def mark_alerts_read(
        self, username: str, severity: str, event_id: str, created_at: str
    ) -> None:
        self.store.mark_alerts_read(username, severity, event_id, created_at)

    def unread_alert_summary(self, username: str) -> dict[str, object]:
        return self.store.unread_alert_summary(username)

    def prune_info_events(self, before: str) -> int:
        return self.store.prune_info_events(before)

    def clear_operational_data(self) -> dict[str, int]:
        return self.store.clear_operational_data()

    def append_pimcore_submission(self, record: dict[str, object]) -> dict[str, Any]:
        return self.store.append_pimcore_submission(record)

    def query_pimcore_submissions(
        self,
        *,
        operation_type: str = "",
        status: str = "",
        user: str = "",
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self.store.query_pimcore_submissions(
            operation_type=operation_type,
            status=status,
            user=user,
            query=query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    def load_file_index_cache(self) -> dict[str, Any]:
        return self.store.load_file_index_cache()

    def save_file_index_cache(
        self,
        payload: dict[str, object],
        *,
        reused_segment_keys: tuple[str, ...] = (),
    ) -> None:
        self.store.save_file_index_cache(
            payload,
            reused_segment_keys=reused_segment_keys,
        )

    def save_file_index_segments(self, snapshot: dict[str, object]) -> int:
        return self.store.save_file_index_segments(snapshot)

    def load_file_index_segment(self, segment_key: str, section: str, lookup_key: str):
        return self.store.load_file_index_segment(segment_key, section, lookup_key)


def reset_active_store_cache() -> None:
    """Clear the cached active store, mainly for tests and runtime switches."""

    global _ACTIVE_STORE, _ACTIVE_STORE_KEY
    with _STORE_REGISTRY_LOCK:
        _ACTIVE_STORE = None
        _ACTIVE_STORE_KEY = None
        _SQLITE_STORES.clear()


def invalidate_sqlite_store(database_path: str | None = None) -> None:
    """Discard a replaced SQLite store while preserving unrelated stores."""

    global _ACTIVE_STORE, _ACTIVE_STORE_KEY
    with _STORE_REGISTRY_LOCK:
        if database_path is None:
            _SQLITE_STORES.clear()
        else:
            _SQLITE_STORES.pop(str(Path(database_path).resolve()), None)
        if database_path is None or (
            _ACTIVE_STORE_KEY
            and _ACTIVE_STORE_KEY[1] == str(Path(database_path).resolve())
        ):
            _ACTIVE_STORE = None
            _ACTIVE_STORE_KEY = None


def get_active_store():
    """Return the data store selected by bootstrap settings."""

    global _ACTIVE_STORE, _ACTIVE_STORE_KEY
    bootstrap = storage_settings.load_bootstrap_settings()
    mode = storage_settings.normalize_data_mode(
        bootstrap.get(storage_settings.DATA_MODE_KEY)
    )
    database_path = ""
    if mode == storage_settings.DATA_MODE_SQLITE:
        database_path = storage_settings.resolve_sqlite_path(bootstrap)
    key = (mode, database_path)
    with _STORE_REGISTRY_LOCK:
        if _ACTIVE_STORE is not None and _ACTIVE_STORE_KEY == key:
            return _ACTIVE_STORE
        if mode == storage_settings.DATA_MODE_SQLITE:
            _ACTIVE_STORE = SqliteDataStoreAdapter(database_path)
        else:
            _ACTIVE_STORE = LegacyDataStore()
        _ACTIVE_STORE_KEY = key
        return _ACTIVE_STORE


def is_sqlite_mode() -> bool:
    """Return True when SQLite mode is active."""

    return get_active_store().mode == storage_settings.DATA_MODE_SQLITE
