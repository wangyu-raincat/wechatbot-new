# -*- coding: utf-8 -*-
"""QQ 小号扫码登录窗口。

`qqbot_ctl.py` 在「NapCat 起来了但小号没登录」时拉起本窗口，显示登录
二维码。二维码本身取自 NapCat 自己写在 `D:\\napcat\\cache\\qrcode.png`
的那张 —— 每次换码（约两分钟过期）NapCat 都会重写该文件，所以本窗口
只要盯着 mtime，看到变化就重新加载，屏幕上永远是能扫的那张。

`get_status` 报 `online: true` 时自动关窗，不需要人工点确认。

单独运行等价：`.venv\\Scripts\\pythonw.exe` 二维码窗口.pyw
"""

from __future__ import annotations

import json
import socket
import time
import tkinter as tk
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent

try:
    import config as _cfg
except Exception:  # 配置损坏时用默认值，窗口本身仍要能开
    _cfg = None

HTTP = str(getattr(_cfg, "QQ_ONEBOT_HTTP", "http://127.0.0.1:3000")).rstrip("/")
TOKEN = getattr(_cfg, "QQ_ONEBOT_TOKEN", "") or ""
SELF_ID = getattr(_cfg, "QQ_SELF_ID", 0) or ""
LAUNCHER = Path(str(getattr(_cfg, "QQ_NAPCAT_LAUNCHER", r"D:\napcat\launcher-win10-user.bat")))
NAPCAT_DIR = LAUNCHER.parent
QRCODE_PNG = NAPCAT_DIR / "cache" / "qrcode.png"

POLL_MS = 1500          # 轮询间隔（毫秒）
MAX_SECONDS = 600       # 窗口最长存活时间，超时自己关掉
QR_PIXELS = 340         # 二维码显示边长


def headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def online() -> bool:
    """小号是否真在线。半掉线时 get_login_info 照样成功，只有这个判据靠得住。"""
    try:
        data = requests.post(f"{HTTP}/get_status", headers=headers(), timeout=3).json()
    except Exception:
        return False
    return bool((data.get("data") or {}).get("online"))


def webui_port() -> int:
    try:
        data = json.loads((NAPCAT_DIR / "config" / "webui.json").read_text(encoding="utf-8"))
        return int(data.get("port") or 6099)
    except Exception:
        return 6099


def webui_up() -> bool:
    """NapCat 的 WebUI 端口是否在听 —— 用来区分「还在启动」和「彻底的没起来」。"""
    with socket.socket() as sock:
        sock.settimeout(1.5)
        return sock.connect_ex(("127.0.0.1", webui_port())) == 0


def read_qr(path: Path):
    """把二维码读成 Tk 能用的图片。优先 PIL（能按像素精确缩放），退回 Tk 自带解码。"""
    try:
        from PIL import Image, ImageTk

        image = Image.open(path).convert("RGB")
        # 用 NEAREST 而不是默认的双线性：二维码放大不能糊，糊了扫不出来
        image = image.resize((QR_PIXELS, QR_PIXELS), Image.NEAREST)
        return ImageTk.PhotoImage(image)
    except Exception:
        photo = tk.PhotoImage(file=str(path))
        factor = max(1, photo.width() // QR_PIXELS)
        return photo.subsample(factor, factor) if factor > 1 else photo


class QRWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"扫码登录 QQ 小号 {SELF_ID}".strip())
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(padx=20, pady=16, bg="white")

        self.started = time.time()
        self.seen_qr_mtime: float | None = None
        self.photo = None
        self.qr_item: int | None = None

        title = f"用手机 QQ 扫码登录小号 {SELF_ID}" if SELF_ID else "用手机 QQ 扫码登录小号"
        tk.Label(self, text=title, font=("Microsoft YaHei UI", 13, "bold"), bg="white").pack()

        self.canvas = tk.Canvas(self, width=QR_PIXELS, height=QR_PIXELS,
                                bg="#f2f2f2", highlightthickness=0)
        self.canvas.pack(pady=(12, 8))
        self.placeholder = self.canvas.create_text(
            QR_PIXELS // 2, QR_PIXELS // 2, text="正在等待二维码…",
            fill="#888", font=("Microsoft YaHei UI", 11), width=QR_PIXELS - 40, justify="center")

        self.status = tk.StringVar(value="正在检查登录状态…")
        tk.Label(self, textvariable=self.status, font=("Microsoft YaHei UI", 10),
                 fg="#444", bg="white", wraplength=QR_PIXELS).pack()

        tk.Label(self, text=f"扫不到？WebUI：http://localhost:{webui_port()}",
                 font=("Microsoft YaHei UI", 9), fg="#999", bg="white").pack(pady=(8, 0))

        self.lift()
        self.after(300, self.tick)

    def tick(self) -> None:
        if online():
            self.finish("登录成功，窗口即将关闭", close_after=600)
            return

        refreshed = self.load_qr()
        elapsed = int(time.time() - self.started)

        if self.seen_qr_mtime is None:
            self.status.set("NapCat 已启动，正在生成二维码…" if webui_up()
                            else "NapCat 还没就绪，继续等待…")
        elif refreshed:
            self.status.set("二维码已刷新，请在手机上确认登录")
        else:
            self.status.set(f"等待扫码…（{elapsed} 秒，二维码过期会自动刷新）")

        if elapsed > MAX_SECONDS:
            self.finish("等待超时，窗口关闭。可重新运行启动入口。", close_after=2500)
            return

        self.after(POLL_MS, self.tick)

    def load_qr(self) -> bool:
        """文件有更新就换图，返回是否真的换了。"""
        try:
            mtime = QRCODE_PNG.stat().st_mtime
        except OSError:
            return False
        if mtime == self.seen_qr_mtime:
            return False

        try:
            photo = read_qr(QRCODE_PNG)
        except Exception:
            return False

        self.photo = photo  # 必须留引用，否则会被 GC 掉变成空白
        if self.placeholder is not None:
            self.canvas.delete(self.placeholder)
            self.placeholder = None
            self.qr_item = self.canvas.create_image(QR_PIXELS // 2, QR_PIXELS // 2, image=self.photo)
        else:
            self.canvas.itemconfigure(self.qr_item, image=self.photo)
        self.seen_qr_mtime = mtime
        return True

    def finish(self, message: str, close_after: int) -> None:
        self.status.set(message)
        self.after(close_after, self.destroy)


if __name__ == "__main__":
    QRWindow().mainloop()
