$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Port = if ($env:PICSYNCRA_WEB_PORT) { [int]$env:PICSYNCRA_WEB_PORT } else { 8010 }
$PidFile = Join-Path $Root ".picsyncra_web.pid"

function Write-Info($Text) {
    Write-Host "[WEB] $Text"
}

function Test-Administrator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Test-WebProcess($PidValue) {
    $process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    if (-not $process) {
        return $false
    }
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $PidValue"
        $cmd = [string]$proc.CommandLine
        if ($cmd) {
            return (
                ($cmd -like "*uvicorn*" -and $cmd -like "*picsyncra.web.app*") -or
                $cmd -like "*picsyncra.web_manager*" -or
                $cmd -like "*PicSyncra-WEB*" -or
                $cmd -like "*--service-run*"
            )
        }
    } catch {
    }
    return $process.ProcessName -in @("python", "pythonw", "PicSyncra-WEB")
}

function Get-PortListenerPids {
    $pids = @()
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        foreach ($connection in $connections) {
            $pids += [int]$connection.OwningProcess
        }
    } catch {
    }
    if ($pids.Count -eq 0) {
        $lines = netstat -ano | Where-Object {
            $_ -match ":$Port\s" -and $_ -match "\sLISTENING\s+(\d+)\s*$"
        }
        foreach ($line in $lines) {
            if ($line -match "\sLISTENING\s+(\d+)\s*$") {
                $pids += [int]$Matches[1]
            }
        }
    }
    return $pids | Select-Object -Unique
}

function Stop-WebPid($PidValue, [switch]$AllowRecordedLauncher) {
    $process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    if (-not $process) {
        return [pscustomobject]@{ ok = $true; attempted = $false; message = "" }
    }
    if (-not $AllowRecordedLauncher -and -not (Test-WebProcess $PidValue)) {
        return [pscustomobject]@{ ok = $true; attempted = $false; message = "" }
    }
    try {
        $output = @(& taskkill /PID $PidValue /T /F 2>&1)
    } catch {
        return [pscustomobject]@{ ok = $false; attempted = $true; message = $_.Exception.Message }
    }
    if ($LASTEXITCODE -eq 0) {
        return [pscustomobject]@{ ok = $true; attempted = $true; message = "" }
    }
    $detail = (($output | Out-String).Trim())
    if (-not $detail) {
        $detail = "brak szczegolow z Windows"
    }
    return [pscustomobject]@{ ok = $false; attempted = $true; message = $detail }
}

function Wait-WebPortRelease {
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-PortListenerPids).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 200
    }
    return @(Get-PortListenerPids).Count -eq 0
}

function Read-RunMetadata {
    if (-not (Test-Path $PidFile)) {
        return $null
    }
    $content = Get-Content -Path $PidFile -Raw -ErrorAction SilentlyContinue
    if (-not $content) {
        return $null
    }
    try {
        return $content | ConvertFrom-Json
    } catch {
        $pidValue = 0
        $firstLine = ($content -split "`r?`n" | Select-Object -First 1)
        if ([int]::TryParse([string]$firstLine, [ref]$pidValue)) {
            return [pscustomobject]@{
                pid = $pidValue
                port = $Port
                firewall_rule_created = $false
                firewall_remove_on_stop = $false
                firewall_rule_name = ""
            }
        }
    }
    return $null
}

function Remove-FirewallRuleFromMetadata($Metadata) {
    if (-not $Metadata) {
        return
    }
    if (-not $Metadata.firewall_rule_created -or -not $Metadata.firewall_remove_on_stop) {
        return
    }
    $ruleName = [string]$Metadata.firewall_rule_name
    if (-not $ruleName) {
        return
    }
    if (-not (Get-Command Remove-NetFirewallRule -ErrorAction SilentlyContinue)) {
        Write-Info "Brak cmdletow Windows Firewall. Regula pozostaje: $ruleName."
        return
    }
    if (-not (Test-Administrator)) {
        Write-Info "Brak uprawnien administratora, nie moge usunac reguly firewall."
        Write-Info "Uruchom STOP_WEB.bat jako administrator albo wykonaj:"
        Write-Info "Remove-NetFirewallRule -DisplayName `"$ruleName`""
        return
    }
    try {
        Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Write-Info "Usunieto regule firewall: $ruleName."
    } catch {
        Write-Info "Nie udalo sie usunac reguly firewall: $($_.Exception.Message)"
    }
}

$stopped = $false
$failureMessages = @()
$metadata = Read-RunMetadata
if ($metadata -and $metadata.port) {
    $Port = [int]$metadata.port
}

$launcherStopped = $false
if ($metadata -and $metadata.launcher_pid) {
    $launcherPid = [int]$metadata.launcher_pid
    $result = Stop-WebPid $launcherPid -AllowRecordedLauncher
    if (-not $result.ok) {
        $failureMessages += "PID launchera ${launcherPid}: $($result.message)"
    } elseif ($result.attempted) {
        Write-Info "Zatrzymano launcher panelu webowego, PID $launcherPid."
        $stopped = $true
        $launcherStopped = $true
    }
}

if (-not $launcherStopped) {
    $candidatePids = @()
    if ($metadata -and $metadata.pid) {
        $candidatePids += [int]$metadata.pid
    }
    $candidatePids += Get-PortListenerPids
    foreach ($pidValue in @($candidatePids | Select-Object -Unique)) {
        $result = Stop-WebPid $pidValue
        if (-not $result.ok) {
            $failureMessages += "PID ${pidValue}: $($result.message)"
        } elseif ($result.attempted) {
            Write-Info "Zatrzymano panel webowy na porcie $Port, PID $pidValue."
            $stopped = $true
        }
    }
}

if ($failureMessages.Count -gt 0) {
    Write-Info "Nie udalo sie zatrzymac panelu webowego: $($failureMessages -join '; ')"
} elseif (-not (Wait-WebPortRelease)) {
    Write-Info "Panel webowy nadal nasluchuje na porcie $Port. Plik PID pozostaje do ponownej proby."
} else {
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    if (-not $stopped) {
        Write-Info "Panel webowy nie byl uruchomiony albo na porcie $Port dziala inna usluga."
    }
    Remove-FirewallRuleFromMetadata $metadata
}
