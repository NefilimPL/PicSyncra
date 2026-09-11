@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_web_exe.ps1" -IncludeVision -IncludeVisionModels
if errorlevel 1 pause
endlocal
