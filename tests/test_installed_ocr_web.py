"""Installed WEB selects the separately installed OCR runtime without changing portable."""

from __future__ import annotations

from picsyncra.installation.contracts import InstallContext
from picsyncra.web import app as web_app


def test_installed_web_uses_the_verified_ocr_worker_factory(monkeypatch, tmp_path) -> None:
    """Catches installed WEB falling back to importing PaddleOCR in its own process."""

    context = InstallContext(
        installation_id="primary",
        program_root=tmp_path / "program",
        state_root=tmp_path / "state",
        config_root=tmp_path / "state" / "config",
        database_path=tmp_path / "state" / "data" / "picsyncra.sqlite",
    )
    expected = object()
    monkeypatch.setattr(web_app, "resolve_install_context", lambda _executable: context)
    monkeypatch.setattr(
        web_app, "create_installed_ocr_worker", lambda received: expected if received is context else None
    )

    worker = web_app._create_ocr_execution_worker({"max_cpu_percent": 35})

    assert worker is expected


def test_installed_web_without_ocr_component_does_not_start_portable_worker(
    monkeypatch, tmp_path
) -> None:
    """Catches base installed WEB silently gaining a bundled OCR dependency."""

    context = InstallContext(
        installation_id="primary",
        program_root=tmp_path / "program",
        state_root=tmp_path / "state",
        config_root=tmp_path / "state" / "config",
        database_path=tmp_path / "state" / "data" / "picsyncra.sqlite",
    )
    monkeypatch.setattr(web_app, "resolve_install_context", lambda _executable: context)
    monkeypatch.setattr(web_app, "create_installed_ocr_worker", lambda _context: None)
    monkeypatch.setattr(
        web_app,
        "OcrWorkerProcess",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("portable worker started")),
    )

    assert web_app._create_ocr_execution_worker({"max_cpu_percent": 35}) is None


def test_portable_web_keeps_using_its_existing_ocr_worker(monkeypatch) -> None:
    """Catches the installed-runtime selection disabling portable deployments."""

    expected = object()
    created: dict[str, int] = {}
    monkeypatch.setattr(web_app, "resolve_install_context", lambda _executable: None)
    monkeypatch.setattr(
        web_app,
        "OcrWorkerProcess",
        lambda *, cpu_percent: created.setdefault("cpu_percent", cpu_percent) and expected,
    )

    worker = web_app._create_ocr_execution_worker({"max_cpu_percent": 27})

    assert worker is expected
    assert created == {"cpu_percent": 27}
