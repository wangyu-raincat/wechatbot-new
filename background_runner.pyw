"""Run the bot without a console window and keep a local log/pid file."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import runpy
import sys

import psutil


ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "机器人后台.pid"
LOG_FILE = ROOT / "机器人后台.log"


def existing_process() -> bool:
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        process = psutil.Process(pid)
        return process.is_running() and "background_runner.pyw" in " ".join(process.cmdline())
    except (OSError, ValueError, psutil.Error):
        return False


def cleanup() -> None:
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def main() -> None:
    os.chdir(ROOT)
    if existing_process():
        return
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    atexit.register(cleanup)
    log = LOG_FILE.open("a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    print("\n=== 后台机器人启动 ===")
    try:
        from config import DEEPSEEK_API_KEY
        if not DEEPSEEK_API_KEY:
            print("启动失败：未配置 DeepSeek API Key")
            return
        runpy.run_path(str(ROOT / "bot.py"), run_name="__main__")
    except BaseException:
        import traceback
        traceback.print_exc()
    finally:
        print("=== 后台机器人退出 ===")
        log.close()


if __name__ == "__main__":
    main()
