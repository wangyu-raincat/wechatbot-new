@echo off
chcp 65001 >nul
cd /d "%~dp0"
python bot.py
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已安装 Python，并已执行 pip install -r requirements.txt
  pause
)
