"""Import must leave installed configuration independent of its source."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def importer():
    return importlib.import_module("picsyncra.installation.config_import")


def source_config(tmp_path, *, secret="import-test-secret"):
    source = tmp_path / "portable"
    source.mkdir()
    (source / "local_settings.json").write_text(
        json.dumps({"app_secret": secret, "language": "pl", "base_dir_override": "../photos"}),
        encoding="utf-8",
    )
    (source / "config.json").write_text(
        json.dumps({"ftp": {"host": "example.invalid", "path": "/images"}}),
        encoding="utf-8",
    )
    return source


def test_copied_configuration_survives_removing_source(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    destination = tmp_path / "installed" / "config"
    original = (source / "config.json").read_bytes()

    copied = module.copy_configuration(source, destination)
    shutil.rmtree(source)

    assert set(copied) == {destination / "local_settings.json", destination / "config.json"}
    assert (destination / "config.json").read_bytes() == original
    settings = json.loads((destination / "local_settings.json").read_text(encoding="utf-8"))
    from picsyncra.common import _decode_local_secret

    assert _decode_local_secret(settings["app_secret"], "missing") == "import-test-secret"
    assert Path(settings["base_dir_override"]) == tmp_path / "photos"
    assert settings["language"] == "pl"


def test_import_preserves_encoded_key_and_selected_database(tmp_path):
    from picsyncra.common import _decode_local_secret, _encode_local_secret

    module = importer()
    source = source_config(tmp_path, secret=_encode_local_secret("same-logical-secret"))
    destination = tmp_path / "installed" / "config"
    database = tmp_path / "data" / "existing.sqlite"
    module.copy_configuration(source, destination, database_path=database)
    payload = json.loads((destination / "local_settings.json").read_text(encoding="utf-8"))
    assert _decode_local_secret(payload["app_secret"], "missing") == "same-logical-secret"
    assert payload["data_mode"] == "sqlite"
    assert payload["database_location_mode"] == "custom"
    assert Path(payload["database_path"]) == database


def test_import_copies_explicitly_selected_referenced_file(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    (source / "client.pem").write_bytes(b"test-certificate")
    (source / "config.json").write_text(json.dumps({"tls": {"certificate_file": "client.pem"}}))
    destination = tmp_path / "installed" / "config"
    module.copy_configuration(
        source, destination, file_references=(("config.json", "tls", "certificate_file"),)
    )
    shutil.rmtree(source)
    config = json.loads((destination / "config.json").read_text(encoding="utf-8"))
    reference = Path(config["tls"]["certificate_file"])
    assert reference.is_relative_to(destination)
    assert reference.read_bytes() == b"test-certificate"


@pytest.mark.parametrize("content", ["not json", "[]", '{"app_secret":"enc:!bad!"}'])
def test_invalid_bootstrap_never_publishes_partial_import(tmp_path, content):
    module = importer()
    source = source_config(tmp_path)
    (source / "local_settings.json").write_text(content)
    destination = tmp_path / "installed" / "config"
    with pytest.raises(module.ConfigurationImportError):
        module.copy_configuration(source, destination)
    assert not destination.exists()
    assert (source / "local_settings.json").read_text() == content


def test_existing_destination_is_never_overwritten(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    destination = tmp_path / "installed" / "config"
    destination.mkdir(parents=True)
    (destination / "local_settings.json").write_bytes(b"existing-secret")
    with pytest.raises(FileExistsError):
        module.copy_configuration(source, destination)
    assert (destination / "local_settings.json").read_bytes() == b"existing-secret"


def test_failure_during_file_copy_keeps_source_and_no_destination(tmp_path, monkeypatch):
    module = importer()
    source = source_config(tmp_path)
    (source / "client.pem").write_bytes(b"test-certificate")
    (source / "config.json").write_text(json.dumps({"tls": {"certificate_file": "client.pem"}}))
    destination = tmp_path / "installed" / "config"

    def fail_copy(*args, **kwargs):
        raise OSError("simulated full disk")

    monkeypatch.setattr(module.shutil, "copyfile", fail_copy)
    with pytest.raises(OSError):
        module.copy_configuration(
            source, destination, file_references=(("config.json", "tls", "certificate_file"),)
        )
    assert not destination.exists()
    assert (source / "client.pem").read_bytes() == b"test-certificate"
    assert not list(destination.parent.glob(".config-import-*"))


def test_database_only_import_does_not_claim_secrets_are_available(tmp_path):
    module = importer()
    source = tmp_path / "empty-source"
    source.mkdir()
    destination = tmp_path / "installed" / "config"
    database = tmp_path / "data" / "existing.sqlite"
    module.copy_configuration(source, destination, database_path=database)
    status = module.validate_import(SimpleNamespace(config_root=destination))
    assert status["app_secret"] == "needs_configuration"
    assert status["configuration"] == "needs_configuration"
    assert "secret_v1" not in (destination / "local_settings.json").read_text()


def test_missing_reference_aborts_instead_of_preserving_old_path(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    (source / "config.json").write_text(json.dumps({"tls": {"certificate_file": "missing.pem"}}))
    destination = tmp_path / "installed" / "config"
    with pytest.raises(module.ConfigurationImportError):
        module.copy_configuration(
            source, destination, file_references=(("config.json", "tls", "certificate_file"),)
        )
    assert not destination.exists()


def test_legacy_exe_relative_database_is_resolved_before_copy(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    (source / "local_settings.json").write_text(json.dumps({
        "app_secret": "test-key", "data_mode": "sqlite", "database_location_mode": "exe_dir"
    }))
    destination = tmp_path / "installed" / "config"
    module.copy_configuration(source, destination)
    payload = json.loads((destination / "local_settings.json").read_text(encoding="utf-8"))
    assert payload["database_location_mode"] == "custom"
    assert Path(payload["database_path"]) == source / "picsyncra.sqlite"


def test_import_rejects_destination_inside_source(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    with pytest.raises(module.ConfigurationImportError):
        module.copy_configuration(source, source / "installed-config")


def test_import_can_select_config_stored_apart_from_bootstrap(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    external = tmp_path / "external-config"
    external.mkdir()
    (external / "client.pem").write_bytes(b"external-certificate")
    selected = external / "config.json"
    selected.write_text(json.dumps({"tls": {"certificate_file": "client.pem"}}))
    destination = tmp_path / "installed" / "config"
    module.copy_configuration(
        source, destination, configuration_path=selected,
        file_references=(("config.json", "tls", "certificate_file"),),
    )
    shutil.rmtree(external)
    payload = json.loads((destination / "config.json").read_text(encoding="utf-8"))
    assert Path(payload["tls"]["certificate_file"]).read_bytes() == b"external-certificate"


def test_missing_bootstrap_key_stays_explicitly_unconfigured(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    (source / "local_settings.json").unlink()
    destination = tmp_path / "installed" / "config"
    module.copy_configuration(source, destination)
    settings = json.loads((destination / "local_settings.json").read_text(encoding="utf-8"))
    assert settings["installation_secrets_required"] is True
    assert "app_secret" not in settings


def test_new_process_reads_imported_key_and_config_after_source_is_removed(tmp_path):
    module = importer()
    source = source_config(tmp_path)
    state = tmp_path / "installed-data"
    destination = state / "config"
    program = tmp_path / "program"
    executable = program / "versions" / "42" / "PicSyncra-WEB.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test executable")
    (program / "active.json").write_text(json.dumps({
        "schema": 1, "installation_id": "test", "release_id": 42,
    }))
    module.copy_configuration(source, destination)
    shutil.rmtree(source)
    registration = {
        "installation_id": "test", "program_root": str(program), "state_root": str(state),
        "database_path": str(state / "data" / "picsyncra.sqlite"),
    }
    script = """
import json, sys
from picsyncra import install_paths
registration = json.loads(sys.argv[1])
install_paths._read_hklm_registrations = lambda: (registration,)
sys.executable = sys.argv[2]
sys.frozen = True
from picsyncra import common, settings, config
assert common.APP_SECRET == 'import-test-secret'
assert settings.BASE_DIR_SETTINGS_PATH == str(install_paths.resolve_config_root(sys.executable) / 'local_settings.json')
assert config._get_config_path() == str(install_paths.resolve_config_root(sys.executable) / 'config.json')
assert json.load(open(config._get_config_path(), encoding='utf-8'))['ftp']['host'] == 'example.invalid'
print('imported configuration available')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(registration), str(executable)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "imported configuration available"
