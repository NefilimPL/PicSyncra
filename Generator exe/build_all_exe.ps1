$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "build_local_exe.ps1")
& (Join-Path $PSScriptRoot "build_migrator_exe.ps1")
& (Join-Path $PSScriptRoot "build_web_exe.ps1")
& (Join-Path $PSScriptRoot "build_web_exe.ps1") -IncludeVision -IncludeVisionModels

Write-Host "OK. Wygenerowano lokalne EXE oraz warianty web bez OCR i z offline OCR w: $PSScriptRoot"
