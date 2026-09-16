from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_installed_build_installs_web_and_optional_ocr_dependencies_before_packaging() -> None:
    source = (ROOT / "installer" / "build_installer.ps1").read_text(encoding="utf-8")

    assert "-r requirements-web.txt" in source
    assert "-r requirements-vision.txt" in source
    assert source.index("requirements-vision.txt") < source.index("installer/ocr.spec")
    assert "PADDLE_PDX_CACHE_HOME" in source
    assert "available_ocr_profiles" in source


def test_ocr_spec_packages_the_prepared_model_cache() -> None:
    source = (ROOT / "installer" / "ocr.spec").read_text(encoding="utf-8")

    assert "PADDLE_PDX_CACHE_HOME" in source
    assert '"ocr_models"' in source


def test_setup_helper_spec_resolves_its_root_entrypoint_outside_installer_directory() -> None:
    source = (ROOT / "installer" / "installed.spec").read_text(encoding="utf-8")

    assert "Path(SPECPATH).parent" in source
    assert 'ROOT / "PicSyncra-SetupHelper.py"' in source


def test_local_installer_generator_uses_the_canonical_installer_build_script() -> None:
    source = (ROOT / "Generator exe" / "BUILD_INSTALLER.bat").read_text(encoding="utf-8")

    assert "installer\\build_installer.ps1" in source
    assert "-BuildOcr" in source
    assert "--without-ocr" in source
    assert "-ReleaseId" in source
