from pathlib import Path
import json
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('channel', ['stable','dev'])
def test_installed_build_from_clean_directory_and_repeated_release(tmp_path: Path, channel: str) -> None:
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
    shutil.copytree(ROOT / 'picsyncra', checkout / 'picsyncra', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (checkout / 'tools').mkdir()
    shutil.copy2(ROOT / 'tools/build_installed_modules.py', checkout / 'tools')
    shutil.copy2(ROOT / 'installer/module-compatibility.json', checkout / 'installer')
    shutil.copy2(ROOT / 'PicSyncra.pyw', checkout)
    harness = tmp_path / "build-harness.ps1"
    harness.write_text(
        r"""param([string]$Checkout, [string]$TestPython, [string]$TestChannel)
$ErrorActionPreference = 'Stop'
function Invoke-BuildPython {
    $arguments = @($args)
    if ($arguments[0] -eq '-c') {
        & $TestPython @arguments
        $global:LASTEXITCODE = $LASTEXITCODE
        return
    }
    if ($arguments[0] -eq 'tools/build_installed_modules.py') {
        & $TestPython @arguments
        $global:LASTEXITCODE = $LASTEXITCODE
        return
    }
    if ($arguments[0] -ne '-m') { throw 'Unexpected Python invocation' }
    if ($arguments[1] -eq 'pip') { $global:LASTEXITCODE = 0; return }
    if ($arguments[1] -ne 'PyInstaller') { throw 'Unexpected build module' }
    $nameIndex = [Array]::IndexOf($arguments, '--name')
    $name = if ($nameIndex -ge 0) { $arguments[$nameIndex + 1] } else { 'PicSyncra-SetupHelper' }
    if ($arguments -contains 'installer/module-host.spec') { $name = $env:PICSYNCRA_HOST_NAME }
    $distIndex = [Array]::IndexOf($arguments, '--distpath')
    $output = Join-Path $arguments[$distIndex + 1] $name
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $output "$name.exe") -Value 'compiled application'
    New-Item -ItemType Directory -Path (Join-Path $output '_internal') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $output '_internal\runtime.dll') -Value 'runtime'
    for ($index = 0; $index -lt $arguments.Count; $index++) {
        if ($arguments[$index] -eq '--add-data') {
            $source, $relativeDestination = $arguments[$index + 1].Split(';', 2)
            $destination = Join-Path (Join-Path $output '_internal') $relativeDestination
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination $destination
        }
    }
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
& (Join-Path $Checkout 'installer\build_installer.ps1') -ReleaseId 1 -ReleaseCommit ('a' * 40) -Channel $TestChannel -SourceBranch $(if ($TestChannel -eq 'dev') { 'dev2' } else { 'main' }) -Python Invoke-BuildPython
""",
        encoding="utf-8",
    )

    def run_build() -> None:
        result = subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness),
             str(checkout), sys.executable, channel],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run_build()
    output = checkout / "dist" / "installed"
    layout = json.loads((output / 'module-initial-layout.json').read_text())
    assert layout['channel'] == channel
    base = output / 'module-sets' / layout['base']
    local = output / 'module-sets' / layout['local']
    static = base / 'picsyncra/web/static'
    for template in ("index.html", "login.html"):
        html = (static / template).read_text(encoding="utf-8")
        referenced_assets = re.findall(r'(?:src|href)="/static/([^"?]+)', html)
        assert referenced_assets
        missing = [asset for asset in referenced_assets if not (static / asset).is_file()]
        assert not missing, f"{template} references missing packaged assets: {missing}"
    assert (output / "PicSyncra-Setup.ico").is_file()
    assert json.loads((base / 'module-set.json').read_text())['pinned'] == []
    assert not (base / 'apps/local').exists()
    for directory, executable in (
        (f"module-sets/{layout['base']}/apps/web", "PicSyncra-WEB"),
        (f"module-sets/{layout['base']}/apps/migrator", "PicSyncra-Migrator"),
        (f"module-sets/{layout['local']}/apps/local", "PicSyncra"),
        ("helper", "PicSyncra-SetupHelper"),
    ):
        assert (output / directory / f"{executable}.exe").is_file()
        (output / directory / "obsolete.dll").write_text("old release", encoding="utf-8")
    run_build()
    for directory, executable in (
        (f"module-sets/{layout['base']}/apps/web", "PicSyncra-WEB"),
        (f"module-sets/{layout['base']}/apps/migrator", "PicSyncra-Migrator"),
        (f"module-sets/{layout['local']}/apps/local", "PicSyncra"),
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
    assert source.index("requirements-vision.txt") < source.index("Build-Onedir 'PicSyncra-OCR'")
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
