"""Staged, validated import of one pre-rebrand data profile into SQLite."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from .legacy_import import ENTRY_RECORDS_KEY, _read_workbook_payload, import_legacy_to_sqlite
from .legacy_profile import LegacyProfile
from .sqlite_store import LIST_SHEETS, SqliteStore


_SAFE_BOOTSTRAP_KEYS = ("language", "app_secret", "sqlite_backup")
_PASSWORD_ALGORITHM = "pbkdf2_sha256"


class LegacyProfileValidationError(ValueError):
    """Raised when a selected profile cannot be imported without losing data."""


@dataclass(frozen=True)
class LegacyProfileImportReport:
    """Non-sensitive import result used by the publishing transaction and UI."""

    source_root: Path
    source_names: tuple[str, ...]
    component_counts: dict[str, int]
    bootstrap_settings: dict[str, object]

    def public_dict(self) -> dict[str, object]:
        return {
            "source_root": str(self.source_root),
            "source_names": list(self.source_names),
            "component_counts": dict(self.component_counts),
        }


@dataclass(frozen=True)
class _SourcePayloads:
    config: dict[str, object] | None
    lists: dict[str, object] | None
    users: list[dict[str, object]] | None
    history: list[dict[str, object]] | None
    file_index: dict[str, object] | None
    bootstrap_settings: dict[str, object]


def _read_json_file(path: Path, *, expected_type: type, label: str) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LegacyProfileValidationError(f"Niepoprawny plik {label}.") from exc
    if not isinstance(payload, expected_type):
        raise LegacyProfileValidationError(f"Plik {label} ma niepoprawny format.")
    return payload


def _is_supported_password_hash(value: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = value.split(":", 3)
        if algorithm != _PASSWORD_ALGORITHM or int(iterations_raw) < 1:
            return False
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        digest = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False
    return bool(salt and digest)


def _validate_account_records(
    payload: list[object],
    *,
    label: str,
    require_admin: bool,
) -> list[dict[str, object]]:
    users: list[dict[str, object]] = []
    usernames: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise LegacyProfileValidationError(f"{label} zawiera niepoprawne konto.")
        username_value = item.get("username")
        password_hash_value = item.get("password_hash")
        role_value = item.get("role", "user")
        enabled_value = item.get("enabled", True)
        username = username_value.strip() if isinstance(username_value, str) else ""
        password_hash = password_hash_value.strip() if isinstance(password_hash_value, str) else ""
        role = role_value.strip().lower() if isinstance(role_value, str) else ""
        key = username.casefold()
        if (
            not username
            or key in usernames
            or role not in {"admin", "user"}
            or not isinstance(enabled_value, bool)
            or not _is_supported_password_hash(password_hash)
        ):
            raise LegacyProfileValidationError(f"{label} zawiera niepoprawne konto.")
        usernames.add(key)
        users.append(dict(item))
    if not users:
        if require_admin:
            raise LegacyProfileValidationError(
                f"{label} nie zawiera uzywalnego konta administratora."
            )
        raise LegacyProfileValidationError(f"{label} nie zawiera zadnego konta.")
    if require_admin and not any(
        str(item.get("role") or "").strip().lower() == "admin"
        and item.get("enabled", True) is True
        for item in users
    ):
        raise LegacyProfileValidationError(f"{label} nie zawiera uzywalnego konta administratora.")
    return users


def _validate_users(payload: list[object]) -> list[dict[str, object]]:
    return _validate_account_records(
        payload,
        label="Plik web_users.json",
        require_admin=False,
    )


def _validate_history(payload: list[object]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    record_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise LegacyProfileValidationError("Plik web_history.json zawiera niepoprawny wpis.")
        record_id = item.get("id")
        normalized_id = record_id.strip() if isinstance(record_id, str) else ""
        if not normalized_id or normalized_id in record_ids:
            raise LegacyProfileValidationError("Plik web_history.json zawiera niepoprawny wpis.")
        record_ids.add(normalized_id)
        records.append(dict(item))
    return records


def _read_lists_file(path: Path) -> dict[str, object]:
    try:
        return _read_workbook_payload(path)
    except Exception as exc:
        raise LegacyProfileValidationError("Niepoprawny plik lists.xlsx.") from exc


def _load_source_payloads(profile: LegacyProfile) -> _SourcePayloads:
    source = profile.root
    config_path = source / "config.json"
    lists_path = source / "lists.xlsx"
    users_path = source / "web_users.json"
    history_path = source / "web_history.json"
    index_path = source / "file_index.json"
    settings_path = source / "local_settings.json"

    config = (
        _read_json_file(config_path, expected_type=dict, label="config.json")
        if config_path.is_file()
        else None
    )
    lists = _read_lists_file(lists_path) if lists_path.is_file() else None
    raw_users = (
        _read_json_file(users_path, expected_type=list, label="web_users.json")
        if users_path.is_file()
        else None
    )
    users = _validate_users(raw_users) if raw_users is not None else None
    raw_history = (
        _read_json_file(history_path, expected_type=list, label="web_history.json")
        if history_path.is_file()
        else None
    )
    history = _validate_history(raw_history) if raw_history is not None else None
    file_index = (
        _read_json_file(index_path, expected_type=dict, label="file_index.json")
        if index_path.is_file()
        else None
    )
    raw_settings = (
        _read_json_file(settings_path, expected_type=dict, label="local_settings.json")
        if settings_path.is_file()
        else {}
    )
    bootstrap_settings: dict[str, object] = {}
    for key in _SAFE_BOOTSTRAP_KEYS:
        if key not in raw_settings:
            continue
        value = raw_settings[key]
        if key in {"language", "app_secret"} and not isinstance(value, str):
            raise LegacyProfileValidationError(f"Plik local_settings.json ma niepoprawne pole {key}.")
        if key == "sqlite_backup" and not isinstance(value, dict):
            raise LegacyProfileValidationError("Plik local_settings.json ma niepoprawne pole sqlite_backup.")
        bootstrap_settings[key] = value
    return _SourcePayloads(config, lists, users, history, file_index, bootstrap_settings)


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = None
    destination_connection = None
    try:
        source_connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(str(destination))
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise LegacyProfileValidationError("Stara baza SQLite nie przeszla kontroli spojnosci.")
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()


def _deep_contains(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _deep_contains(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


def _validate_staged_data(
    database_path: Path,
    payloads: _SourcePayloads,
    import_result: dict[str, object],
    *,
    require_web_admin: bool,
) -> None:
    store = SqliteStore(str(database_path))
    if payloads.config is not None and not _deep_contains(store.load_config(), payloads.config):
        raise LegacyProfileValidationError("Nie zweryfikowano konfiguracji w nowej SQLite.")
    if payloads.lists is not None:
        actual_lists = store.load_lists()
        for sheet in LIST_SHEETS:
            expected_values = payloads.lists.get(sheet, [])
            actual_values = actual_lists.get(sheet, [])
            if not isinstance(expected_values, list) or not all(
                value in actual_values for value in expected_values
            ):
                raise LegacyProfileValidationError("Nie zweryfikowano list w nowej SQLite.")
        expected_entries = payloads.lists.get(ENTRY_RECORDS_KEY, [])
        actual_entries = actual_lists.get(ENTRY_RECORDS_KEY, [])
        if not isinstance(expected_entries, list) or not all(
            entry in actual_entries for entry in expected_entries
        ):
            raise LegacyProfileValidationError("Nie zweryfikowano list w nowej SQLite.")
    actual_user_records = store.load_users()
    if require_web_admin:
        _validate_account_records(
            actual_user_records,
            label="Nowa SQLite",
            require_admin=True,
        )
    if payloads.users is not None:
        actual_users = {
            str(item.get("username") or "").casefold(): item for item in actual_user_records
        }
        for expected in payloads.users:
            username = str(expected["username"])
            actual = actual_users.get(username.casefold())
            if actual != expected:
                raise LegacyProfileValidationError("Nie zweryfikowano kont w nowej SQLite.")
    if payloads.history is not None:
        actual_history_ids = {
            str(item.get("id") or "") for item in store.load_history()
        }
        expected_history_ids = {
            str(item.get("id") or "") for item in payloads.history if item.get("id")
        }
        if expected_history_ids and not expected_history_ids.issubset(actual_history_ids):
            raise LegacyProfileValidationError("Nie zweryfikowano historii w nowej SQLite.")
    if payloads.file_index is not None and payloads.file_index:
        if not _deep_contains(store.load_file_index_cache(), payloads.file_index):
            raise LegacyProfileValidationError("Nie zweryfikowano indeksu plikow w nowej SQLite.")
    if not isinstance(import_result.get("lists"), int) or not isinstance(
        import_result.get("entries"), int
    ):
        raise LegacyProfileValidationError("Nie zweryfikowano list w nowej SQLite.")


def _remove_staging_database(database_path: Path) -> None:
    for path in (database_path, *(database_path.with_name(database_path.name + suffix) for suffix in ("-wal", "-shm"))):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def stage_legacy_profile_import(
    profile: LegacyProfile,
    staged_database_path: Path,
) -> LegacyProfileImportReport:
    """Create and validate a new SQLite database without touching active settings."""

    payloads = _load_source_payloads(profile)
    staging = Path(staged_database_path)
    if staging.exists():
        raise LegacyProfileValidationError("Robocza baza SQLite juz istnieje.")
    try:
        if profile.sqlite_path is not None:
            _copy_sqlite_database(profile.sqlite_path, staging)
        import_result = import_legacy_to_sqlite(
            str(profile.root),
            str(staging),
            merge_existing=profile.has_sqlite,
        )
        _validate_staged_data(
            staging,
            payloads,
            import_result,
            require_web_admin=profile.has_sqlite or payloads.users is not None,
        )
    except Exception:
        _remove_staging_database(staging)
        raise
    component_counts = {
        "config": int(payloads.config is not None),
        "lists": int(import_result.get("lists") or 0),
        "entries": int(import_result.get("entries") or 0),
        "users": len(SqliteStore(str(staging)).load_users()),
        "history": len(payloads.history or []),
        "file_index": int(payloads.file_index is not None),
        "bootstrap_settings": len(payloads.bootstrap_settings),
    }
    return LegacyProfileImportReport(
        source_root=profile.root,
        source_names=profile.manifest.source_names,
        component_counts=component_counts,
        bootstrap_settings=payloads.bootstrap_settings,
    )
