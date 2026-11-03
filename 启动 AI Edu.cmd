@echo off
chcp 65001 >nul
rem Double-click = local mode; "启动 AI Edu.cmd -Mobile" = mobile mode (listen 0.0.0.0).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1" %*
echo.
echo Press any key to close this window (services keep running).
pause >nul
