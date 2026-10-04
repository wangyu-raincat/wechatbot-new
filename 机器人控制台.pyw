"""Small non-technical control panel for configuring and running the bot."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
import winreg

import psutil
import requests
from openai import OpenAI


ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "机器人后台.pid"
LOG_FILE = ROOT / "机器人后台.log"
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"

# 控制台文案与启动前检查都跟随 config.PLATFORM
try:
    from config import LISTEN_LIST, PLATFORM as _PLATFORM
except Exception:  # 配置损坏时不应导致控制台打不开
    LISTEN_LIST, _PLATFORM = [], "wechat"

IS_QQ = _PLATFORM == "qq"
PLATFORM_LABEL = "QQ" if IS_QQ else "微信"


def listening_summary() -> str:
    names = [str(entry[0]) for entry in LISTEN_LIST if entry]
    return "、".join(names) if names else "未配置"


def qq_api_reachable() -> bool:
    """QQ 模式下确认 NapCat 的 HTTP 接口可用（替代微信进程检查）。"""
    try:
        from config import QQ_ONEBOT_HTTP, QQ_ONEBOT_TOKEN
    except Exception:
        return True
    headers = {"Authorization": f"Bearer {QQ_ONEBOT_TOKEN}"} if QQ_ONEBOT_TOKEN else {}
    try:
        resp = requests.post(f"{QQ_ONEBOT_HTTP.rstrip('/')}/get_login_info",
                             headers=headers, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def saved_key() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            return str(winreg.QueryValueEx(key, "DEEPSEEK_API_KEY")[0]).strip()
    except OSError:
        return ""


def bot_process():
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        process = psutil.Process(pid)
        if process.is_running() and "background_runner.pyw" in " ".join(process.cmdline()):
            return process
    except (OSError, ValueError, psutil.Error):
        pass
    return None


class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{PLATFORM_LABEL}小号 AI 控制台")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(padx=22, pady=18)

        tk.Label(self, text=f"{PLATFORM_LABEL}小号 AI", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        self.status = tk.StringVar()
        tk.Label(self, textvariable=self.status, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(8, 16))

        key_row = tk.Frame(self)
        key_row.pack(fill="x")
        tk.Label(key_row, text="DeepSeek Key：").pack(side="left")
        self.key_entry = tk.Entry(key_row, show="●", width=38)
        self.key_entry.pack(side="left", padx=6)
        tk.Button(key_row, text="验证并保存", command=self.save_key).pack(side="left")

        buttons = tk.Frame(self)
        buttons.pack(fill="x", pady=18)
        tk.Button(buttons, text="启动机器人", width=14, height=2, command=self.start_bot).pack(side="left", padx=(0, 10))
        tk.Button(buttons, text="停止机器人", width=14, height=2, command=self.stop_bot).pack(side="left", padx=10)
        tk.Button(buttons, text="刷新状态", width=14, height=2, command=self.refresh).pack(side="left", padx=10)

        tk.Label(self, text="最近日志", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.log_box = tk.Text(self, height=11, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(5, 0))
        self.refresh()

    def refresh(self):
        running = bot_process() is not None
        key_ok = bool(saved_key())
        self.status.set(
            f"机器人：{'运行中' if running else '已停止'}    "
            f"DeepSeek：{'已配置' if key_ok else '未配置'}    监听：{listening_summary()}"
        )
        text = "暂无日志"
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            text = "\n".join(lines[-12:]) or text
        except OSError:
            pass
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("1.0", text)
        self.log_box.configure(state="disabled")

    def save_key(self):
        api_key = self.key_entry.get().strip()
        if not api_key:
            messagebox.showwarning("未输入", "请输入 DeepSeek API Key。")
            return
        self.status.set("正在验证 DeepSeek Key……")

        def worker():
            try:
                response = OpenAI(api_key=api_key, base_url="https://api.deepseek.com").chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": "只回复OK"}],
                    max_tokens=8,
                    temperature=0,
                )
                if response.choices[0].message.content.strip() != "OK":
                    raise RuntimeError("接口返回异常")
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "DEEPSEEK_API_KEY", 0, winreg.REG_SZ, api_key)
                self.after(0, lambda: messagebox.showinfo("成功", "DeepSeek Key 已验证并保存。"))
                self.after(0, lambda: self.key_entry.delete(0, "end"))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("验证失败", f"{type(exc).__name__}：请检查 Key 和网络。"))
            finally:
                self.after(0, self.refresh)

        threading.Thread(target=worker, daemon=True).start()

    def start_bot(self):
        if bot_process():
            messagebox.showinfo("已经运行", "机器人已经在后台运行。")
            return
        if not saved_key():
            messagebox.showwarning("尚未配置", "请先输入 DeepSeek Key，并点击“验证并保存”。")
            return
        if IS_QQ:
            # NapCat 没跑就拉起来，小号没登录就弹扫码窗口；都在后台线程里做，别卡住界面
            self.status.set("正在准备 NapCat（小号没登录会自动弹出扫码窗口）……")
            threading.Thread(target=self.prepare_napcat_and_start, daemon=True).start()
            return
        if not any((p.info["name"] or "").lower() == "weixin.exe" for p in psutil.process_iter(["name"])):
            messagebox.showwarning("微信未运行", "请先登录电脑微信小号。")
            return
        self.launch_bot()

    def prepare_napcat_and_start(self):
        """后台把 NapCat 弄到在线（必要时等扫码），再启动机器人。"""
        try:
            import qqbot_ctl
        except Exception:  # config 损坏时 qqbot_ctl 会直接退出，退回最简单的可达性检查
            qqbot_ctl = None
        ok = qqbot_ctl.ensure_napcat() if qqbot_ctl else qq_api_reachable()
        if not ok:
            self.after(0, lambda: messagebox.showwarning(
                "NapCat 起不来",
                "启动器不可用，机器人会收不到消息。\n\n"
                "请检查 config.py 里的 QQ_NAPCAT_LAUNCHER，"
                "或手工启动 NapCat 并扫码登录后重试。",
            ))
            self.after(0, self.refresh)
            return
        self.after(0, self.launch_bot)

    def launch_bot(self):
        if bot_process():
            self.refresh()
            return
        subprocess.Popen(
            [str(PYTHONW), str(ROOT / "background_runner.pyw")],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        self.after(1800, self.refresh)

    def stop_bot(self):
        process = bot_process()
        if not process:
            self.refresh()
            return
        try:
            process.terminate()
            process.wait(5)
        except psutil.TimeoutExpired:
            process.kill()
        except psutil.Error:
            pass
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        self.refresh()


if __name__ == "__main__":
    ControlPanel().mainloop()
