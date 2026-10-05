from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]


def test_installed_build_from_clean_directory_and_repeated_release(tmp_path: Path) -> None:
    """Run the packaging script without the expensive external compilers.

    Catches a missing output root, nested bundles on rebuild, stale files,
    and Python icon commands that break on apostrophes in the checkout path.
    """
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is required to execute the Windows build script")
    checkout = tmp_path / "builder's checkout"
    (checkout / "installer").mkdir(parents=True)
    shutil.copy2(ROOT / "installer" / "build_installer.ps1", checkout / "installer")
    shutil.copytree(ROOT / "pic", checkout / "pic")
    shutil.copytree(ROOT / "picsyncra" / "web" / "static", checkout / "picsyncra" / "web" / "static")
    harness = tmp_path / "build-harness.ps1"
    harness.write_text(
        r"""param([string]$Checkout, [string]$TestPython)
$ErrorActionPreference = 'Stop'
function Invoke-BuildPython {
    $arguments = @($args)
    if ($arguments[0] -eq '-c') {
        & $TestPython @arguments
        $global:LASTEXITCODE = $LASTEXITCODE
        return
    }
    if ($arguments[0] -ne '-m') { throw 'Unexpected Python invocation' }
    if ($arguments[1] -eq 'pip') { $global:LASTEXITCODE = 0; return }
    if ($arguments[1] -ne 'PyInstaller') { throw 'Unexpected build module' }
    $nameIndex = [Array]::IndexOf($arguments, '--name')
    $name = if ($nameIndex -ge 0) { $arguments[$nameIndex + 1] } else { 'PicSyncra-SetupHelper' }
    $distIndex = [Array]::IndexOf($arguments, '--distpath')
    $output = Join-Path $arguments[$distIndex + 1] $name
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $output "$name.exe") -Value 'compiled application'
    New-Item -ItemType Directory -Path (Join-Path $output '_internal') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $output '_internal\runtime.dll') -Value 'runtime'
    $global:LASTEXITCODE = 0
}
function Get-Command {
    param([string]$Name, [string]$ErrorAction)
    if ($Name -ne 'ISCC.exe') { throw 'Unexpected compiler lookup' }
    return [pscustomobject]@{ Source = 'Invoke-TestIscc' }
}
function Invoke-TestIscc {
    $global:LASTEXITCODE = 0
}
& (Join-Path $Checkout 'installer\build_installer.ps1') -ReleaseId 1 -Python Invoke-BuildPython
""",
        encoding="utf-8",
    )

    def run_build() -> None:
        result = subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness),
             str(checkout), sys.executable],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run_build()
    output = checkout / "dist" / "installed"
    assert (output / "PicSyncra-Setup.ico").is_file()
    assert json.loads((output / "active.json").read_text(encoding="utf-8")) == {
        "schema": 1, "installation_id": "primary-installation", "release_id": 1,
    }
    for directory, executable in (
        ("versions/1/web", "PicSyncra-WEB"),
        ("versions/1/migrator", "PicSyncra-Migrator"),
        ("versions/1/local", "PicSyncra"),
        ("helper", "PicSyncra-SetupHelper"),
    ):
        assert (output / directory / f"{executable}.exe").is_file()
        (output / directory / "obsolete.dll").write_text("old release", encoding="utf-8")
    run_build()
    for directory, executable in (
        ("versions/1/web", "PicSyncra-WEB"),
        ("versions/1/migrator", "PicSyncra-Migrator"),
        ("versions/1/local", "PicSyncra"),
        ("helper", "PicSyncra-SetupHelper"),
    ):
        bundle = output / directory
        assert (bundle / f"{executable}.exe").is_file()
        assert (bundle / "_internal" / "runtime.dll").is_file()
        assert not (bundle / executable).exists()
        assert not (bundle / "obsolete.dll").exists()


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


def test_ocr_spec_resolves_its_root_entrypoint_outside_installer_directory() -> None:
    source = (ROOT / "installer" / "ocr.spec").read_text(encoding="utf-8")

    assert "Path(SPECPATH).parent" in source
    assert 'ROOT / "PicSyncra-OCR.py"' in source


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


def test_installed_build_packages_web_static_files_and_generates_icons() -> None:
    """Catches a frozen WEB backend without static assets or application icons."""

    source = (ROOT / "installer" / "build_installer.ps1").read_text(encoding="utf-8")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "PIC9_WEB.png" in source
    assert "PIC9_LOCAL.png" in source
    assert "function New-BuildIcon" in source
    assert "--icon $IconPath" in source
    assert "'runtime-status.js'" in source
    assert "$sourcePath;picsyncra\\web\\static" in source
    assert "PicSyncra-Setup.ico" in source
    assert "installer/Output/" in ignored
