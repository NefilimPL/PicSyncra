"""The base installed package has a fixed, safe component layout."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from picsyncra.installation.setup_cli import (
    PRODUCT_APP_ID,
    build_installer_layout,
    main,
)


def test_base_installer_contains_required_apps_but_not_ocr_or_local() -> None:
    """Catches shipping the optional LOCAL or OCR runtime in every base install."""

    layout = build_installer_layout(include_local=False)

    assert layout.product_app_id == PRODUCT_APP_ID
    assert layout.required_components == ("web", "migrator")
    assert layout.optional_components == ()
    assert layout.downloadable_components == ("ocr",)
    assert layout.autostart_enabled is False


def test_inno_leaves_local_unchecked_in_the_default_install_type() -> None:
    """Catches selecting LOCAL merely because the default type is chosen."""

    installer = (
        Path(__file__).resolve().parents[1] / "installer" / "PicSyncra.iss"
    ).read_text(encoding="utf-8")

    assert 'Name: "custom"; Description: "Wybór składników"; Flags: iscustom' in installer
    assert 'Name: "local"; Description: "Wersja lokalna (opcjonalna)"' in installer
    assert 'Name: "local"; Description: "Wersja lokalna (opcjonalna)"; Types:' not in installer


def test_local_is_opt_in_without_changing_the_required_base_components() -> None:
    """Catches selecting LOCAL from removing WEB or Migrator from the installation."""

    layout = build_installer_layout(include_local=True)

    assert layout.required_components == ("web", "migrator")
    assert layout.optional_components == ("local",)
    assert layout.downloadable_components == ("ocr",)


def test_inno_base_package_uses_the_setup_mutex_and_preserves_machine_data() -> None:
    """Catches a base package that races another setup or deletes state on uninstall."""

    installer = (
        Path(__file__).resolve().parents[1] / "installer" / "PicSyncra.iss"
    ).read_text(encoding="utf-8")

    assert "SetupMutex=Global\\PicSyncra.Setup" in installer
    assert "CreateMutex(" not in installer
    assert "{commonappdata}\\PicSyncra\\primary-installation\\config" in installer
    assert "{commonappdata}\\PicSyncra\\primary-installation\\data" in installer
    assert "Flags: uninsneveruninstall" in installer
    assert 'Subkey: "SOFTWARE\\PicSyncra\\Installations\\primary-installation"' in installer
    assert "uninsdeletekey" in installer


def test_installed_build_always_bundles_local_for_the_optional_component() -> None:
    """Catches offering LOCAL in Inno while omitting its files from the package."""

    build_script = (
        Path(__file__).resolve().parents[1] / "installer" / "build_installer.ps1"
    ).read_text(encoding="utf-8")

    assert "Build-Onedir 'PicSyncra' 'PicSyncra.pyw'" in build_script
    assert "if ($IncludeLocal)" not in build_script


def test_installed_build_keeps_pyinstaller_specs_as_versioned_source_files() -> None:
    """Catches a blanket ignore rule silently removing installer build inputs."""

    root = Path(__file__).resolve().parents[1]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    build_script = (root / "installer" / "build_installer.ps1").read_text(encoding="utf-8")

    assert (root / "installer" / "installed.spec").is_file()
    assert (root / "installer" / "ocr.spec").is_file()
    assert "!installer/installed.spec" in ignored
    assert "!installer/ocr.spec" in ignored
    assert "installer/installed.spec" in build_script
    assert "installer/ocr.spec" in build_script


def test_inno_collects_database_and_optional_config_through_protected_requests() -> None:
    """Catches silently discarding the selected database/configuration at install time."""

    installer = (
        Path(__file__).resolve().parents[1] / "installer" / "PicSyncra.iss"
    ).read_text(encoding="utf-8")

    assert "CreateInputFilePage" in installer
    assert "CreateInputDirPage" in installer
    assert "SelectedDatabasePath" in installer
    assert 'ValueData: "{code:SelectedDatabasePath}"' in installer
    assert "PicSyncra-SetupHelper.exe" in installer
    assert "RunSetupHelper('import-config', RequestJson)" in installer


def test_inno_json_escaping_mutates_the_request_text_not_the_change_count() -> None:
    """Catches serialising the integer returned by Inno's StringChangeEx."""

    installer = (
        Path(__file__).resolve().parents[1] / "installer" / "PicSyncra.iss"
    ).read_text(encoding="utf-8")

    assert "Result := StringChangeEx" not in installer
    assert "StringChangeEx(Result, '\\', '\\\\', True)" in installer


def test_import_config_cli_reads_secret_material_only_from_a_request_file(
    tmp_path: Path,
) -> None:
    """Catches placing a configuration secret or source path in process arguments."""

    source = tmp_path / "portable-config"
    source.mkdir()
    (source / "local_settings.json").write_text(
        json.dumps({"app_secret": "test-secret"}), encoding="utf-8"
    )
    destination = tmp_path / "installed" / "config"
    request = tmp_path / "protected-request.json"
    request.write_text(
        json.dumps(
            {
                "source_config_root": str(source),
                "destination_config_root": str(destination),
            }
        ),
        encoding="utf-8",
    )

    assert main(["import-config", "--request", str(request)]) == 0

    from picsyncra.common import _decode_local_secret

    copied_settings = json.loads(
        (destination / "local_settings.json").read_text(encoding="utf-8")
    )
    assert _decode_local_secret(copied_settings["app_secret"], "missing") == "test-secret"


def test_inspect_cli_reports_existing_database_without_exposing_its_path(
    tmp_path: Path, capsys
) -> None:
    """Catches the installer starting migrations just to inspect a selected database."""

    database = tmp_path / "existing.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER)")
        connection.execute("INSERT INTO schema_version VALUES (7)")
        connection.execute("CREATE TABLE app_config_values (key TEXT, value TEXT)")
    request = tmp_path / "inspect-request.json"
    request.write_text(json.dumps({"database_path": str(database)}), encoding="utf-8")

    assert main(["inspect", "--request", str(request)]) == 0

    response = json.loads(capsys.readouterr().out)
    assert response == {
        "ok": True,
        "database": {"schema_version": 7, "integrity_ok": True, "is_picsyncra": True},
    }


def test_inspect_cli_reports_a_corrupt_database_as_a_safe_setup_failure(
    tmp_path: Path, capsys
) -> None:
    """Catches a raw SQLite traceback escaping from the installer helper."""

    database = tmp_path / "corrupt.sqlite"
    database.write_bytes(b"not a sqlite database")
    request = tmp_path / "inspect-request.json"
    request.write_text(json.dumps({"database_path": str(database)}), encoding="utf-8")

    assert main(["inspect", "--request", str(request)]) == 1

    error_text = capsys.readouterr().err
    assert str(database) not in error_text
    assert "Setup helper failed:" in error_text
