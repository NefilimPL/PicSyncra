@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

rem Usage: BUILD_INSTALLER.bat [release-id] [--without-ocr]
rem The default mirrors the CI installed release and includes the optional OCR package.
set "releaseId=%~1"
if "%releaseId%"=="" set "releaseId=1"

set "buildOcr=-BuildOcr"
if /I "%~2"=="--without-ocr" set "buildOcr="

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\installer\build_installer.ps1" -ReleaseId "%releaseId%" %buildOcr%
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" pause
exit /b %exitCode%
