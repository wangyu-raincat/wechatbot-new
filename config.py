# -*- coding: utf-8 -*-

import os


def _read_user_environment(name):
    """Read a per-user secret without embedding it in the repository.

    Windows 上以注册表为准：本项目的两个写入方（控制台的「验证并保存」与
    setup_deepseek_key.py）都写 HKCU\\Environment。若反过来先读 os.environ，
    长驻进程里残留的旧值会静默盖掉用户刚保存的新值 —— 环境变量一旦被进程
    继承就固定不变，之后改注册表也不会同步过去。
    注册表里没有时才回退到环境变量，以兼容只在 shell 里临时设置的情况。
    """
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment') as key:
                value = str(winreg.QueryValueEx(key, name)[0]).strip()
            if value:
                return value
        except (FileNotFoundError, OSError):
            pass
    return os.environ.get(name, '').strip()

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# ***********************************************************************

# 临时固定机器人运行账号（大号）。留空时由底层自动选择账号。
WECHAT_ACCOUNT = _read_user_environment('WECHAT_ACCOUNT')

# 用户列表(请配置要和bot说话的账号！)
# 微信模式(PLATFORM='wechat')：填微信昵称/备注，例如 [['微信名1', '角色1']]
# QQ 模式 (PLATFORM='qq')    ：填 QQ 号或群号，也可填好友昵称/群名，
#                              例如 [['10001', '角色1'], ['987654321', '角色2']]
# ⚠️ 填的是「跟机器人说话的人」，不是机器人自己登录的号！
# QQ 模式下务实用号码：昵称会变，而且容易和机器人自己的昵称撞上。
LISTEN_LIST = []

# DeepSeek API 配置
DEEPSEEK_API_KEY = _read_user_environment('DEEPSEEK_API_KEY')
# 硅基流动API注册地址，免费15元额度 https://cloud.siliconflow.cn/i/Dlavkw5R
DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
# 硅基流动API的模型
MODEL = 'deepseek-chat'
# 用户和AI对话轮数
MAX_GROUPS = 12

# 如果要使用官方的API
# DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
# 官方API的V3模型
# MODEL = 'deepseek-chat'

# 回复最大token
MAX_TOKEN = 2000
# DeepSeek温度
# 0.7 太稳，短句上会反复说同一句话（问两次「在忙」两次都回「忙你的」）。
# 调到 1.0 换口语的自然随机性；再往上（1.3 是官方创意写作推荐值）会更活泼
# 但偶尔会答非所问。
TEMPERATURE = 1.0

# 图片/表情包识别的 API 配置（Web UI 里选服务商：月之暗面 / DeepSeek官方 / WeAPIs / 其它）
# DeepSeek 官方已支持图片输入，用同一套字段即可：
#   MOONSHOT_BASE_URL = 'https://api.deepseek.com'
#   MOONSHOT_MODEL = 'deepseek-flash'
#   下面这个 API Key 填 DeepSeek 官方 Key（与 Chat 的 DEEPSEEK_API_KEY 可以不同）
MOONSHOT_API_KEY = _read_user_environment('MOONSHOT_API_KEY')
MOONSHOT_BASE_URL = 'https://api.deepseek.com'
MOONSHOT_MODEL = 'deepseek-flash'
MOONSHOT_TEMPERATURE = 0.5
ENABLE_IMAGE_RECOGNITION = False
ENABLE_EMOJI_RECOGNITION = False

# 消息队列等待时间
QUEUE_WAITING_TIME = 4

# 表情包存放目录
EMOJI_DIR = 'emojis'
ENABLE_EMOJI_SENDING = True
EMOJI_SENDING_PROBABILITY = 35

# 自动消息配置
AUTO_MESSAGE = '请你模拟系统设置的角色，主动找对方继续刚刚的话题，或者问问对方在做什么'
ENABLE_AUTO_MESSAGE = True
# 等待时间
MIN_COUNTDOWN_HOURS = 1.0
MAX_COUNTDOWN_HOURS = 3.0
# 消息发送时间限制
QUIET_TIME_START = '23:30'
QUIET_TIME_END = '8:00'
# 不对群聊发送自动消息
IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE = True

# 消息回复时间间隔
# 间隔时间 = 字数 * (平均时间 + 随机时间)
AVERAGE_TYPING_SPEED = 0.08
RANDOM_TYPING_SPEED_MIN = 0.02
RANDOM_TYPING_SPEED_MAX = 0.08
SEPARATE_ROW_SYMBOLS = True

# 记忆功能
# 采用综合评分公式：0.6*重要度 - 0.4*(存在时间小时数)
# 示例：
# 重要度5的旧记忆（存在12小时）得分：0.65 - 0.412 = 3 - 4.8 = -1.8
# 重要度4的新记忆（存在1小时）得分：0.64 - 0.41 = 2.4 - 0.4 = 2.0 → 保留新记忆
ENABLE_MEMORY = True
MEMORY_TEMP_DIR = 'Memory_Temp'
MAX_MESSAGE_LOG_ENTRIES = 30
MAX_MEMORY_NUMBER = 50
UPLOAD_MEMORY_TO_AI = True
# 记忆存储方式：True = 保存到单独的JSON文件，False = 保存到prompt文件中
SAVE_MEMORY_TO_SEPARATE_FILE = True
CORE_MEMORY_DIR = 'CoreMemory'

# ===== 聊天记录风格模仿 与 上下文读取 =====
# 名单里的用户：不再使用他的 Prompt 文件，改用「读取聊天记录」生成的风格档案
# （保存在 HistoryProfiles/<昵称>.md，在配置页的用户列表里勾选并生成）
HISTORY_STYLE_USERS = []
# 风格档案目录（相对程序根目录）
HISTORY_PROFILE_DIR = 'HistoryProfiles'
# 生成档案时读最近多少条聊天记录
HISTORY_READ_LIMIT = 60
# 用哪个模型生成风格档案；留空 = 用「Chat 模型配置」里的 MODEL。
# API 地址与 Key 仍沿用 Chat 模型那一套（只换模型名）
HISTORY_PROFILE_MODEL = ''
# 风格档案最长多少字符（超出截断，避免吃光上下文）
HISTORY_PROFILE_MAX_CHARS = 3000

# 未启用风格档案的用户：启动时先预读一次聊天记录做背景，
# 之后由模型判断这条消息是否需要更多上下文，需要时再重新读一次
ENABLE_CONTEXT_FETCH = True
# 每次读取最近多少条消息
CONTEXT_MESSAGE_LIMIT = 30
# 注入的背景文本上限（字符）
CONTEXT_MAX_CHARS = 2500

# 是否接收全部群聊消息
ACCEPT_ALL_GROUP_CHAT_MESSAGES = False
ENABLE_GROUP_AT_REPLY = True
ENABLE_GROUP_KEYWORD_REPLY = True
GROUP_KEYWORD_LIST = []
GROUP_CHAT_RESPONSE_PROBABILITY = 0
GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY = True

# 登录配置编辑器设置
ENABLE_LOGIN_PASSWORD = False
LOGIN_PASSWORD = _read_user_environment('BOT_LOGIN_PASSWORD')
PORT = 5000

# 文字指令识别开关
# 开启后，私聊/群聊（满足触发条件）中以“/”开头的指令将被解析并执行
ENABLE_TEXT_COMMANDS = True

# 定时器/提醒设置
# 启用提醒功能
ENABLE_REMINDERS = True
# 是否允许在安静时间内发送提醒 (True/False)
# 如果设置为 False，则在安静时间内安排的提醒将被跳过。
ALLOW_REMINDERS_IN_QUIET_TIME = True
# 是否使用语音通话进行提醒
# 群聊无法使用语音通话进行提醒
USE_VOICE_CALL_FOR_REMINDERS = False

# 防撤回：挂载后把监听会话的消息镜像到本地（只读微信库 + 写自己的镜像目录，
# 不驱动界面），对方撤回后用 /撤回 指令可以看到原文。镜像目录见
# ~/Documents/wechatauto_recall
ENABLE_RECALL_GUARD = True
# 启动时把每个会话最近多少条历史消息补进镜像（0 = 不补）
RECALL_BACKFILL = 50
# 撤回轮询间隔（秒）
RECALL_SCAN_INTERVAL = 2.0
# 每会话每轮重读最近多少条消息用于比对
RECALL_SCAN_LIMIT = 30
# 发现新的撤回时，由机器人往那个会话发一条提醒（含原文）。会主动发消息，默认关
ENABLE_RECALL_NOTICE = False

# 文本指令 /朋友圈（或 /pyq）：查看发指令者（或指定昵称）最近的朋友圈动态
# 读本地 sns.db，不打开微信界面
ENABLE_MOMENTS_COMMAND = True
# /朋友圈 每次返回的条数（也可在指令后面直接跟数字，如「/朋友圈 10」）
MOMENTS_QUERY_LIMIT = 5
# /朋友圈互动（或 /pyqi）：查询「谁赞了/评论了你的朋友圈」。含账号社交信息，默认关
ENABLE_MOMENTS_INTERACTIONS = False
# 朋友圈监听：轮询监听对象的新动态，等对方下次发消息时随上下文告知模型
ENABLE_MOMENTS_WATCH = False
# 朋友圈监听轮询间隔（秒，最小 30）
MOMENTS_WATCH_INTERVAL = 120

# 联网API配置
ENABLE_ONLINE_API = False
ONLINE_BASE_URL = 'https://vg.v1api.cc/v1'
ONLINE_MODEL = 'deepseek-r1-searching'
ONLINE_API_KEY = _read_user_environment('ONLINE_API_KEY')
ONLINE_API_TEMPERATURE = 0.5
ONLINE_API_MAX_TOKEN = 2000
SEARCH_DETECTION_PROMPT = '是否需要查询今天的天气、最新的新闻事件、特定网站的内容、股票价格、特定人物的最新动态、歌词、小说情节、游戏内容、网络热梗、历史信息等'
ONLINE_FIXED_PROMPT = ''

# 是否启用自动抓取消息中URL链接内容的功能
ENABLE_URL_FETCHING = False
# 网络请求超时时间 (秒)
REQUESTS_TIMEOUT = 10
# 抓取网页时使用的 User-Agent，模拟浏览器防止被屏蔽
# REQUESTS_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
# REQUESTS_USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
REQUESTS_USER_AGENT = 'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36'
# 从网页提取内容的最大字符数，防止上下文过长，影响AI处理效率和成本
MAX_WEB_CONTENT_LENGTH = 2000

# 定时重启配置
ENABLE_SCHEDULED_RESTART = False
RESTART_INTERVAL_HOURS = 2.0
RESTART_INACTIVITY_MINUTES = 15

# 强制移除括号当中的内容
REMOVE_PARENTHESES = False

# 是否使用辅助模型
ENABLE_ASSISTANT_MODEL = False
ASSISTANT_BASE_URL = 'https://vg.v1api.cc/v1'
ASSISTANT_MODEL = 'gpt-4o-mini'
ASSISTANT_API_KEY = _read_user_environment('ASSISTANT_API_KEY')
ASSISTANT_TEMPERATURE = 0.3
ASSISTANT_MAX_TOKEN = 1000
USE_ASSISTANT_FOR_MEMORY_SUMMARY = True

# 敏感词处理配置
# 开启后遇到敏感词时自动清除Memory_Temp文件和聊天上下文
ENABLE_SENSITIVE_CONTENT_CLEARING = True

# 论坛自定义模型配置（可选）
ENABLE_FORUM_CUSTOM_MODEL = False
FORUM_BASE_URL = 'https://vg.v1api.cc/v1'
FORUM_MODEL = 'deepseek-ai/DeepSeek-V3'
FORUM_API_KEY = _read_user_environment('FORUM_API_KEY')
FORUM_TEMPERATURE = 1.0
FORUM_MAX_TOKEN = 1200

# ======================================================================
# 平台选择
# ======================================================================
# 'wechat' = 走 wxbot 兼容层（数据库收信 + GUI 坐标/OCR 发信，需登录电脑微信）
# 'qq'     = 走 qqbot 兼容层（NapCat / OneBot v11，不需要桌面客户端）
PLATFORM = 'qq'

# ======================================================================
# QQ / NapCat (OneBot v11) 配置 —— 仅 PLATFORM = 'qq' 时生效
# ======================================================================
# NapCat WebUI → 网络配置 里新建「HTTP服务器」和「WebSocket服务器」，
# 两者都要启用 Token，并把下面的 token 填成一致的值。
QQ_ONEBOT_HTTP = 'http://127.0.0.1:3000'   # NapCat HTTP server 地址
QQ_ONEBOT_WS = 'ws://127.0.0.1:3001'       # NapCat WebSocket server 地址
QQ_ONEBOT_TOKEN = _read_user_environment('QQ_ONEBOT_TOKEN')  # 与 NapCat 网络配置一致
QQ_SELF_ID = 0  # 留 0 则启动时自动获取
QQ_AUTO_MARK_READ = True                   # 收到消息后标记已读
# NapCat 启动器路径。启动入口发现 NapCat 没在跑时会自动拉起它；留空则只做检查。
QQ_NAPCAT_LAUNCHER = _read_user_environment('QQ_NAPCAT_LAUNCHER')

# 可选的本地覆盖文件。config_local.py 已被 .gitignore 排除，适合存放
# LISTEN_LIST、账号标识和仅属于本机的路径；不要把它提交到版本库。
try:
    from config_local import *  # noqa: F401,F403
except ModuleNotFoundError as exc:
    if exc.name != 'config_local':
        raise


