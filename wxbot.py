# -*- coding: utf-8 -*-
"""微信收发兼容层。

数据库轮询收消息，坐标/OCR 发消息，适配微信 4.x。
自己发的消息靠 status 和表情 XML 认出来，避免机器人回复自己。
卡片、表情、合并转发收成一行可读文字，不把整段 XML 交给模型。
"""

import logging
import os
import re
import sqlite3
import threading
import time

# wechatauto 默认 natural 档会把连发拖住。这里用 fast 档；
# 用户自己设的同名环境变量优先。
os.environ.setdefault("WECHATAUTO_RHYTHM", "fast")

log = logging.getLogger("wxbot")
_BACKEND_ERROR = None

try:
    from wechatauto.guia import WeChatGUI as _WeChatGUI
    from wechatauto.db import WeChatDB
    from wechatauto.wx import WeChat as _BaseWeChat
    from wechatauto.wx import Chat as _BaseChat
    from wechatauto import MediaDownloader
    from wechatauto.param import WxResponse
    from wechatauto import wxlog
    from PIL import ImageStat
except ImportError as exc:
    _BACKEND_ERROR = exc
    ImageStat = None
    _WeChatGUI = None
    WeChatDB = None
    _BaseWeChat = object
    _BaseChat = object
    MediaDownloader = None
    WxResponse = None
    wxlog = log


def _desktop_available_theme_compatible(self):
    """Treat both light and dark WeChat themes as a visible desktop.

    wechatauto 1.2.0 only checks for a minimum amount of near-white pixels,
    which incorrectly rejects a healthy dark-mode WeChat window.  A real
    captured window has meaningful channel variation; locked/disconnected
    captures are effectively blank.
    """
    if not self.is_alive():
        return False
    try:
        image = self._grab_screen(self.render_rect).convert("RGB")
        stats = ImageStat.Stat(image.resize((64, 64)))
    except Exception:
        return False
    return max(stats.stddev) >= 4.0 and any(high - low >= 24 for low, high in stats.extrema)


if _WeChatGUI is not None and ImageStat is not None:
    _WeChatGUI.desktop_available = _desktop_available_theme_compatible
    # 发消息时只把微信提到前台几秒，不最小化用户正在用的其它窗口。
    _WeChatGUI._minimize_blockers = lambda self: 0

_URL_RE = re.compile(r"https?://[^\s\"'<>\[\]]+")

# 微信自己的资源域名：卡片 XML 里到处是这种 stodownload / 头像 / 客服链接，
# 它们是二进制资源的下载地址，**不是**网页链接。以前正文里只要出现这种串就被
# 当成「链接」送去抓取，结果必然是「非 HTML / 提取不到文本」。实测 5307 行里
# 有 478 次命中的是 vweixinf.tc.qq.com、184 次是 wxapp.tc.qq.com。
_ASSET_HOSTS = (
    "vweixinf.tc.qq.com", "wxapp.tc.qq.com", "wxwinstore.getweapp.com",
    "wctcn.bd.qq.com", "store.icf.mmweb.qq.com", "c.weixin.com",
    "wx.qlogo.cn", "mmbiz.qpic.cn", "mmbiz.qlogo.cn",
    "support.weixin.qq.com", "help.wechat.com", "open.weixin.qq.com",
    "wx.tenpay.com", "url.tenpay.com", "tenpay.com", "wxapp.tenpay.com",
    "dldir1.qq.com", "dldir1v6.qq.com",
)


def is_wechat_asset_url(url):
    """True = 这是微信客户端的资源地址，不该当网页链接抓。"""
    if not url:
        return False
    low = str(url).strip().lower()
    if not low.startswith(("http://", "https://")):
        return False
    host = re.sub(r"^https?://", "", low).split("/")[0]
    if any(host == h or host.endswith("." + h.lstrip(".")) for h in _ASSET_HOSTS if h):
        return True
    # 剩下的按路径特征兜一层：这些都是下载端点或错误占位页
    return any(p in low for p in ("/stodownload", "encfilekey=",
                                  "checkresupdate", "/mp/waerrpage"))


def _first_http_url(text):
    """从 XML 里取第一个**像网页**的 http(s) 链接，资源地址一律不要。"""
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0)
        if not is_wechat_asset_url(u):
            return u
    return ""


def _tag_val(text, *names):
    """取 <name>…</name> 或 <name xxx="…" /> 里的文本；CDATA 剥掉。取不到返回 ''。"""
    for name in names:
        m = re.search(r"<%s>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</%s>" % (name, name),
                      text or "", re.S)
        if m:
            v = _strip_tags(m.group(1))
            if v:
                return v
        # 属性形式：<location label="xx" /> / <name title="xx">
        for attr in ("label", "title", "poiname", "desc", "showmsg", "content", "name"):
            m = re.search(r"<%s\b[^>]*\b%s=\"([^\"]+)\"" % (name, attr), text or "")
            if m:
                v = _strip_tags(m.group(1))
                if v:
                    return v
        m = re.search(r"<%s\b[^/>]*>(.*?)" % name, text or "", re.S)
        if m:
            v = _strip_tags(re.sub(r"<[^>]+>", "", m.group(1)))
            if v:
                return v
    return ""


def _looks_like_xml(text):
    t = (text or "").lstrip()
    return t.startswith("<?xml") or (t.startswith("<") and (">" in t[:200] or "/>" in t[:200]))


def _split_sender_prefix(text):
    """群消息正文常是「发送者:\\n真身」。前缀不一定是 wxid_ 或纯数字，也可能是别名。

    返回 (前缀或None, 剩下的部分)。只有当剩下的部分明显是 XML 卡面时才剥，
    免得把「备注: 我今天很忙」这种正常文本也剁一截。
    """
    if not text:
        return None, text
    m = re.match(r"^[^\n:]{1,40}:\n", text)
    if m and _looks_like_xml(text[m.end():].lstrip()):
        return m.group(0).rstrip(":\n"), text[m.end():]
    return None, text


_MERGE_ITEM_RE = re.compile(r"<item\b([^>]*?)(?:/>|>(.*?)</item>)", re.S)
_MERGE_ATTR_RE = re.compile(r'([\w:]+)\s*=\s*"([^"]*)"')
_MERGE_SENDER_KEYS = ("sname", "sendernickname", "sendername", "sender")
_MERGE_TEXT_KEYS = ("msg", "msgdata", "content", "title", "digest")
_MERGE_TIME_KEYS = ("asmantime", "time", "timestamp", "createtime")
_MERGE_ENTITIES = (("&quot;", '"'), ("&apos;", "'"), ("&lt;", "<"),
                   ("&gt;", ">"), ("&#x0a;", "\n"), ("&#10;", "\n"), ("&amp;", "&"))


def _parse_merge_records(blob):
    """合并转发（``<record>`` 里的 ``<item>``）拆成 ``[[发送者, 内容, 时间], ...]``。

    bot 侧按三元素列表消费（``bot.py`` 的 ``msgtype == 'merge'`` 分支）。各版本属性名
    不一致，所以每个字段给一串候选键；整条解析不出来返回 ``[]``。以前 ``_merge``
    从没被赋过值，``get_messages()`` 永远返回 None —— 合并转发的内容对模型就是空的。
    """
    out = []
    for m in _MERGE_ITEM_RE.finditer(blob or ""):
        attrs = {k.lower(): v for k, v in _MERGE_ATTR_RE.findall(m.group(1) or "")}
        inner = m.group(2) or ""
        sender = next((attrs[k] for k in _MERGE_SENDER_KEYS if attrs.get(k)), "")
        text = next((attrs[k] for k in _MERGE_TEXT_KEYS if attrs.get(k)), "")
        text = text or _tag_val(inner, "title", "msg", "content", "desc")
        for a, b in _MERGE_ENTITIES:
            text = text.replace(a, b)
            sender = sender.replace(a, b)
        ts = next((attrs[k] for k in _MERGE_TIME_KEYS if attrs.get(k)), "")
        stamp = time.strftime("%m-%d %H:%M", time.localtime(int(ts))) if ts.isdigit() else ""
        text = _strip_tags(text or "").strip()
        if text:
            out.append([sender or "未知", text, stamp])
    return out


def _fold_xml_content(text, type_cn):
    """把消息正文里的整坨 XML 折成一行人类可读的话。

    兼容层的 content 会直接喂给模型、并被 bot 的链接正则扫一遍，所以这里
    返回 XML 原文等于同时污染提示词和制造「莫名识别到链接」。非 XML 原样返回。
    """
    if not text or "<" not in text:
        return text
    # 「发送者:\n<?xml…」这种形状：前缀不是 wxid_/纯数字时 _clean_content 那步剥不掉，
    # 于是 XML 整坨留在正文里（实测合并转发卡片就是这么漏网的）。
    _p, rest = _split_sender_prefix(text)
    text = rest
    if not _looks_like_xml(text):
        head = text[:300]
        if not (head.lstrip().startswith("<?xml") or "<appmsg" in head or "<emoji" in head
                or "<msg" in head):
            return text
    if type_cn == "动画表情":
        return "[动画表情]"
    if type_cn == "图片":
        return "[图片]"
    if type_cn == "视频":
        return "[视频]"
    if type_cn == "语音":
        return "[语音]"
    if type_cn == "位置":
        place = _tag_val(text, "location", "label", "poiname", "title")
        return ("[位置] " + place).strip()
    if type_cn == "红包":
        return "[红包] " + (_tag_val(text, "title", "showmsg") or "恭喜发财")
    if type_cn == "音视频通话":
        return "[语音/视频通话] " + _tag_val(text, "content", "title")
    if type_cn == "系统消息":
        plain = _strip_tags(text)
        return plain or "[系统消息]"
    # 文件/链接/卡片：按卡面类型分别折
    if "<refermsg" in text:
        return "[引用消息] " + (_tag_val(text, "title", "content") or "")
    if "<record" in text:
        return "[合并转发的聊天记录]"
    if "<findernamecard" in text or "<finder" in text:
        return "[视频号视频] " + _tag_val(text, "title", "desc")
    if "<wefilename" in text or "<appmsg" in text and "<cdnattachurl" in text:
        return "[文件] " + _tag_val(text, "wefilename", "title")
    title = _tag_val(text, "title")
    if title:
        # 拍一拍、公众号文章分享、小程序卡片等：只留标题，链接另由 _classify 判
        return "[卡片] " + title
    return "[卡片消息]"


# wechatauto 4.x 的消息正文列可能是 zstd 帧（首字节 28 B5 2F FD），
# get_messages 的摘要列已经解过，但 get_message_row 的原始列没有 —— 不解就
# 永远抽不到 URL，「链接/引用/合并转发」这套判据等于死代码（实测 336/336 是帧）。
def _decode_cell(value):
    if isinstance(value, (bytes, bytearray)):
        head = bytes(value[:4])
        if head == b"\x28\xb5\x2f\xfd":
            try:
                from wechatauto.db import _get_zstd_module, _zstd_decompress
                zstd = _get_zstd_module()
                if zstd is not None:
                    out = _zstd_decompress(zstd, bytes(value))
                    if out:
                        return out
            except Exception as e:  # 换版本/缺库时退回原值，别把整条消息判死
                log.debug("zstd 解压失败: %s" % e)
        return _to_text(value)
    return value


# 微信数据库中文类型 -> bot 使用的英文类型
_TYPE_MAP = {
    "文本": "text",
    "图片": "image",
    "语音": "voice",
    "视频": "video",
    "动画表情": "emotion",
    "表情": "emotion",
    "位置": "location",
    "文件/链接/卡片": "file",
    "系统消息": "system",
    "引用消息": "quote",
    "撤回消息": "recall",
}


def _to_text(x):
    if x is None:
        return ""
    if isinstance(x, bytes):
        try:
            return x.decode("utf-8", "ignore")
        except Exception:
            return ""
    return str(x)


def _strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for a, b in (
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&apos;", "'"),
        ("&#10;", "\n"),
        ("&nbsp;", " "),
    ):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_XML_SELF_RE = re.compile(r'fromusername\s*=\s*["\']?\s*([A-Za-z0-9_\-@]+)')
_MSG_TABLE_RE = re.compile(r'^Msg_[0-9a-f]{32}$')


def status_votes(db, username, since=0, until=0, cap=0):
    """``{sender_id: [条数, 其中 status==2 的条数]}``。

    ``status`` 不在 ``get_messages()`` 的返回里，只能自己开分片读；读不到就回空表，
    调用方退到「只看 XML」这一条证据上。

    窗口参数是给热路径留的：历史格式化只查被格式化的那批消息的时间跨度
    （``since``/``until``），实时判定只看这个会话最近的 ``cap`` 条 ——
    一个几万条的群全表扫一遍是不能放在收消息的循环里的。
    """
    out = {}
    try:
        conns = db._msg_conns(username)
    except Exception as e:
        wxlog.warning("读 status 失败（只用 XML 证据判定「我」）: %s" % e)
        return {}
    for conn, table in conns or []:
        if not _MSG_TABLE_RE.match(str(table)):          # 表名进 SQL 前先卡死格式
            continue
        sql = 'SELECT real_sender_id, status FROM "%s"' % table
        args = []
        if since and until:
            sql += " WHERE create_time BETWEEN ? AND ?"
            args += [int(since), int(until)]
        if cap:
            sql += " ORDER BY sort_seq DESC LIMIT ?"
            args.append(int(cap))
        try:
            for sid, st in conn.execute(sql, args):
                v = out.setdefault(str(sid), [0, 0])
                v[0] += 1
                if st == 2:
                    v[1] += 1
        except Exception as e:
            wxlog.warning("分片 %s 读 status 失败: %s" % (table, e))
    return out


def classify_senders(rows, own_wxid, votes):
    """这个会话里哪些 ``sender_id`` 是「我」，返回 ``(self_ids, 证据列表)``。

    ``real_sender_id`` 是**分片内**的短编号，同一个人换个分片就换个号：本机实测
    2025-07~2026-02 自己是 4、2026-06 之后是 2，所以 ``== 2`` 会把整段旧历史里的
    我算成对方（风格档案于是描述的是对方的口吻）。只认两条正向证据：
    ① ``status == 2``（微信给自己发的消息打的标，跨分片稳）；
    ② 表情/图片 XML 里的 ``fromusername`` == 本机 wxid。
    整场都没有正向证据才退回 ``== 2``；只要判得出「我」，剩下的 id 一律算对方
    —— 群里十几个成员编号，不该有一个靠 ``== 2`` 混进来。
    """
    win, xml = {}, {}
    for r in rows or []:
        sid = str(r.get("sender_id"))
        win[sid] = win.get(sid, 0) + 1
        m = _XML_SELF_RE.search(_to_text(r.get("content")))
        if m and own_wxid and m.group(1) == own_wxid:
            xml[sid] = xml.get(sid, 0) + 1
    self_ids, ev = set(), []

    def positive(sid):
        n, st2 = votes.get(sid, [0, 0])
        return st2 >= max(1, int(0.3 * n)) or bool(xml.get(sid))

    decided = any(positive(s) for s in set(list(win) + list(votes)))
    for sid in sorted(set(list(win) + list(votes))):
        n, st2 = votes.get(sid, [0, 0])
        x = xml.get(sid, 0)
        if st2 >= max(1, int(0.3 * n)):
            is_self, how = True, "status=2 占 %d/%d" % (st2, n)
        elif x:
            is_self, how = True, "表情 XML 里 fromusername 是本机号，%d 条" % x
        elif not decided and sid == "2":
            is_self, how = True, "整场都没有正向证据，退回 sender_id==2"
        else:
            is_self, how = False, "无正向证据（status=2 只有 %d/%d）" % (st2, n)
        if is_self:
            self_ids.add(sid)
        ev.append((sid, win.get(sid, 0), is_self, how))
    return self_ids, ev


def resolve_self_ids(db, username, rows=None, cap=0):
    """历史/实时两条路共用的入口：拿本机 wxid + status 证据，判出「我」的编号集合。"""
    try:
        own = (getattr(db, "wxid", "") or "").strip()
    except Exception:
        own = ""
    since = until = 0
    if rows:
        ts = [_as_int(r.get("create_time")) for r in rows if _as_int(r.get("create_time"))]
        if ts:
            since, until = min(ts), max(ts)
    try:
        votes = status_votes(db, username, since=since, until=until, cap=cap)
    except Exception as e:
        wxlog.warning("判定「我」的 sender_id 失败（退回 sender_id==2）: %s" % e)
        votes = {}
    ids, _ev = classify_senders(rows or [], own, votes)
    return ids


class WxMessage:
    """bot 兼容消息对象（对齐 wxautox4_wechatbot 的消息接口）"""

    def __init__(self, row, chat, db, media, self_wxid, self_ids=None):
        self._row = row
        self._chat = chat
        self._db = db
        self._media = media
        self._self_wxid = self_wxid or ""
        self.local_id = row.get("local_id")
        self.create_time = row.get("create_time")
        self.sort_seq = row.get("sort_seq")

        type_cn = row.get("type") or ""
        self._type_cn = type_cn
        self.type = _TYPE_MAP.get(type_cn, "text")

        sender_id = row.get("sender_id")
        self._is_group = bool(
            self._chat
            and str(getattr(self._chat, "_wxid", "")).endswith("@chatroom")
        )
        # self_ids 由调用方按 status/XML 证据判好传进来（一个会话算一次，见
        # WeChat._make_listen_cb）。real_sender_id 是分片内的短编号，写死 ==2
        # 在换过分片编号的机器上会把"我"当成"对方"，于是自己回复自己。
        is_self = str(sender_id) in (self_ids or {"2"})
        self.attr = "self" if is_self else "friend"

        content = _to_text(row.get("content"))
        prefix = self._extract_prefix_sender(content)
        self.sender_wxid = self._resolve_sender_wxid(row, prefix)
        self.sender = self._resolve_sender(sender_id, prefix)
        self.content = self._clean_content(content, prefix, type_cn)

        self.quote_content = None
        self._link_url = None
        self._merge = None
        self._file_path = None
        self._file_name = None
        self._cached_full = None
        self._classify()

    # ---------------------------------------------------------------- 内部

    def _full_row(self):
        if self._cached_full is None:
            try:
                if (
                    self._chat
                    and getattr(self._chat, "_wxid", None)
                    and self.local_id is not None
                ):
                    full = (
                        self._db.get_message_row(self._chat._wxid, self.local_id) or {}
                    )
                    # 原始列可能是 zstd 帧，不解的话判据永远拿到空串
                    self._cached_full = {
                        k: _decode_cell(v) for k, v in full.items()
                    }
                else:
                    self._cached_full = {}
            except Exception:
                self._cached_full = {}
        return self._cached_full

    @staticmethod
    def _extract_prefix_sender(content):
        m = re.match(r"^(wxid_[^\s:\n]+|gh_[^\s:\n]+|\d{6,}):\n", content)
        return m.group(1) if m else None

    def _resolve_sender_wxid(self, row, prefix):
        """真实发送者 wxid（wechatauto 1.2.4.1 起由 db 层把 real_sender_id 换好）。

        纯数字要丢掉：1.2.4 之前那套兜底会把数字 rowid 冒充成用户名。
        拿不到时退正文前缀（文本消息里才有），再拿不到就是空字符串。
        """
        if self.attr == "self":
            return self._self_wxid
        value = str(row.get("sender_username") or "").strip()
        if value and not value.isdigit():
            return value
        return prefix or ""

    def _nickname_of(self, wxid):
        """wxid -> 备注/昵称（进程内缓存，逐条查 contact.db 太贵）。"""
        if not wxid:
            return ""
        try:
            return self._db.nickname_map().get(wxid, "") or ""
        except Exception:
            return ""

    def _resolve_sender(self, sender_id, prefix):
        # 微信4.x 数据库里 real_sender_id 只是短数字ID，不能当 wxid 用。
        if self.attr == "self":
            try:
                return self._db.get_self_info().get("nick_name") or "我"
            except Exception:
                return "我"
        if self._is_group:
            # 群里先用真 wxid 换名字：图片/文件/语音这些类型正文里没有
            # "wxid_xxx:\n" 前缀，旧实现只能回落到一个无意义的数字。
            name = self._nickname_of(self.sender_wxid) or self._nickname_of(prefix)
            return name or ("群成员%s" % sender_id if str(sender_id).isdigit() else str(sender_id))
        # 私聊：对方就是聊天窗口本身
        try:
            return self._chat.who or "对方"
        except Exception:
            return "对方"

    @staticmethod
    def _clean_content(content, prefix, type_cn=""):
        if prefix:
            content = re.sub(r"^" + re.escape(prefix) + r":\n", "", content)
        content = content.replace("[文本]", "").strip()
        return _fold_xml_content(content, type_cn)

    def _classify(self):
        if self._type_cn == "文件/链接/卡片":
            full = self._full_row()
            raw = _to_text(full.get("content"))
            packed = _to_text(full.get("packed_info"))
            summary = _to_text(self._row.get("content"))
            # 摘要列(get_messages)通常是解开的 XML，原始列解压后字段更全；
            # 两边都看一眼，取信息多的那份。
            blob = "\n".join(t for t in (raw, packed, summary) if t)
            title = _tag_val(blob, "title")

            if "<refermsg" in blob:
                self.type = "quote"
                self.quote_content = (
                    _tag_val(blob, "content") or title or self.content or "[引用消息]"
                )
                return
            if "<record" in blob:
                self.type = "merge"
                self._merge = _parse_merge_records(blob)
                return

            # 链接卡片：只认卡面 <url> 里的网页地址。以前是「blob 里有 http 就算链接」，
            # 于是视频号/表情卡片的 stodownload 资源地址被当成网页链接送去抓取。
            url = _first_http_url(_tag_val(blob, "url")) or _first_http_url(_tag_val(blob, "linkurl"))
            if not url and "<findernamecard" not in blob and "<wefilename" not in blob:
                # 公众号文章一类会把链接直接写在正文里，过滤掉资源域名后仍可接受
                url = _first_http_url(_strip_tags(blob))
            if url:
                self.type = "link"
                self._link_url = url
                return

            if "<wefilename" in blob or "<md5" in blob and "<appmsg" not in blob:
                self.type = "file"
                self._file_name = _tag_val(blob, "wefilename", "title")
                return
            self.type = "file"
        elif self._type_cn == "系统消息":
            if "拍了拍" in self.content:
                self.attr = "tickle"

    # ------------------------------------------------------------- 对外接口

    def to_text(self):
        if self.type == "voice":
            return ""
        return self.content

    def get_url(self):
        return self._link_url

    def get_messages(self):
        return self._merge or []

    def __str__(self):
        return "<WxMessage %s from %s: %s>" % (self.type, self.sender, self.content[:50])


class WeChat(_BaseWeChat):
    """兼容层主类：在 wechatauto.wx.WeChat 之上补齐 bot 需要的接口。"""

    def __init__(self, *args, **kwargs):
        account = kwargs.pop("account", None)
        if not account:
            try:
                from config import WECHAT_ACCOUNT
                account = WECHAT_ACCOUNT
            except (ImportError, AttributeError):
                account = None

        if not account:
            super().__init__(*args, **kwargs)
        else:
            nickname = kwargs.pop("nickname", None)
            start_listener = kwargs.pop("start_listener", False)
            debug = kwargs.pop("debug", False)
            self._gui = _WeChatGUI()
            self._db = WeChatDB(account=account)
            info = self._db.get_self_info()
            self.nickname = nickname or info.get("nick_name") or info.get("username") or ""
            self.who = self.nickname
            self._wxid = info.get("username") or ""
            self.listen = {}
            self._listener = None
            self._listen_wrappers = {}
            self._listener_is_listening = False
            self._listener_stop_event = threading.Event()
            self._current_chat = None
            self._listen_all_active = False
            self._listen_all_callback = None
            self._moment_api = None
            self._moment = None
            if start_listener:
                self._listener_start()
            if debug:
                wxlog.set_debug(True)
                wxlog.debug("Debug mode is on")
        self._media = MediaDownloader(self._db)

    # ------------------------------------------------------------- 消息监听

    def _make_listen_cb(self, chat, callback):
        self_wxid = ""
        try:
            self_wxid = self._db.get_self_info()["username"]
        except Exception:
            pass
        # 一个会话只判一次（订阅时），不放在每条消息的回调里。cap=400：只看这个
        # 会话最近的几百条，几万条的群不做全表扫。
        wxid = str(getattr(chat, "_wxid", "") or "")
        self_ids = resolve_self_ids(self._db, wxid, cap=400) if wxid else set()
        if wxid:
            wxlog.info("会话 %s 的「我」= sender_id %s"
                       % (wxid, "、".join(sorted(self_ids)) or "（未判出，按 2 兜底）"))

        def _wrapper(row, listener):
            try:
                msg = WxMessage(row, chat, self._db, self._media, self_wxid, self_ids)
                callback(msg, chat)
            except Exception:
                import traceback

                wxlog.debug("wxbot 监听回调错误:\n%s" % traceback.format_exc())

        return _wrapper

    def AddListenChat(self, nickname=None, callback=None, **kwargs):
        """校验昵称确实存在后再监听；找不到返回失败（falsy），供 bot 退出。

        相比基类更稳健：
          * 微信写库瞬间会抛 sqlite "database disk image is malformed"，这里做重试；
          * 预先设置水位后再注册回调，避免水位初始化失败导致旧消息洪泛。
        """
        if not nickname:
            return WxResponse.failure("昵称为空")
        if nickname in self.listen:
            return WxResponse.failure("该聊天已监听")
        uname = self._resolve_uname(nickname)
        if uname is None:
            return WxResponse.failure("找不到聊天窗口: %s" % nickname)
        if not self._listener_is_listening:
            self._listener_start()  # 首次调用，listen 为空，仅启动监听线程
        chat = _BaseChat(nickname, self._gui, self._db)
        if uname != chat._wxid:
            chat._wxid = uname
        self.listen[nickname] = (chat, callback)
        self._listen_wrappers[nickname] = self._make_listen_cb(chat, callback)
        listener = self._listener
        if listener is None:
            return WxResponse.failure("监听器未启动: %s" % nickname)
        # 先设水位（带重试），再注册回调
        for attempt in range(5):
            try:
                msgs = self._db.get_messages(uname, limit=1)
                listener._watermark[uname] = msgs[0]["sort_seq"] if msgs else 0
                listener.add_listener(uname, self._listen_wrappers[nickname])
                return chat
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
                log.warning("数据库暂不可用(第%d次, %s): %s", attempt + 1, nickname, e)
                time.sleep(1.5)
        return WxResponse.failure("监听失败: %s" % nickname)

    def _resolve_uname(self, nickname):
        """昵称 -> username；数据库瞬时不可用时重试。找不到返回 None。"""
        if nickname in ("filehelper", "文件传输助手"):
            return "filehelper"
        for _ in range(5):
            try:
                for hit in self._db.search_contact(nickname):
                    if nickname in (hit.get("nick_name"), hit.get("remark")):
                        return hit["username"]
                return None
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
                log.warning("数据库暂不可用(解析昵称): %s", e)
                time.sleep(1.5)
        return None

    # --------------------------------------------------------------- 发送

    def _display_name(self, who):
        """who 可能是昵称，也可能是 username(wxid/@chatroom)，统一转成界面显示名。"""
        if not who:
            return who
        if who in ("filehelper", "文件传输助手"):
            return "文件传输助手"
        try:
            nick = self._db.get_nickname(who)
            if nick and nick != who:
                return nick
        except Exception:
            pass
        return who

    def SendMsg(self, msg, who=None, **kwargs):
        user32 = __import__('ctypes').windll.user32
        previous = user32.GetForegroundWindow()
        try:
            return super().SendMsg(msg, who=self._display_name(who), **kwargs)
        finally:
            try:
                self._gui.restore_zorder()
                if previous and previous != self._gui.main_hwnd and user32.IsWindow(previous):
                    user32.SetForegroundWindow(previous)
            except Exception:
                pass

    def GetListenChatType(self, nickname):
        """直接从已注册的监听对象读取聊天类型，避免全量扫描会话。

        返回 "group"/"friend"；未监听该昵称时返回 None。
        """
        if not nickname:
            return None
        entry = self.listen.get(nickname)
        if not entry:
            return None
        chat = entry[0] if isinstance(entry, tuple) else entry
        try:
            info = chat.ChatInfo()
        except Exception as e:
            log.warning("GetListenChatType(%s) 失败: %s", nickname, e)
            return None
        return info.get("chat_type")

