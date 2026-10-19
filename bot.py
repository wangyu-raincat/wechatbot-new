# -*- coding: utf-8 -*-
# 微信自动回复。版权与许可证见 LICENSE（GPL-3.0 或更高版本）。
# 基于 KouriChat / WeChatBot 的收发循环精简而来。

import json
import logging
import os
import re
import threading
import time
from datetime import datetime

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    LISTEN_LIST,
    MAX_GROUPS,
    MAX_TOKEN,
    MODEL,
    QUEUE_WAITING_TIME,
    TEMPERATURE,
)

logger = logging.getLogger("bot")

root_dir = os.path.dirname(os.path.abspath(__file__))
CHAT_CONTEXTS_FILE = os.path.join(root_dir, "chat_contexts.json")
PID_FILE = os.path.join(root_dir, "bot.pid")

_THINK_RE = re.compile(r"(?:</thought>|</think>)([\s\S]*)")
_SPLIT_RE = re.compile(r"[\\$]|\n+")
_TAG_RE = re.compile(r"\[(?:tickle_self|tickle|recall)\]")

queue_lock = threading.Lock()
user_queues = {}
chat_contexts = {}
group_flags = {}
stop_event = threading.Event()
_client = None


def parse_listen(items):
    """LISTEN_LIST -> [(昵称, 提示词文件名), ...]。"""
    pairs = []
    for entry in items or []:
        if not isinstance(entry, (list, tuple)) or not entry or not str(entry[0]).strip():
            raise ValueError("LISTEN_LIST 的每一项都要写成 [昵称或群名, 提示词文件名]")
        name = str(entry[0]).strip()
        prompt = "角色1"
        if len(entry) > 1 and str(entry[1]).strip():
            prompt = str(entry[1]).strip()
        if prompt.lower().endswith(".md"):
            prompt = prompt[:-3]
        if not prompt or "/" in prompt or "\\" in prompt or prompt.startswith("."):
            raise ValueError("提示词文件名不合法: %s" % prompt)
        pairs.append((name, prompt))
    return pairs


def prompt_path(prompt_name):
    return os.path.join(root_dir, "prompts", prompt_name + ".md")


def read_prompt(prompt_name):
    path = prompt_path(prompt_name)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def visible_reply(text):
    if not text:
        return ""
    match = _THINK_RE.search(text)
    if match:
        text = match.group(1)
    return text.strip()


def split_reply(text):
    """按反斜线、$ 或换行拆成多条微信消息。拍一拍/撤回标记直接丢掉。"""
    text = _TAG_RE.sub("", visible_reply(text))
    return [part.strip() for part in _SPLIT_RE.split(text) if part and part.strip()]


def trim_history(history, max_groups=None):
    limit = max(2, int(max_groups if max_groups is not None else MAX_GROUPS) * 2)
    if len(history) > limit:
        return history[-limit:]
    return list(history)


def incoming_text(msg):
    """把一条微信消息收成要交给模型的文字。自己发的、空的、系统通知返回 None。"""
    attr = getattr(msg, "attr", "friend")
    if attr == "self":
        return None
    if attr not in ("friend", "tickle"):
        return None
    content = (getattr(msg, "content", "") or "").strip()
    if attr == "tickle":
        if "我拍了拍" in content:
            return None
        return ("[拍一拍] " + content).strip() if content else "[拍一拍]"

    mtype = getattr(msg, "type", "text") or "text"
    if mtype == "system":
        return None
    if mtype == "merge":
        lines = []
        try:
            records = msg.get_messages() or []
        except Exception:
            records = []
        for item in records:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                lines.append("%s: %s" % (item[0], item[1]))
        content = "[合并转发]\n" + "\n".join(lines) if lines else (content or "[合并转发]")
    elif mtype == "link":
        url = ""
        try:
            url = msg.get_url() or ""
        except Exception:
            url = ""
        content = (content + " " + url).strip() or "[链接]"
    elif not content:
        content = {
            "image": "[图片]",
            "emotion": "[动画表情]",
            "voice": "[语音]",
            "video": "[视频]",
            "file": "[文件]",
            "location": "[位置]",
        }.get(mtype, "")
    if not content:
        return None
    if len(content) > 4000:
        content = content[:4000]
    return content


def load_contexts():
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return {}
    try:
        with open(CHAT_CONTEXTS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning("读取聊天上下文失败，从空记录开始: %s", exc)
        return {}


def save_contexts():
    tmp = CHAT_CONTEXTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(chat_contexts, handle, ensure_ascii=False)
    os.replace(tmp, CHAT_CONTEXTS_FILE)


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=60,
        )
    return _client


def call_model(messages):
    last_error = ""
    for attempt in range(3):
        try:
            response = get_client().chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKEN,
                stream=False,
            )
            content = ""
            if response.choices:
                content = response.choices[0].message.content or ""
            reply = visible_reply(content)
            if reply:
                return reply
            last_error = "模型返回了空内容"
        except Exception as exc:
            last_error = str(exc)
            logger.warning("调用模型失败（第 %d 次）: %s", attempt + 1, last_error)
            if any(flag in last_error.lower() for flag in ("api key", "invalid", "payment", "quota", "insufficient")):
                break
            time.sleep(1)
    logger.error("调用 %s 失败: %s", MODEL, last_error or "空内容")
    return ""


def ask(user_id, prompt_name, user_text):
    stamped = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"), user_text)
    with queue_lock:
        history = trim_history(chat_contexts.get(user_id, []))
    messages = [{"role": "system", "content": read_prompt(prompt_name)}]
    messages.extend(history)
    messages.append({"role": "user", "content": stamped})
    reply = call_model(messages)
    if not reply:
        return ""
    with queue_lock:
        updated = trim_history(chat_contexts.get(user_id, []))
        updated.append({"role": "user", "content": stamped})
        updated.append({"role": "assistant", "content": reply})
        chat_contexts[user_id] = trim_history(updated)
        save_contexts()
    return reply


def enqueue(who, text):
    with queue_lock:
        slot = user_queues.setdefault(who, {"messages": [], "last": 0.0})
        slot["messages"].append(text)
        slot["last"] = time.time()


def on_message(msg, chat):
    who = getattr(chat, "who", "") or ""
    text = incoming_text(msg)
    if not text or who not in group_flags:
        return
    sender = getattr(msg, "sender", "") or ""
    if group_flags.get(who) and sender:
        text = "%s: %s" % (sender, text)
    logger.info("收到 %s: %s", who, text[:80])
    enqueue(who, text)


def send_reply(wx, who, reply):
    parts = split_reply(reply)
    if not parts:
        logger.warning("回复是空的，不发送: %s", who)
        return
    for index, part in enumerate(parts):
        sent = False
        for attempt in range(3):
            try:
                if wx.SendMsg(msg=part, who=who):
                    sent = True
                    logger.info("已发给 %s: %s", who, part[:60])
                    break
                logger.warning("发送失败，重试 %d/3: %s", attempt + 1, who)
            except Exception as exc:
                logger.warning("发送异常，重试 %d/3: %s", attempt + 1, exc)
            time.sleep(0.6)
        if not sent:
            logger.error("发给 %s 失败: %s", who, part[:60])
            return
        if index < len(parts) - 1:
            time.sleep(0.8)


def worker(wx, prompt_of):
    while not stop_event.is_set():
        time.sleep(0.4)
        now = time.time()
        ready = []
        with queue_lock:
            for who, slot in user_queues.items():
                if slot["messages"] and now - slot["last"] >= QUEUE_WAITING_TIME:
                    ready.append(who)
        for who in ready:
            with queue_lock:
                slot = user_queues.pop(who, None)
            if not slot or not slot["messages"]:
                continue
            merged = "\n".join(slot["messages"])
            logger.info("回复 %s: %s", who, merged[:80])
            try:
                reply = ask(who, prompt_of[who], merged)
            except Exception:
                logger.exception("生成回复失败: %s", who)
                continue
            if reply:
                send_reply(wx, who, reply)


def _prevent_sleep(enable):
    if os.name != "nt":
        return
    try:
        import ctypes

        es_continuous = 0x80000000
        es_system_required = 0x00000001
        flags = es_continuous | es_system_required if enable else es_continuous
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception as exc:
        logger.warning("设置休眠状态失败: %s", exc)


def _write_pid():
    with open(PID_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        pairs = parse_listen(LISTEN_LIST)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    if not pairs:
        logger.error("监听名单是空的。复制 config_local.example.py 为 config_local.py，填上对方的微信昵称或群名。")
        return 1
    if not (DEEPSEEK_API_KEY or "").strip():
        logger.error("没有 API Key。请设置用户环境变量 DEEPSEEK_API_KEY。")
        return 1

    prompt_of = {}
    for name, prompt_name in pairs:
        path = prompt_path(prompt_name)
        if not os.path.isfile(path):
            logger.error("找不到提示词文件: %s", path)
            return 1
        prompt_of[name] = prompt_name

    import wxbot

    if wxbot._BACKEND_ERROR is not None:
        logger.error("微信自动化库不可用: %s", wxbot._BACKEND_ERROR)
        logger.error("请在已登录微信的 Windows 上执行: pip install -r requirements.txt")
        return 1

    logger.info("正在连接微信...")
    try:
        wx = wxbot.WeChat()
    except Exception as exc:
        logger.error("连接微信失败。请先登录电脑微信，并保持窗口不要锁屏。%s", exc)
        return 1

    for name, _prompt_name in pairs:
        group_flags[name] = False
        chat = wx.AddListenChat(nickname=name, callback=on_message)
        if not chat:
            logger.error("监听 %s 失败。昵称或群名必须和微信里显示的完全一致。", name)
            return 1
        group_flags[name] = wx.GetListenChatType(name) == "group"
        kind = "群聊" if group_flags[name] else "私聊"
        logger.info("正在监听%s: %s", kind, name)

    global chat_contexts
    chat_contexts = load_contexts()
    _write_pid()
    _prevent_sleep(True)
    threading.Thread(target=worker, args=(wx, prompt_of), name="reply", daemon=True).start()
    logger.info("机器人已启动。在这个窗口按 Ctrl+C 停止，或运行 停止机器人.cmd。")
    try:
        # KeepRunning 自己吃掉 Ctrl+C 然后返回，这里不要再套一层死循环。
        wx.KeepRunning()
    except KeyboardInterrupt:
        logger.info("正在停止。")
    finally:
        stop_event.set()
        _prevent_sleep(False)
        _remove_pid()
        logger.info("已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
