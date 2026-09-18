[CmdletBinding()]
param(
    [ValidatePattern('^[1-9][0-9]*$')]
    [string]$ReleaseId = '1',
    [switch]$BuildOcr,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $repoRoot 'dist\installed'
$workRoot = Join-Path $repoRoot 'build\installed'

Push-Location $repoRoot
try {
    & $Python -m pip install -r requirements-build.txt -r requirements-web.txt -r requirements-installed.txt
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac zaleznosci builda.' }

    function New-BuildIcon([string]$SourcePath, [string]$IconPath) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $IconPath) -Force | Out-Null
        & $Python -c "from PIL import Image; Image.open(r'$SourcePath').save(r'$IconPath', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
        if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie utworzyc ikony: $IconPath" }
    }

    function Get-WebStaticDataArguments {
        $staticDirectory = Join-Path $repoRoot 'picsyncra\web\static'
        $staticAssets = @(
            'app.css',
            'app.js',
            'autocomplete.js',
            'index.html',
            'latest-request.js',
            'login.html',
            'login.js',
            'module-build-status.js',
            'ocr-diagnostics.js',
            'process-jobs.js',
            'runtime-status.js'
        )
        $arguments = @()
        foreach ($asset in $staticAssets) {
            $sourcePath = Join-Path $staticDirectory $asset
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
                throw "Brakuje wymaganego zasobu web: $sourcePath"
            }
            $arguments += '--add-data'
            $arguments += "$sourcePath;picsyncra\web\static"
        }
        return $arguments
    }

    $iconRoot = Join-Path $workRoot 'icons'
    $webIconPath = Join-Path $iconRoot 'web.ico'
    $localIconPath = Join-Path $iconRoot 'local.ico'
    $setupIconPath = Join-Path $distRoot 'PicSyncra-Setup.ico'
    New-BuildIcon (Join-Path $repoRoot 'pic\PIC9_WEB.png') $webIconPath
    New-BuildIcon (Join-Path $repoRoot 'pic\PIC9_LOCAL.png') $localIconPath
    Copy-Item $localIconPath $setupIconPath -Force
    $webStaticDataArguments = Get-WebStaticDataArguments

    function Build-Onedir([string]$Name, [string]$Entrypoint, [string]$IconPath, [string[]]$ExtraArguments = @()) {
        & $Python -m PyInstaller --noconfirm --clean --onedir --name $Name `
            --distpath $distRoot --workpath $workRoot `
            --collect-submodules picsyncra --collect-data certifi `
            --icon $IconPath @ExtraArguments $Entrypoint
        if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie zbudowac $Name." }
    }

    Build-Onedir 'PicSyncra-WEB' 'PicSyncra-WEB.pyw' $webIconPath -ExtraArguments $webStaticDataArguments
    Build-Onedir 'PicSyncra-Migrator' 'PicSyncra-Migrator.pyw' $localIconPath
    Build-Onedir 'PicSyncra' 'PicSyncra.pyw' $localIconPath
    Build-Onedir 'PicSyncra-Controller' 'PicSyncra-Controller.py' $localIconPath
    & $Python -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot installer/installed.spec
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zbudowac PicSyncra-SetupHelper.' }
    if ($BuildOcr) {
        & $Python -m pip install -r requirements-vision.txt
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac zaleznosci komponentu OCR.' }
        $modelCache = Join-Path $workRoot 'ocr-model-cache'
        New-Item -ItemType Directory -Path $modelCache -Force | Out-Null
        $env:PADDLE_PDX_CACHE_HOME = $modelCache
        & $Python -c "from paddleocr import PaddleOCR; from picsyncra.services.ocr_profiles import available_ocr_profiles; [PaddleOCR(text_detection_model_name=profile.detector_model, text_recognition_model_name=profile.recognizer_model, enable_mkldnn=False, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False) for profile in available_ocr_profiles()]"
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie przygotowac lokalnych modeli OCR.' }
        & $Python -c "from picsyncra.services.image_dimensions import _model_cache_has_profile; from picsyncra.services.ocr_profiles import available_ocr_profiles; import os; missing = [profile.id for profile in available_ocr_profiles() if not _model_cache_has_profile(os.environ['PADDLE_PDX_CACHE_HOME'], profile)]; (_ for _ in ()).throw(RuntimeError('Brakuje modeli OCR: ' + ', '.join(missing))) if missing else None"
        if ($LASTEXITCODE -ne 0) { throw 'Nie wszystkie lokalne profile OCR zostaly przygotowane.' }
        & $Python -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot installer/ocr.spec
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zbudowac komponentu OCR.' }
    }

    $versionRoot = Join-Path $distRoot "versions\$ReleaseId"
    New-Item -ItemType Directory -Path $versionRoot -Force | Out-Null
    Copy-Item (Join-Path $distRoot 'PicSyncra-WEB') (Join-Path $versionRoot 'web') -Recurse -Force
    Copy-Item (Join-Path $distRoot 'PicSyncra-Migrator') (Join-Path $versionRoot 'migrator') -Recurse -Force
    Copy-Item (Join-Path $distRoot 'PicSyncra') (Join-Path $versionRoot 'local') -Recurse -Force
    # The controller lives outside a release bundle so it can start the newly
    # active WEB executable after an update changes active.json.
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
