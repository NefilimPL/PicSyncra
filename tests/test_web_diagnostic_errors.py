from __future__ import annotations

import picsyncra.web_data as web_data


def test_local_diagnostics_hide_filesystem_exception_details(monkeypatch) -> None:
    diagnostic_secret = "LOCAL_DIAGNOSTIC_SECRET"
    logged: list[str] = []

    def fail_to_create_directory(*_args, **_kwargs) -> None:
        raise RuntimeError(diagnostic_secret)

    monkeypatch.setattr(web_data.os, "makedirs", fail_to_create_directory)
    monkeypatch.setattr(web_data, "log_error", logged.append)

    result = web_data.test_local_paths()

    assert result["ok"] is False
    assert all(
        item["error"] == "Nie udalo sie sprawdzic folderu lokalnego."
        for item in result["checks"]
    )
    assert diagnostic_secret not in str(result)
    assert all(diagnostic_secret not in message for message in logged)


def test_ftp_diagnostics_hide_connection_exception_details(monkeypatch) -> None:
    diagnostic_secret = "FTP_DIAGNOSTIC_SECRET"
    logged: list[str] = []

    def fail_to_list_files(*_args, **_kwargs) -> None:
        raise RuntimeError(diagnostic_secret)

    monkeypatch.setattr(web_data.config, "CONFIG", {web_data.ft: True, web_data.H: {}})
    monkeypatch.setattr(web_data, "list_remote_files_for_ean", fail_to_list_files)
    monkeypatch.setattr(web_data, "log_error", logged.append)

    result = web_data.test_ftp_connection()

    assert result == {
        "ok": False,
        "message": "Nie udalo sie polaczyc z FTP. Sprawdz konfiguracje i log serwera.",
    }
    assert diagnostic_secret not in str(result)
    assert all(diagnostic_secret not in message for message in logged)


def test_sql_diagnostics_hide_connection_exception_details(monkeypatch) -> None:
    diagnostic_secret = "SQL_DIAGNOSTIC_SECRET"
    logged: list[str] = []

    def fail_to_connect() -> None:
        raise RuntimeError(diagnostic_secret)

    monkeypatch.setattr(web_data, "connect_db", fail_to_connect)
    monkeypatch.setattr(web_data, "log_error", logged.append)

    result = web_data.test_sql_connection()

    assert result == {
        "ok": False,
        "message": "Nie udalo sie polaczyc z SQL. Sprawdz konfiguracje i log serwera.",
    }
    assert diagnostic_secret not in str(result)
    assert all(diagnostic_secret not in message for message in logged)


def test_sql_profile_diagnostics_hide_connection_exception_details(monkeypatch) -> None:
    diagnostic_secret = "SQL_PROFILE_DIAGNOSTIC_SECRET"
    logged: list[str] = []

    def fail_to_connect(*_args, **_kwargs) -> None:
        raise RuntimeError(diagnostic_secret)

    monkeypatch.setattr(web_data, "resolve_sql_profile", lambda *_args: {"id": "reporting"})
    monkeypatch.setattr(web_data, "connect_profile", fail_to_connect)
    monkeypatch.setattr(web_data, "log_error", logged.append)

    result = web_data.test_sql_profile_connection("reporting")

    assert result == {
        "ok": False,
        "message": "Nie udalo sie polaczyc z SQL. Sprawdz konfiguracje i log serwera.",
    }
    assert diagnostic_secret not in str(result)
    assert all(diagnostic_secret not in message for message in logged)
