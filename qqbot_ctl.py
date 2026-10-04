# -*- coding: utf-8 -*-
"""机器人启动 / 停止 / 状态入口（命令行版）。

`机器人控制台.pyw` 是图形版；本脚本是等价的命令行版，
供 `启动机器人.cmd` / `停止机器人.cmd` / 桌面快捷方式调用。

用法：
    qqbot_ctl.py start     启动（已在运行则直接提示）
    qqbot_ctl.py stop      停止
    qqbot_ctl.py restart   重启
    qqbot_ctl.py status    查看状态

进程识别逻辑与控制台保持一致：读 `机器人后台.pid`，并校验命令行里
确实带 `background_runner.pyw`（防止 PID 被复用后误杀别的进程）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import requests

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "机器人后台.pid"
LOG_FILE = ROOT / "机器人后台.log"
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
RUNNER = ROOT / "background_runner.pyw"
QR_WINDOW = ROOT / "二维码窗口.pyw"

BOOT_WAIT_SECONDS = 60     # 冷启动 NapCat 的等待上限
LOGIN_WAIT_SECONDS = 180   # 等扫码的上限，超时照样放机器人起来

try:
    import config as _cfg
except Exception as exc:  # 配置损坏时给出明确提示，而不是一堆 traceback
    print(f"[!] 读取 config.py 失败：{exc}")
    sys.exit(2)

PLATFORM = getattr(_cfg, "PLATFORM", "wechat")
LISTEN_LIST = getattr(_cfg, "LISTEN_LIST", [])
IS_QQ = PLATFORM == "qq"
LABEL = "QQ" if IS_QQ else "微信"


def listening_summary() -> str:
    names = [str(entry[0]) for entry in LISTEN_LIST if entry]
    return "、".join(names) if names else "未配置"


def bot_process():
    """返回正在运行的机器人进程；没有则返回 None。"""
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        process = psutil.Process(pid)
        if process.is_running() and "background_runner.pyw" in " ".join(process.cmdline()):
            return process
    except (OSError, ValueError, psutil.Error):
        pass
    return None


def _say(message: str) -> None:
    """控制台入口直接打印；被 .pyw 引进来时（stdout 为 None）静默。"""
    if sys.stdout is None:
        return
    try:
        print(message)
    except Exception:
        pass


def _onebot_url(path: str) -> str:
    return getattr(_cfg, "QQ_ONEBOT_HTTP", "http://127.0.0.1:3000").rstrip("/") + path


def _onebot_headers() -> dict:
    token = getattr(_cfg, "QQ_ONEBOT_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def napcat_dir() -> Path | None:
    launcher = getattr(_cfg, "QQ_NAPCAT_LAUNCHER", "")
    return Path(launcher).parent if launcher else None


def napcat_qrcode() -> str:
    folder = napcat_dir()
    return str(folder / "cache" / "qrcode.png") if folder else r"D:\napcat\cache\qrcode.png"


def napcat_webui_port() -> int:
    folder = napcat_dir()
    if folder:
        try:
            data = json.loads((folder / "config" / "webui.json").read_text(encoding="utf-8"))
            return int(data.get("port") or 6099)
        except Exception:
            pass
    return 6099


def napcat_webui_up() -> bool:
    """NapCat 的 WebUI 端口在不在听 —— 它先于登录起来，用来区分「还在启动」和「没在跑」。"""
    with socket.socket() as sock:
        sock.settimeout(1.5)
        return sock.connect_ex(("127.0.0.1", napcat_webui_port())) == 0


def napcat_reachable() -> bool:
    """QQ 模式下确认 NapCat 的 HTTP 接口可用（替代微信的进程检查）。"""
    try:
        return requests.post(_onebot_url("/get_login_info"),
                             headers=_onebot_headers(), timeout=4).status_code == 200
    except Exception:
        return False


def napcat_online() -> bool:
    """小号是否真在线。

    半掉线时 `get_login_info` 照样返回 QQ 号（NapCat 以为还登着），只有
    `get_status` 的 `online` 说了算 —— 启动判定必须用这个。
    """
    try:
        data = requests.post(_onebot_url("/get_status"), headers=_onebot_headers(), timeout=4).json()
    except Exception:
        return False
    return bool((data.get("data") or {}).get("online"))


def napcat_identity() -> str:
    """取当前登录的 QQ 号，取不到返回空串。"""
    try:
        data = requests.post(_onebot_url("/get_login_info"), headers=_onebot_headers(), timeout=4).json()
        info = data.get("data") or {}
        return f"{info.get('nickname', '')}({info.get('user_id', '')})"
    except Exception:
        return ""


def qr_window_process():
    """扫码窗口的进程；没开着则返回 None。

    先按进程名过滤再读 cmdline —— 对全机每个进程读 cmdline 要好几秒，
    这个函数在等待循环里每秒都要调一次。
    """
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() not in ("pythonw.exe", "python.exe"):
                continue
            if any("二维码窗口.pyw" in str(part) for part in proc.cmdline()):
                return proc
        except (psutil.Error, TypeError):
            continue
    return None


def spawn_qr_window() -> bool:
    """拉起扫码窗口，返回是否真的起来了。"""
    if not QR_WINDOW.exists():
        return False
    try:
        subprocess.Popen(
            [str(PYTHONW), str(QR_WINDOW)],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError as exc:
        _say(f"  扫码窗口拉起失败：{exc}")
        return False

    # 刚起来的进程 cmdline 可能还读不到，多探几秒；窗口自己秒退（比如其实已登录）也算没起来
    for _ in range(12):
        time.sleep(0.5)
        if qr_window_process() is not None:
            return True
    return False


def wait_for_scan() -> bool:
    """弹扫码窗口并等小号上线。等不到也返回 True —— 机器人先起来，登录后自己会接上。"""
    if qr_window_process() is not None:
        started = True
        _say("  扫码窗口已经开着")
    else:
        _say("  小号不在线，正在打开扫码窗口…")
        started = spawn_qr_window()

    if started:
        _say("  请用手机 QQ 扫描弹出的二维码（二维码过期会自动刷新）")
    elif napcat_online():
        # 窗口可能刚起来就发现"其实已登录"于是自己关了
        who = napcat_identity()
        _say(f"  小号已经在线{'：' + who if who else ''}")
        return True
    else:
        _say("  [!] 扫码窗口没打开，可以手工扫：")
        _say(f"    WebUI http://localhost:{napcat_webui_port()}（页面里二维码自动刷新）")
        _say(f"    或打开图片 {napcat_qrcode()}")

    deadline = time.time() + LOGIN_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(1)
        if napcat_online():
            who = napcat_identity()
            _say(f"  扫码登录成功{'：' + who if who else ''}")
            return True
        if started and qr_window_process() is None:
            _say("  扫码窗口已关闭。")
            break
    else:
        _say(f"  等了 {LOGIN_WAIT_SECONDS} 秒仍未登录。")

    _say("  机器人照常启动，登录成功后会自动接上。")
    return True


def ensure_napcat() -> bool:
    """把小号弄到在线：没跑就拉起 NapCat，没登录就弹扫码窗口。

    冷启动本来就慢，小号掉登录时更是必须人工扫码，等多久都不够 ——
    所以等不到登录不算失败：`qqbot.py` 的 `_wait_for_login()` 会自己等，
    WS 也每 5 秒重连。只有「启动器本身不可用」才是真正的失败。
    """
    if napcat_online():
        who = napcat_identity()
        _say(f"  NapCat 已登录{'：' + who if who else ''}")
        return True

    if napcat_webui_up():
        # 已经在跑就不能再拉一次启动器，否则会开出第二个 QQ
        _say("  NapCat 已在运行，但小号不在线")
        return wait_for_scan()

    launcher = getattr(_cfg, "QQ_NAPCAT_LAUNCHER", "")
    if not launcher or not Path(launcher).exists():
        _say(f"  NapCat 未响应，且启动器不可用（QQ_NAPCAT_LAUNCHER={launcher or '未设置'}）")
        return False

    _say(f"  NapCat 未运行，正在拉起：{launcher}")
    try:
        subprocess.Popen(
            ["cmd", "/c", launcher],
            cwd=str(Path(launcher).parent),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError as exc:
        _say(f"  拉起失败：{exc}")
        return False

    for _ in range(BOOT_WAIT_SECONDS):
        time.sleep(1)
        if napcat_online():
            who = napcat_identity()
            _say(f"  NapCat 已就绪{'：' + who if who else ''}")
            return True
        if napcat_webui_up():
            break  # 起来了但没登录，交给扫码流程

    return wait_for_scan()


def cmd_start() -> int:
    process = bot_process()
    if process:
        print(f"机器人已经在运行（PID {process.pid}），无需重复启动。")
        return 0

    if not getattr(_cfg, "DEEPSEEK_API_KEY", ""):
        print("[!] 未配置 DeepSeek API Key，机器人会启动失败。")
        print("    请双击「机器人控制台」，在界面里填写并保存。")
        return 1

    if IS_QQ:
        if not ensure_napcat():
            print("[!] NapCat 启动器不可用，机器人会收不到消息。")
            print("    请检查 QQ_NAPCAT_LAUNCHER，或手工启动 NapCat 后重试。")
            return 1
    else:
        running = any((p.info["name"] or "").lower() == "weixin.exe"
                      for p in psutil.process_iter(["name"]))
        if not running:
            print("[!] 微信未运行，请先登录电脑微信小号。")
            return 1

    try:
        subprocess.Popen(
            [str(PYTHONW), str(RUNNER)],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError as exc:
        print(f"[!] 启动失败：{exc}")
        return 1

    time.sleep(2.5)
    process = bot_process()
    if process:
        print(f"[OK] 机器人已启动（PID {process.pid}）")
        print(f"     平台：{LABEL}     监听：{listening_summary()}")
        print(f"     日志：{LOG_FILE}")
        return 0

    print("[!] 启动命令已发出，但没检测到进程。请查看日志：")
    print(f"    {LOG_FILE}")
    return 1


def cmd_stop() -> int:
    process = bot_process()
    if not process:
        print("机器人当前没有在运行。")
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 0

    pid = process.pid
    print(f"正在停止机器人（PID {pid}）...")
    try:
        process.terminate()
        process.wait(8)
    except psutil.TimeoutExpired:
        print("  8 秒内未退出，强制结束。")
        try:
            process.kill()
        except psutil.Error:
            pass
    except psutil.Error as exc:
        print(f"  停止时出错：{exc}")

    try:
        PID_FILE.unlink()
    except OSError:
        pass

    if bot_process() is None:
        print("[OK] 机器人已停止。")
        return 0
    print("[!] 进程可能仍在，请用任务管理器确认。")
    return 1


def cmd_status() -> int:
    process = bot_process()
    key = getattr(_cfg, "DEEPSEEK_API_KEY", "")
    print(f"平台     : {LABEL}")
    print(f"机器人   : " + (f"运行中（PID {process.pid}）" if process else "已停止"))
    print(f"监听     : {listening_summary()}")
    print(f"DeepSeek : " + ("已配置（值不显示）" if key else "未配置"))
    if IS_QQ:
        # 只看端口会骗人：半掉线时接口通、get_login_info 也正常，只有 online 是 false
        if napcat_online():
            print(f"NapCat   : 已登录 {napcat_identity()}")
        elif napcat_reachable():
            print("NapCat   : 半掉线（接口通，但 online=false）")
            print("           要杀掉 NapCat 重启并重新扫码，stop/start 修不好")
        elif napcat_webui_up():
            print("NapCat   : 已启动，小号未登录（停在扫码界面）")
        else:
            print("NapCat   : 未响应")
        if qr_window_process() is not None:
            print("扫码窗口 : 开着")
    print(f"日志     : {LOG_FILE}")
    return 0


def cmd_restart() -> int:
    cmd_stop()
    print()
    time.sleep(1)
    return cmd_start()


COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        return 2
    return COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
