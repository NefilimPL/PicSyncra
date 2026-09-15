[CmdletBinding()]
param(
    [ValidatePattern('^[1-9][0-9]*$')]
    [string]$ReleaseId = '1',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $repoRoot 'dist\installed'
$workRoot = Join-Path $repoRoot 'build\installed'

Push-Location $repoRoot
try {
    & $Python -m pip install -r requirements-build.txt -r requirements-installed.txt
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac zaleznosci builda.' }

    function Build-Onedir([string]$Name, [string]$Entrypoint) {
        & $Python -m PyInstaller --noconfirm --clean --onedir --name $Name `
            --distpath $distRoot --workpath $workRoot `
            --collect-submodules picsyncra --collect-data certifi $Entrypoint
        if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie zbudowac $Name." }
    }

    Build-Onedir 'PicSyncra-WEB' 'PicSyncra-WEB.pyw'
    Build-Onedir 'PicSyncra-Migrator' 'PicSyncra-Migrator.pyw'
    Build-Onedir 'PicSyncra' 'PicSyncra.pyw'
    & $Python -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot installer/installed.spec
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zbudowac PicSyncra-SetupHelper.' }

    $versionRoot = Join-Path $distRoot "versions\$ReleaseId"
    New-Item -ItemType Directory -Path $versionRoot -Force | Out-Null
    Copy-Item (Join-Path $distRoot 'PicSyncra-WEB') (Join-Path $versionRoot 'web') -Recurse -Force
    Copy-Item (Join-Path $distRoot 'PicSyncra-Migrator') (Join-Path $versionRoot 'migrator') -Recurse -Force
    Copy-Item (Join-Path $distRoot 'PicSyncra') (Join-Path $versionRoot 'local') -Recurse -Force
    Copy-Item (Join-Path $distRoot 'PicSyncra-SetupHelper') (Join-Path $distRoot 'helper') -Recurse -Force
    [ordered]@{
        schema = 1
        installation_id = 'primary-installation'
        release_id = [int]$ReleaseId
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $distRoot 'active.json') -Encoding utf8 -NoNewline

    $iscc = Get-Command ISCC.exe -ErrorAction Stop
    & $iscc.Source "/DBuildRoot=$distRoot" "/DReleaseId=$ReleaseId" (Join-Path $PSScriptRoot 'PicSyncra.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Kompilacja Inno Setup nie powiodla sie.' }
}
finally {
    Pop-Location
}
