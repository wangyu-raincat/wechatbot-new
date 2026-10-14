@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist bot.pid (
  echo 没有找到正在运行的机器人。
  pause
  exit /b 1
)
set /p PID=<bot.pid
taskkill /PID %PID% /F
del bot.pid 2>nul
echo 已停止。
pause
