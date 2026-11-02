@echo off
chcp 65001 >nul
rem 双击＝本机模式；「启动 AI Edu.cmd -Mobile」＝手机模式（前后端监听 0.0.0.0 并打印局域网地址）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1" %*
echo.
echo Press any key to close this window (services keep running).
pause >nul
