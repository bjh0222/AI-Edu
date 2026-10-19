@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1"
echo.
echo Press any key to close this window (services keep running).
pause >nul
