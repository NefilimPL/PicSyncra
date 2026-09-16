from pathlib import Path


def test_installed_build_installs_web_and_optional_ocr_dependencies_before_packaging() -> None:
    source = (Path(__file__).parents[1] / "installer" / "build_installer.ps1").read_text(encoding="utf-8")

    assert "-r requirements-web.txt" in source
    assert "-r requirements-vision.txt" in source
    assert source.index("requirements-vision.txt") < source.index("installer/ocr.spec")
