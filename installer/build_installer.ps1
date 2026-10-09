[CmdletBinding()]
param(
    [ValidatePattern('^[1-9][0-9]*$')]
    [string]$ReleaseId = '1',
    [switch]$BuildOcr,
    [string]$ReleaseTag = '',
    [string]$ReleaseCommit = '',
    [ValidateSet('stable', 'dev')][string]$Channel = 'stable',
    [string]$SourceBranch = 'main',
    [string]$PublishedAt = '',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $repoRoot 'dist\installed'
$workRoot = Join-Path $repoRoot 'build\installed'

Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
    & $Python -m pip install -r requirements-build.txt -r requirements-web.txt -r requirements-installed.txt
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac zaleznosci builda.' }

    function New-BuildIcon([string]$SourcePath, [string]$IconPath) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $IconPath) -Force | Out-Null
        & $Python -c 'from PIL import Image; import sys; Image.open(sys.argv[1]).save(sys.argv[2], sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])' $SourcePath $IconPath
        if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie utworzyc ikony: $IconPath" }
    }

    function Get-WebStaticDataArguments {
        $staticDirectory = Join-Path $repoRoot 'picsyncra\web\static'
        $staticAssets = @(
            'app.css',
            'app.js',
            'autocomplete.js',
            'index.html',
            'installation-updates.js',
            'latest-request.js',
            'legacy-migration.js',
            'login.html',
            'login.js',
            'module-build-status.js',
            'module-updates-panel.js',
            'ocr-diagnostics.js',
            'process-jobs.js',
            'slot-ui.js',
            'settings-ui.js',
            'ocr-tester-ui.js',
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
        if ($Name -in @('PicSyncra-WEB', 'PicSyncra-Migrator', 'PicSyncra', 'PicSyncra-OCR')) {
            $env:PICSYNCRA_HOST_NAME = $Name
            $env:PICSYNCRA_HOST_ICON = $IconPath
            $env:SOURCE_DATE_EPOCH = '946684800'
            & $Python -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath (Join-Path $workRoot $Name) installer/module-host.spec
            if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie zbudowac hosta $Name." }
            return
        }
        & $Python -m PyInstaller --noconfirm --clean --onedir --name $Name `
            --distpath $distRoot --workpath $workRoot `
            --collect-data certifi `
            --icon $IconPath @ExtraArguments $Entrypoint
        if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie zbudowac $Name." }
    }

    Build-Onedir 'PicSyncra-WEB' 'PicSyncra-WEB.pyw' $webIconPath -ExtraArguments $webStaticDataArguments
    Build-Onedir 'PicSyncra-Migrator' 'PicSyncra-Migrator.pyw' $localIconPath
    Build-Onedir 'PicSyncra' 'PicSyncra.pyw' $localIconPath
    Build-Onedir 'PicSyncra-Controller' 'PicSyncra-Controller.py' $localIconPath
    Build-Onedir 'PicSyncra-Launcher' 'PicSyncra-Launcher.pyw' $localIconPath
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
        Build-Onedir 'PicSyncra-OCR' 'installer/installed_host.py' $localIconPath
    } else {
        # A stale OCR build must not turn an explicitly no-OCR build into a
        # release with old vision libraries or models.
        $staleOcr = Join-Path $distRoot 'PicSyncra-OCR'
        if (Test-Path -LiteralPath $staleOcr) {
            $resolvedOcr = [IO.Path]::GetFullPath($staleOcr)
            if (-not $resolvedOcr.StartsWith([IO.Path]::GetFullPath($distRoot) + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Nieprawidlowy katalog OCR.' }
            if ((Get-Item -LiteralPath $resolvedOcr).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Katalog OCR jest dowiazaniem.' }
            Remove-Item -LiteralPath $resolvedOcr -Recurse -Force
        }
    }


    function Copy-BuildDirectory([string]$SourcePath, [string]$DestinationPath) {
        $outputRoot = [IO.Path]::GetFullPath($distRoot).TrimEnd('\', '/')
        $destination = [IO.Path]::GetFullPath($DestinationPath)
        if (-not $destination.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Katalog docelowy musi znajdowac sie wewnatrz dist\installed: $destination"
        }
        if (-not (Test-Path -LiteralPath $SourcePath -PathType Container)) {
            throw "Brakuje zbudowanego komponentu: $SourcePath"
        }
        # Do not follow a junction or symlink while removing previous build output.
        $current = $destination
        while ($current.Length -ge $outputRoot.Length) {
            if (Test-Path -LiteralPath $current) {
                $item = Get-Item -LiteralPath $current -Force
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Katalog builda nie moze byc dowiazaniem: $current"
                }
            }
            $current = Split-Path -Parent $current
        }
        if (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Recurse -Force
        }
        Copy-Item -LiteralPath $SourcePath -Destination $destination -Recurse -Force
    }

    # The controller lives outside a release bundle so it can start the newly
    # active WEB executable after an update changes active.json.
    Copy-BuildDirectory (Join-Path $distRoot 'PicSyncra-SetupHelper') (Join-Path $distRoot 'helper')
    if (-not $ReleaseTag) { $ReleaseTag = "local-$ReleaseId" }
    if (-not $ReleaseCommit) { $ReleaseCommit = (& git rev-parse HEAD).Trim() }
    $moduleArguments = @('tools/build_installed_modules.py', '--dist-root', $distRoot, '--release-id', $ReleaseId,
        '--tag', $ReleaseTag, '--commit', $ReleaseCommit, '--channel', $Channel, '--source-branch', $SourceBranch)
    if ($PublishedAt) { $moduleArguments += @('--published-at', $PublishedAt) }
    & $Python @moduleArguments
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zbudowac rozlacznych modulow.' }
    $moduleLayout = Get-Content -LiteralPath (Join-Path $distRoot 'module-initial-layout.json') -Raw | ConvertFrom-Json

    $iscc = Get-Command ISCC.exe -ErrorAction Stop
    & $iscc.Source "/DBuildRoot=$distRoot" "/DReleaseId=$ReleaseId" "/DBaseSetId=$($moduleLayout.base)" "/DLocalSetId=$($moduleLayout.local)" (Join-Path $PSScriptRoot 'PicSyncra.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Kompilacja Inno Setup nie powiodla sie.' }
}
finally {
    Pop-Location
}
