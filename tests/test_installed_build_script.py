from pathlib import Path


def test_installed_build_installs_web_and_optional_ocr_dependencies_before_packaging() -> None:
    source = (Path(__file__).parents[1] / "installer" / "build_installer.ps1").read_text(encoding="utf-8")

    assert "-r requirements-web.txt" in source
    assert "-r requirements-vision.txt" in source
    assert source.index("requirements-vision.txt") < source.index("installer/ocr.spec")
    assert "PADDLE_PDX_CACHE_HOME" in source
    assert "available_ocr_profiles" in source


def test_ocr_spec_packages_the_prepared_model_cache() -> None:
    source = (Path(__file__).parents[1] / "installer" / "ocr.spec").read_text(encoding="utf-8")

    assert "PADDLE_PDX_CACHE_HOME" in source
    assert '"ocr_models"' in source
