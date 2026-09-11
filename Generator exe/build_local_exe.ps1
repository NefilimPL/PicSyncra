$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$VenvDir = Join-Path $RepoRoot ".venv-build"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$IconDir = Join-Path $ScriptDir ".icons"
$IconPath = Join-Path $IconDir "PIC9_LOCAL.ico"
$WorkPath = Join-Path $RepoRoot "build\local-exe"
$VersionInfoPath = Join-Path $WorkPath "PicSyncra.version.txt"

Set-Location $RepoRoot
. (Join-Path $ScriptDir "build_common.ps1")

Initialize-BuildEnvironment `
    -RepoRoot $RepoRoot `
    -VenvDir $VenvDir `
    -Python $Python

New-Item -ItemType Directory -Path $IconDir -Force | Out-Null
New-Item -ItemType Directory -Path $WorkPath -Force | Out-Null
Invoke-Native $Python "-c" "from PIL import Image; Image.open(r'pic\PIC9_LOCAL.png').save(r'$IconPath', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
Invoke-Native $Python "tools\generate_windows_version_info.py" `
    --output $VersionInfoPath `
    --file-description "PicSyncra desktop application" `
    --internal-name "PicSyncra" `
    --original-filename "PicSyncra.exe"
$ModuleBuildManifestArguments = New-ModuleBuildManifestArguments `
    -Python $Python `
    -RepoRoot $RepoRoot `
    -WorkPath $WorkPath `
    -BuildVariant "local"

$env:PICSYNCRA_HEADLESS = "1"
$env:PYINSTALLER_BUILD = "1"
Invoke-Native $Python "-m" "PyInstaller" "--noconfirm" "--clean" "--log-level=WARN" `
    --name PicSyncra `
    --noconsole `
    --onefile `
    --distpath $ScriptDir `
    --workpath $WorkPath `
    --icon $IconPath `
    --version-file $VersionInfoPath `
    --collect-submodules mysql.connector `
    --collect-data mysql.connector `
    --collect-data certifi `
    --add-data "picsyncra\Localization;picsyncra\Localization" `
    --add-data "picsyncra\VERSION;picsyncra" `
    @ModuleBuildManifestArguments `
    --add-data "pic\PIC9_LOCAL.png;pic" `
    PicSyncra.pyw

Write-Host "OK. Wynik: $ScriptDir\PicSyncra.exe"
