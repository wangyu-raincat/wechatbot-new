@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
".venv\Scripts\python.exe" qqbot_ctl.py stop
echo.
pause
