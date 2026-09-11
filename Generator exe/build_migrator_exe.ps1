$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$VenvDir = Join-Path $RepoRoot ".venv-build"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$IconDir = Join-Path $ScriptDir ".icons"
$IconPath = Join-Path $IconDir "PIC9_LOCAL.ico"
$WorkPath = Join-Path $RepoRoot "build\migrator-exe"
$VersionInfoPath = Join-Path $WorkPath "PicSyncra-Migrator.version.txt"

Set-Location $RepoRoot
. (Join-Path $ScriptDir "build_common.ps1")
Initialize-BuildEnvironment -RepoRoot $RepoRoot -VenvDir $VenvDir -Python $Python
New-Item -ItemType Directory -Path $IconDir -Force | Out-Null
New-Item -ItemType Directory -Path $WorkPath -Force | Out-Null
Invoke-Native $Python "-c" "from PIL import Image; Image.open(r'pic\PIC9_LOCAL.png').save(r'$IconPath', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
Invoke-Native $Python "tools\generate_windows_version_info.py" --output $VersionInfoPath --file-description "PicSyncra legacy SQLite migrator" --internal-name "PicSyncra-Migrator" --original-filename "PicSyncra-Migrator.exe"
$env:PICSYNCRA_HEADLESS = "1"
$env:PYINSTALLER_BUILD = "1"
Invoke-Native $Python "-m" "PyInstaller" "--noconfirm" "--clean" "--log-level=WARN" `
    --name PicSyncra-Migrator --noconsole --onefile --distpath $ScriptDir --workpath $WorkPath `
    --icon $IconPath --version-file $VersionInfoPath `
    --hidden-import picsyncra.offline_migrator_processes `
    --add-data "picsyncra\VERSION;picsyncra" `
    --add-data "pic\PIC9_LOCAL.png;pic" `
    PicSyncra-Migrator.pyw
Write-Host "OK. Wynik: $ScriptDir\PicSyncra-Migrator.exe"
