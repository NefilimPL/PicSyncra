[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BuildRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[1-9][0-9]*$')][string]$ReleaseId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$BaseSetId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$LocalSetId,
    [ValidatePattern('^[a-f0-9]{64}$')][string]$OcrSetId,
    [ValidatePattern('^[a-f0-9]{64}$')][string]$LocalOcrSetId,
    [Parameter(Mandatory = $true)][string]$Compiler,
    [string]$ScriptPath = (Join-Path $PSScriptRoot 'PicSyncra.iss')
)

$ErrorActionPreference = 'Stop'
$buildDirectory = [IO.Path]::GetFullPath($BuildRoot)
if (-not (Test-Path -LiteralPath $buildDirectory -PathType Container)) { throw 'Brakuje katalogu builda Setup.' }
if ([bool]$OcrSetId -ne [bool]$LocalOcrSetId) { throw 'Niekompletne zestawy OCR dla Setup.' }
$subst = Join-Path ([Environment]::GetFolderPath('System')) 'subst.exe'
$ownedDrive = $null
try {
    # SUBST keeps every source below MAX_PATH without removing SDK/runtime
    # files, copying payloads or changing the machine's long-path policy.
    $occupied = [Environment]::GetLogicalDrives()
    foreach ($code in 90..68) {
        $drive = ([char]$code).ToString() + ':'
        if ($occupied -contains ($drive + '\')) { continue }
        & $subst $drive $buildDirectory 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $ownedDrive = $drive; break }
    }
    if (-not $ownedDrive) { throw 'Brak wolnej litery dysku do kompilacji Setup z krotkimi sciezkami.' }
    $compilerRoot = $ownedDrive + '\'
    Write-Host "Inno Setup: temporary source root $compilerRoot"
    $arguments = @("/DBuildRoot=$compilerRoot", "/DReleaseId=$ReleaseId", "/DBaseSetId=$BaseSetId", "/DLocalSetId=$LocalSetId")
    if ($OcrSetId) { $arguments += @("/DOcrSetId=$OcrSetId", "/DLocalOcrSetId=$LocalOcrSetId") }
    & $Compiler @arguments $ScriptPath
    $compilerExitCode = $LASTEXITCODE
    if ($compilerExitCode -ne 0) { throw "Kompilacja Inno Setup nie powiodla sie (kod $compilerExitCode)." }
}
finally {
    # Only a drive successfully created by this invocation can be removed.
    if ($ownedDrive) {
        & $subst $ownedDrive /D 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning "Nie udalo sie usunac tymczasowego mapowania $ownedDrive" }
    }
}
