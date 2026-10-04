# -*- coding: utf-8 -*-
"""
qqbot —— QQ 兼容层（OneBot v11 / NapCat）
让 WeChatBot 项目无需微信客户端即可运行在 QQ 上。

用法：把 bot.py 顶部的导入
    from wxbot import WeChat
改成
    from qqbot import WeChat
（或直接设 config.PLATFORM = 'qq'，bot.py 会自动切换）

底层由 NapCat 的 OneBot v11 接口驱动：
  * 消息接收走 WebSocket 事件流，延迟取决于 NapCat，通常 <1 秒。
  * 消息发送走 HTTP API，不依赖桌面窗口，锁屏也能发。
  * 相比微信路径（数据库解密 + 坐标/OCR），不要求登录桌面客户端、
    不要求保持桌面解锁，也不需要唤起任何窗口。

差异说明（相对 wxbot 微信路径）：
  * 表情包截图识别（capture）在 QQ 侧无对应能力，安全降级返回 None。
  * 语音通话（VoiceCall）OneBot 无此接口，降级返回 False。
  * 语音转文字优先取 QQ 自带的转写结果，取不到则尝试 fetch_ptt_text。
  * 拍一拍/撤回已接上 OneBot 的 friend_poke / group_poke / delete_msg。

接口对齐 wxbot.WeChat，使得 bot.py 的业务逻辑（记忆、提醒、表情包、
角色论坛、WebUI）无需任何改动。
"""

import base64
import json
import logging
import os
import re
import threading
import time

import requests
import websocket  # websocket-client

import config as _cfg

log = logging.getLogger("qqbot")

# ------------------------------------------------------------------ 配置

QQ_ONEBOT_HTTP = getattr(_cfg, 'QQ_ONEBOT_HTTP', 'http://127.0.0.1:3000')
QQ_ONEBOT_WS = getattr(_cfg, 'QQ_ONEBOT_WS', 'ws://127.0.0.1:3001')
QQ_ONEBOT_TOKEN = getattr(_cfg, 'QQ_ONEBOT_TOKEN', '')
QQ_SELF_ID = getattr(_cfg, 'QQ_SELF_ID', 0)
QQ_AUTO_MARK_READ = getattr(_cfg, 'QQ_AUTO_MARK_READ', True)

_IMG_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
_URL_RE = re.compile(r'https?://[^\s"\'<>\[\]]+')
_MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qq_media')

# 纯附件消息的占位文本（按 msg_type 索引）。
# 图片/表情/视频/文件这四类只带媒体段、不带文本段，content 会是空串，
# 而 bot.py 在 message_listener 末尾有一条「内容为空则忽略」的检查
# （bot.py:1316），位置在图片处理分支之前，会把整条消息丢掉。微信链路
# 靠 wxbot 给的 content 本身非空躲过了它，QQ 侧必须显式补上。
# 图片识别功能开启时，bot.py 会用识别结果覆盖这个占位符；关闭时它就是
# 最终交给 LLM 的内容。voice/link/quote/merge 不在表内 —— bot.py 自己
# 会拼出非空内容，不需要兜底。
_PLACEHOLDER = {
    'image': '[图片]',
    'emotion': '[动画表情]',
    'video': '[视频]',
    'file': '[文件]',
}

# 图片/表情等媒体留存目录
def _media_dir():
    os.makedirs(_MEDIA_DIR, exist_ok=True)
    return _MEDIA_DIR


def _to_text(x):
    if x is None:
        return ''
    if isinstance(x, bytes):
        try:
            return x.decode('utf-8', 'ignore')
        except Exception:
            return ''
    return str(x)


def _strip_tags(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    for a, b in (('&lt;', '<'), ('&gt;', '>'), ('&amp;', '&'), ('&quot;', '"'),
                 ('&apos;', "'"), ('&#10;', '\n'), ('&nbsp;', ' ')):
        text = text.replace(a, b)
    return re.sub(r'\s+', ' ', text).strip()


def _extract_url(blob):
    m = _URL_RE.search(blob)
    return m.group(0) if m else None


class _OneBotAPI:
    """OneBot v11 HTTP 调用封装（同步）。"""

    def __init__(self, base, token='', timeout=10):
        self.base = (base or '').rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        if token:
            self.session.headers['Authorization'] = 'Bearer ' + token

    def call(self, action, **params):
        """调用一个 action；成功返回 data，失败返回 None。"""
        if not self.base:
            log.error('未配置 QQ_ONEBOT_HTTP，无法调用 %s', action)
            return None
        url = '%s/%s' % (self.base, action)
        try:
            resp = self.session.post(url, json=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            log.warning('OneBot 调用 %s 失败: %s', action, e)
            return None
        # retcode: 0=成功, 1=异步已受理, 其它=错误
        if payload.get('status') == 'ok' and payload.get('retcode') in (0, 1):
            return payload.get('data')
        log.warning('OneBot %s 返回错误: %s', action, payload)
        return None


class QQChat:
    """对齐 wxbot 的 chat 对象：bot.py 只用到 .who 和 .ChatInfo()。"""

    def __init__(self, who, kind, ident, bot):
        self.who = who          # 监听键（LISTEN_LIST 里填的名字/号码）
        self._kind = kind       # 'group' / 'friend'
        self._id = ident        # 群号 / QQ号
        self._bot = bot

    def ChatInfo(self):
        return {'who': self.who, 'chat_type': self._kind}

    def __str__(self):
        return self.who

    def __repr__(self):
        return '<QQChat %s %s(%s)>' % (self.who, self._kind, self._id)


class QQMessage:
    """对齐 wxbot.WxMessage 的消息对象。

    bot.py 需要：.type .attr .content(可写) .sender .quote_content
                .to_text() .get_url() .get_messages() .download() .capture()
                .tickle() .select_option('撤回')
    """

    def __init__(self, bot, *, message_id=None, kind='friend', target_id=None,
                 user_id=None, sender='', content='', msg_type='text',
                 attr='friend', quote_content=None, link_url=None,
                 forward_id=None, image_seg=None, voice_seg=None):
        self._bot = bot
        self.message_id = message_id
        self.kind = kind
        self.target_id = target_id    # 会话对象：群号（群聊）/ 对方 QQ 号（私聊）
        self.user_id = user_id        # 这条消息的发出者 QQ 号（拍一拍要用）
        self.sender = sender
        self.content = content
        self.type = msg_type
        self.attr = attr
        self.quote_content = quote_content
        self._link_url = link_url
        self._forward_id = forward_id
        self._image_seg = image_seg
        self._voice_seg = voice_seg
        self._forward_cache = None

    # ------------------------------------------------------------ 事件解析

    @classmethod
    def from_event(cls, bot, event):
        """把一个 OneBot message 事件解析成 QQMessage。"""
        is_group = event.get('message_type') == 'group'
        kind = 'group' if is_group else 'friend'
        user_id = event.get('user_id')
        group_id = event.get('group_id')
        target_id = group_id if is_group else user_id

        sender_info = event.get('sender') or {}
        is_self = str(user_id) == str(bot.self_id)
        if is_self:
            sender = bot.nickname or '我'
        elif is_group:
            # 群名片优先，其次昵称，最后 QQ 号
            sender = (sender_info.get('card') or sender_info.get('nickname')
                      or str(user_id))
        else:
            sender = sender_info.get('nickname') or str(user_id)

        parsed = cls._parse_segments(bot, event.get('message') or [])

        return cls(
            bot,
            message_id=event.get('message_id'),
            kind=kind,
            target_id=target_id,
            user_id=(bot.self_id if is_self else user_id),
            sender=sender,
            msg_type=parsed['type'],
            attr='self' if is_self else 'friend',
            content=parsed['content'],
            quote_content=parsed['quote_content'],
            link_url=parsed['link_url'],
            forward_id=parsed['forward_id'],
            image_seg=parsed['image_seg'],
            voice_seg=parsed['voice_seg'],
        )

    @staticmethod
    def _parse_segments(bot, segs):
        """把 OneBot 消息段数组解析成 (类型, 文本内容, 各类附件)。"""
        texts = []
        image_seg = voice_seg = face_seg = video_seg = None
        forward_seg = reply_seg = card_seg = file_seg = None

        for seg in segs:
            if not isinstance(seg, dict):
                continue
            stype = seg.get('type')
            data = seg.get('data') or {}

            if stype == 'text':
                texts.append(_to_text(data.get('text')))
            elif stype == 'at':
                qq = str(data.get('qq', ''))
                if qq == 'all':
                    texts.append('@全体成员 ')
                elif qq == str(bot.self_id):
                    # ★ 归一化：bot.py 用正则 @{机器人昵称}  判断是否被 @，
                    #   QQ 的 at 段原始格式与之不同，必须在此转成它能命中的写法，
                    #   否则群聊永远不会触发回复。
                    texts.append('@%s ' % (bot.nickname or ''))
                else:
                    texts.append('@%s ' % (data.get('name') or qq))
            elif stype in ('image', 'flash'):
                image_seg = image_seg or seg
            elif stype == 'record':
                voice_seg = voice_seg or seg
            elif stype in ('face', 'mface'):
                face_seg = face_seg or seg
            elif stype == 'video':
                video_seg = video_seg or seg
            elif stype == 'forward':
                forward_seg = forward_seg or seg
            elif stype == 'reply':
                reply_seg = reply_seg or seg
            elif stype in ('json', 'xml'):
                card_seg = card_seg or seg
            elif stype == 'file':
                file_seg = file_seg or seg
            elif stype == 'markdown':
                texts.append(_to_text(data.get('content')))

        content = ''.join(texts).strip()

        # 解析引用消息的被引用内容
        quote_content = None
        if reply_seg:
            rid = (reply_seg.get('data') or {}).get('id')
            if rid:
                quote_content = bot._fetch_message_summary(rid)

        # 解析卡片链接
        link_url = None
        card_is_quote = False
        if card_seg:
            blob = _to_text((card_seg.get('data') or {}).get('data'))
            link_url = _extract_url(blob)
            if not link_url:
                # 形如 <refermsg> 的卡片按引用消息处理
                if '<refermsg' in blob or '<appmsg' in blob:
                    card_is_quote = True
                    m = re.search(r'<title>(.*?)</title>', blob, re.S)
                    quote_content = (_strip_tags(m.group(1)) if m
                                     else _strip_tags(blob)[:200])
                else:
                    link_url = _extract_url(json.dumps(card_seg.get('data') or {}))

        forward_id = (forward_seg.get('data') or {}).get('id') if forward_seg else None

        # 类型判定优先级：与微信路径的 _TYPE_MAP 语义对齐
        if forward_id:
            msg_type = 'merge'
        elif reply_seg or card_is_quote:
            msg_type = 'quote'
        elif voice_seg:
            msg_type = 'voice'
        elif image_seg:
            msg_type = 'image'
        elif face_seg:
            msg_type = 'emotion'
        elif card_seg:
            msg_type = 'link' if link_url else 'file'
        elif video_seg:
            msg_type = 'video'
        elif file_seg:
            msg_type = 'file'
        else:
            msg_type = 'text'

        # 纯附件消息补占位符，否则会被 bot.py 的「内容为空」检查丢弃（见 _PLACEHOLDER）
        if not content:
            content = _PLACEHOLDER.get(msg_type, '')

        return {
            'type': msg_type,
            'content': content,
            'quote_content': quote_content,
            'link_url': link_url,
            'forward_id': forward_id,
            'image_seg': image_seg,
            'voice_seg': voice_seg,
        }

    # ------------------------------------------------------------- 对外接口

    def to_text(self):
        """语音消息转文字。优先取 QQ 自带的转写结果。"""
        if self.type != 'voice' or not self._voice_seg:
            return ''
        data = self._voice_seg.get('data') or {}
        text = _to_text(data.get('text')).strip()
        if text:
            return text
        # NapCat 的 fetch_ptt_text 需要文件参数，失败则安全降级
        try:
            got = self._bot.api.call('fetch_ptt_text',
                                     message_id=self.message_id)
            if isinstance(got, dict):
                return _to_text(got.get('text')).strip()
            if isinstance(got, str):
                return got.strip()
        except Exception as e:
            log.debug('语音转文字失败: %s', e)
        return ''

    def get_url(self):
        return self._link_url

    def get_messages(self):
        """合并转发消息，返回 [[发送者, 内容, 时间], ...]。"""
        if self.type != 'merge' or not self._forward_id:
            return None
        if self._forward_cache is not None:
            return self._forward_cache

        nodes = self._bot.api.call('get_forward_msg',
                                   message_id=self._forward_id)
        rows = []
        if isinstance(nodes, dict):
            nodes = nodes.get('messages') or []
        for node in (nodes or []):
            if not isinstance(node, dict):
                continue
            sender = node.get('sender') or {}
            name = (sender.get('card') or sender.get('nickname')
                    or str(node.get('user_id') or ''))
            ts = node.get('time') or 0
            try:
                timestr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(ts)))
            except Exception:
                timestr = ''
            for piece in (node.get('message') or []):
                if not isinstance(piece, dict):
                    continue
                if piece.get('type') == 'text':
                    text = _to_text((piece.get('data') or {}).get('text')).strip()
                elif piece.get('type') in ('image', 'flash'):
                    # bot.py 能识别图片路径，这里落盘后把路径交给它
                    text = self._bot._materialize_image(piece) or '[图片]'
                else:
                    text = '[%s]' % piece.get('type')
                if text:
                    rows.append([name, text, timestr])
        self._forward_cache = rows or None
        return self._forward_cache

    def download(self):
        """下载图片，返回本地路径；失败返回 None。"""
        if self.type != 'image' or not self._image_seg:
            return None
        try:
            path = self._bot._materialize_image(self._image_seg)
            if path:
                return path
        except Exception as e:
            log.warning('图片下载失败: %s', e)
        return None

    def capture(self):
        """截图 QQ 表情包用于识别 —— OneBot 无此能力，安全降级。

        bot.py 会对 None 做三次重试并记错误日志，这里直接返回 None
        是预期行为（等价于微信路径里截图失败）。如需识别 QQ 表情，
        应改用 mface 的图片地址走 download 路径。
        """
        if self.type != 'emotion':
            return None
        log.debug('QQ 表情包不支持截图识别，已跳过')
        return None

    def tickle(self, who=None):
        """拍一拍。

        - 群聊：拍这条消息的发出者；机器人自己发的消息则拍机器人自己
          （[tickle_self] 的语义就是「拍自己那条消息」）。
        - 私聊：拍会话对方。

        user_id 在构造消息时就已存下，无需再反查群成员。这不只是省一次
        API 调用 —— 反查靠显示名匹配，遇到重名或改名会解析成 None，
        那样 group_poke 会带着 user_id=None 发出去，必然失败。
        """
        try:
            if self.kind == 'group':
                target = self.user_id or self._bot.self_id
                resp = self._bot.api.call('group_poke',
                                          group_id=self.target_id,
                                          user_id=target)
            else:
                resp = self._bot.api.call('friend_poke',
                                          user_id=self.target_id)
            return resp is not None
        except Exception as e:
            log.warning('拍一拍失败: %s', e)
            return False

    def select_option(self, option, **kwargs):
        """对消息执行菜单操作（当前支持「撤回」）。"""
        if option not in ('撤回', 'recall'):
            log.info('select_option(%s) 暂不支持，已忽略', option)
            return False
        if not self.message_id:
            log.warning('撤回失败：缺少 message_id')
            return False
        try:
            got = self._bot.api.call('delete_msg', message_id=self.message_id)
            return got is not None or got == {}
        except Exception as e:
            log.warning('撤回失败: %s', e)
            return False

    def __str__(self):
        return '<QQMessage %s %s from %s: %s>' % (
            self.type, self.attr, self.sender, (self.content or '')[:50])


class QQBot:
    """兼容层主类：对齐 wxbot.WeChat 的对外接口。"""

    def __init__(self, *args, **kwargs):
        self.api = _OneBotAPI(QQ_ONEBOT_HTTP, QQ_ONEBOT_TOKEN)
        self.ws_url = QQ_ONEBOT_WS
        self.listen = {}            # {监听键: (QQChat, callback)}
        self.self_id = int(QQ_SELF_ID or 0)
        self.nickname = ''
        self.who = ''
        self._stop = threading.Event()
        self._ws_thread = None
        self._lists_lock = threading.Lock()
        self._friends = None
        self._groups = None
        self._groups_at = 0.0

        # bot.py:460 紧接着就要读 wx.nickname，所以这里必须拿到登录信息
        info = self._wait_for_login()
        if info:
            if not self.self_id:
                self.self_id = int(info.get('user_id') or 0)
            self.nickname = info.get('nickname') or str(self.self_id)
            self.who = self.nickname
            log.info('QQ 登录成功: %s(%s)', self.nickname, self.self_id)
        else:
            log.warning('未能获取 QQ 登录信息，机器人昵称留空，'
                        '@机器人 的群聊触发可能失效')

        # 事件流后台线程（目前 listen 为空，不会派发任何回调）
        self._ws_thread = threading.Thread(target=self._ws_loop,
                                           name='qqbot-ws', daemon=True)
        self._ws_thread.start()

    # ------------------------------------------------------------ 登录/连接

    def _wait_for_login(self, attempts=5, interval=2.0):
        """重试获取登录信息，给 NapCat 一点启动时间。"""
        for i in range(attempts):
            info = self.api.call('get_login_info')
            if isinstance(info, dict) and info.get('user_id'):
                return info
            if i < attempts - 1:
                time.sleep(interval)
        return None

    def _ws_loop(self):
        """WebSocket 事件流主循环，断线自动重连。"""
        while not self._stop.is_set():
            try:
                header = []
                if QQ_ONEBOT_TOKEN:
                    header.append('Authorization: Bearer ' + QQ_ONEBOT_TOKEN)
                app = websocket.WebSocketApp(
                    self.ws_url,
                    header=header,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_open=self._on_ws_open,
                    on_close=self._on_ws_close,
                )
                app.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.warning('WebSocket 连接异常: %s', e)
            if self._stop.is_set():
                break
            log.info('WebSocket 断开，5 秒后重连...')
            time.sleep(5)

    def _on_ws_open(self, ws):
        log.info('已连接到 NapCat 事件流: %s', self.ws_url)

    def _on_ws_close(self, ws, code, msg):
        log.warning('NapCat 事件流关闭 (code=%s, msg=%s)', code, msg)

    def _on_ws_error(self, ws, error):
        log.warning('NapCat 事件流错误: %s', error)

    def _on_ws_message(self, ws, raw):
        try:
            event = json.loads(raw)
        except Exception:
            return
        if not isinstance(event, dict):
            return
        if event.get('echo') is not None:
            return  # action 的响应，不是事件
        try:
            post_type = event.get('post_type')
            if post_type == 'message':
                self._handle_message(event)
            elif post_type == 'notice':
                self._handle_notice(event)
            # meta_event（心跳/生命周期）无需处理
        except Exception:
            log.exception('处理 NapCat 事件失败')

    def KeepRunning(self):
        """阻塞主线程，保持进程存活（对齐 wxbot 语义）。"""
        log.info('QQ 消息监听运行中...')
        while not self._stop.is_set():
            time.sleep(1)

    def Show(self):
        """对齐 wxbot 的空操作（微信路径用于显示窗口）。"""
        return True

    # ------------------------------------------------------------ 名单缓存

    def _friend_list(self, refresh=False):
        with self._lists_lock:
            if self._friends is None or refresh:
                data = self.api.call('get_friend_list')
                self._friends = data if isinstance(data, list) else []
            return self._friends

    def _group_list(self, refresh=False):
        with self._lists_lock:
            # 群列表变动少，缓存 60 秒
            if self._groups is None or refresh or (time.time() - self._groups_at) > 60:
                data = self.api.call('get_group_list')
                self._groups = data if isinstance(data, list) else []
                self._groups_at = time.time()
            return self._groups

    def _resolve_uname(self, nickname):
        """把监听目标解析成 (kind, id, display)；解析失败返回 (None, None, None)。

        同时接受 QQ 号/群号（纯数字）和好友昵称/群名，便于沿用填昵称的习惯。
        """
        s = str(nickname or '').strip()
        if not s:
            return None, None, None

        if s.isdigit():
            for g in self._group_list():
                if str(g.get('group_id')) == s:
                    return 'group', int(g['group_id']), (g.get('group_name') or s)
            for f in self._friend_list():
                if str(f.get('user_id')) == s:
                    return 'friend', int(f['user_id']), s
            # 号码没匹配上：可能是没缓存，刷新一次再试
            for g in self._group_list(refresh=True):
                if str(g.get('group_id')) == s:
                    return 'group', int(g['group_id']), (g.get('group_name') or s)
            for f in self._friend_list(refresh=True):
                if str(f.get('user_id')) == s:
                    return 'friend', int(f['user_id']), s
            return None, None, None

        for g in self._group_list(refresh=True):
            if s == (g.get('group_name') or ''):
                return 'group', int(g['group_id']), s
        for f in self._friend_list(refresh=True):
            if s in (f.get('nickname'), f.get('remark')):
                return 'friend', int(f['user_id']), s
        return None, None, None

    # ------------------------------------------------------------- 消息监听

    def AddListenChat(self, nickname=None, callback=None, **kwargs):
        """注册监听并返回 chat 对象；失败返回 None（falsy），bot 会据此退出。"""
        if not nickname:
            return None
        if nickname in self.listen:
            return self.listen[nickname][0]

        kind, ident, display = self._resolve_uname(nickname)
        if kind is None:
            log.error('找不到 QQ 好友或群: %s', nickname)
            return None

        chat = QQChat(nickname, kind, ident, self)
        self.listen[nickname] = (chat, callback)
        log.info('已监听 %s (%s: %s)', nickname, '群聊' if kind == 'group' else '私聊', ident)
        return chat

    def GetListenChatType(self, nickname):
        """直接从已注册的监听对象读取聊天类型，避免全量扫描。"""
        if not nickname:
            return None
        entry = self.listen.get(nickname)
        if not entry:
            return None
        return entry[0]._kind

    def GetAllSubWindow(self):
        """返回所有会话的 chat 对象（供 bot.py 判断群聊/私聊）。"""
        subs = []
        try:
            for f in self._friend_list():
                uid = f.get('user_id')
                if uid is None:
                    continue
                name = f.get('remark') or f.get('nickname') or str(uid)
                subs.append(QQChat(name, 'friend', int(uid), self))
            for g in self._group_list():
                gid = g.get('group_id')
                if gid is None:
                    continue
                name = g.get('group_name') or str(gid)
                subs.append(QQChat(name, 'group', int(gid), self))
        except Exception as e:
            log.warning('GetAllSubWindow 失败: %s', e)
        return subs

    # --------------------------------------------------------------- 事件派发

    def _find_listen(self, kind, ident):
        """按 (类型, ID) 找到对应的监听键。"""
        for key, (chat, _cb) in list(self.listen.items()):
            if chat._kind == kind and str(chat._id) == str(ident):
                return key
        return None

    def _handle_message(self, event):
        is_group = event.get('message_type') == 'group'
        kind = 'group' if is_group else 'friend'
        ident = event.get('group_id') if is_group else event.get('user_id')
        if ident is None:
            return

        key = self._find_listen(kind, ident)
        if key is None:
            return  # 不在监听名单内，忽略

        chat, callback = self.listen[key]
        if callback is None:
            return

        if QQ_AUTO_MARK_READ:
            try:
                self.api.call('mark_group_msg_as_read' if is_group
                              else 'mark_private_msg_as_read',
                              message_id=event.get('message_id'))
            except Exception:
                pass

        msg = QQMessage.from_event(self, event)
        log.info('收到 QQ 消息 [%s/%s] 来自 %s: %s',
                 kind, chat.who, msg.sender, (msg.content or '')[:80])
        try:
            callback(msg, chat)
        except Exception:
            log.exception('QQ 消息回调失败')

    def _handle_notice(self, event):
        notice_type = event.get('notice_type')
        if notice_type == 'notify' and event.get('sub_type') == 'poke':
            self._handle_poke(event)

    def _handle_poke(self, event):
        """拍一拍通知 → 合成一条 attr='tickle' 的消息派发。

        bot.py 会忽略内容含「我拍了拍」的（即机器人自己拍别人），
        只处理别人拍机器人的。
        """
        group_id = event.get('group_id')
        user_id = event.get('user_id')        # 发起拍一拍的人
        target_id = event.get('target_id')    # 被拍的人
        me = str(self.self_id)

        poker = str(user_id)
        target = str(target_id)

        if poker == me:
            content = '我拍了拍%s' % self._display_name(group_id, target)
        elif target == me:
            content = '%s拍了拍我' % self._display_name(group_id, poker)
        else:
            return  # 与机器人无关的拍一拍，忽略

        if group_id is not None:
            kind, ident = 'group', group_id
        else:
            # 私聊：会话对象是「双方中不是机器人的那一个」。
            # 机器人拍好友时 poker == me，对方是 target_id；
            # 好友拍机器人时对方才是 user_id。这里取错会查不到监听项，
            # 事件被无声丢弃（机器人自己拍好友的派发就是这么丢的）。
            kind = 'friend'
            ident = target_id if poker == me else user_id

        key = self._find_listen(kind, ident)
        if key is None:
            return
        chat, callback = self.listen[key]
        if callback is None:
            return

        msg = QQMessage(self, kind=kind, target_id=ident, sender=poker,
                        user_id=user_id, content=content, msg_type='text',
                        attr='tickle')
        log.info('收到拍一拍 [%s] %s', chat.who, content)
        try:
            callback(msg, chat)
        except Exception:
            log.exception('拍一拍回调失败')

    def _display_name(self, group_id, user_id):
        """取群成员名片/昵称，取不到就退回 QQ 号。"""
        if group_id is not None:
            info = self.api.call('get_group_member_info',
                                 group_id=group_id, user_id=user_id)
            if isinstance(info, dict):
                return info.get('card') or info.get('nickname') or str(user_id)
        else:
            for f in self._friend_list():
                if str(f.get('user_id')) == str(user_id):
                    return f.get('remark') or f.get('nickname') or str(user_id)
        return str(user_id)

    # ----------------------------------------------------------------- 发送

    def _target_for(self, who):
        """把 who（监听键）解析成 (kind, ident)。"""
        entry = self.listen.get(who)
        if not entry:
            # 未注册但可能是号码，兜底解析一次
            kind, ident, _d = self._resolve_uname(who)
            if kind is None:
                log.warning('发送失败：未找到目标 %s', who)
                return None
            return kind, ident
        chat = entry[0]
        return chat._kind, chat._id

    def _send_segments(self, who, segments):
        """发送消息段数组，成功返回 message_id，失败返回 None。"""
        target = self._target_for(who)
        if target is None:
            return None
        kind, ident = target
        if kind == 'group':
            data = self.api.call('send_group_msg', group_id=ident,
                                 message=segments)
        else:
            data = self.api.call('send_private_msg', user_id=ident,
                                 message=segments)
        if isinstance(data, dict):
            return data.get('message_id')
        return None

    def _emit_self_message(self, who, message_id, content):
        """把机器人自己发的消息回灌给回调，填充 bot.py 的 bot_last_sent_msg。

        微信路径靠数据库自然回读自己发的消息；OneBot 默认不回推，
        所以这里本地合成一条 attr='self' 的消息，否则 [tickle_self]
        和 [recall] 两个功能会静默失效。
        message_listener 对 self 消息是「保存后 return」，重复灌入是幂等的。
        """
        entry = self.listen.get(who)
        if not entry:
            return
        chat, callback = entry
        if callback is None:
            return
        msg = QQMessage(self, message_id=message_id, kind=chat._kind,
                        target_id=chat._id, user_id=self.self_id,
                        sender=self.nickname or '我',
                        content=content, msg_type='text', attr='self')
        try:
            callback(msg, chat)
        except Exception:
            log.debug('回灌 self 消息失败', exc_info=True)

    def SendMsg(self, msg, who=None, **kwargs):
        message_id = self._send_segments(
            who, [{'type': 'text', 'data': {'text': str(msg)}}])
        if message_id is None:
            return False
        self._emit_self_message(who, message_id, str(msg))
        return True

    def SendFiles(self, filepath, who=None, **kwargs):
        if not filepath or not os.path.exists(filepath):
            log.warning('发送文件失败：文件不存在 %s', filepath)
            return False

        ext = os.path.splitext(str(filepath))[1].lower()
        if ext in _IMG_EXTS:
            # 图片走 base64，避免依赖 NapCat 的本地文件读取配置
            try:
                with open(filepath, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
            except Exception as e:
                log.warning('读取图片失败 %s: %s', filepath, e)
                return False
            message_id = self._send_segments(
                who, [{'type': 'image',
                       'data': {'file': 'base64://' + b64}}])
            if message_id is None:
                return False
            self._emit_self_message(who, message_id, '[图片]')
            return True

        # 其它文件走上传接口（NapCat 与本程序同机，绝对路径可用）
        target = self._target_for(who)
        if target is None:
            return False
        kind, ident = target
        abspath = os.path.abspath(str(filepath))
        name = os.path.basename(abspath)
        if kind == 'group':
            got = self.api.call('upload_group_file', group_id=ident,
                                file=abspath, name=name)
        else:
            got = self.api.call('upload_private_file', user_id=ident,
                                file=abspath, name=name)
        if got is None:
            return False
        self._emit_self_message(who, None, '[文件] %s' % name)
        return True

    # ------------------------------------------------------------ 媒体下载

    def _materialize_image(self, seg):
        """把图片段落地成本地文件，返回路径。"""
        data = (seg.get('data') or {}) if isinstance(seg, dict) else {}
        url = data.get('url')
        path = data.get('file')

        raw = None
        if url:
            try:
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
                raw = resp.content
            except Exception as e:
                log.debug('按 url 下载图片失败: %s', e)
        if raw is None and path and not str(path).startswith(('http', 'base64://')):
            # NapCat 直接给了本地路径
            local = str(path).replace('file:///', '').replace('file://', '')
            if os.path.exists(local):
                return local
        if raw is None and path:
            # 交给 NapCat 转换（可能返回 base64 或本地路径）
            got = self.api.call('get_image', file=path)
            if isinstance(got, dict):
                f = got.get('file')
                if isinstance(f, str) and f.startswith('base64://'):
                    try:
                        raw = base64.b64decode(f[len('base64://'):])
                    except Exception:
                        raw = None
                elif isinstance(f, str) and os.path.exists(f):
                    return f
        if raw is None:
            return None

        ext = '.jpg'
        if raw[:4] == b'\x89PNG':
            ext = '.png'
        elif raw[:3] == b'GIF':
            ext = '.gif'
        name = 'qq_%s%s' % (int(time.time() * 1000), ext)
        out = os.path.join(_media_dir(), name)
        with open(out, 'wb') as f:
            f.write(raw)
        return out

    def _fetch_message_summary(self, message_id):
        """取被引用消息的文本摘要，用于 quote 类型。"""
        got = self.api.call('get_msg', message_id=message_id)
        if not isinstance(got, dict):
            return None
        parts = []
        for seg in (got.get('message') or []):
            if isinstance(seg, dict) and seg.get('type') == 'text':
                parts.append(_to_text((seg.get('data') or {}).get('text')))
        text = ''.join(parts).strip()
        if text:
            return text
        return _to_text(got.get('raw_message')).strip() or None

    # ------------------------------------------------------------ 通话/退出

    def VoiceCall(self, user_id=None, **kwargs):
        """OneBot 无语音通话接口，降级返回 False。"""
        log.info('QQ 路径不支持语音通话，已跳过（用户 %s）', user_id)
        return False

    def Stop(self):
        self._stop.set()


# 与 wxbot 保持同名，使 "from qqbot import WeChat" 写法一致
WeChat = QQBot
