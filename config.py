# -*- coding: utf-8 -*-
# 核心配置。本机名单和账号写在 config_local.py（已被 Git 忽略）。
# API Key 放在用户环境变量 DEEPSEEK_API_KEY，不要写进仓库。

import os


def _read_user_environment(name):
    """优先读 Windows 用户环境变量，没有再读当前进程的环境变量。"""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                value = str(winreg.QueryValueEx(key, name)[0]).strip()
            if value:
                return value
        except (FileNotFoundError, OSError):
            pass
    return os.environ.get(name, "").strip()


# 留空时由底层自动选择当前登录的微信。多开时才需要填账号标识。
WECHAT_ACCOUNT = _read_user_environment("WECHAT_ACCOUNT")

# 要自动回复的会话。[微信昵称或群名, 提示词文件名（不含 .md）]
# 实际名单写在 config_local.py。
LISTEN_LIST = []

# OpenAI 兼容接口。DeepSeek 官方示例：
#   DEEPSEEK_BASE_URL = "https://api.deepseek.com"
#   MODEL = "deepseek-chat"
DEEPSEEK_API_KEY = _read_user_environment("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"
MAX_TOKEN = 2000
TEMPERATURE = 1.0

# 每个会话保留最近多少轮（一问一答算一轮）
MAX_GROUPS = 12

# 对方连续发消息时，静默这么多秒再合并成一次回复
QUEUE_WAITING_TIME = 4

try:
    from config_local import *  # noqa: F401,F403
except ModuleNotFoundError as exc:
    if exc.name != "config_local":
        raise
