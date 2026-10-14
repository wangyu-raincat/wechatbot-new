# -*- coding: utf-8 -*-
"""核心回复逻辑的纯函数测试，不启动微信、不调用模型。

    python test_core.py
"""
import sys

sys.path.insert(0, ".")
import bot

FAILS = []


def ck(name, cond, got=""):
    print("%-4s %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "  <- %r" % (got,)))
    if not cond:
        FAILS.append(name)


class Msg(object):
    def __init__(self, **kwargs):
        self.attr = kwargs.get("attr", "friend")
        self.type = kwargs.get("type", "text")
        self.content = kwargs.get("content", "")
        self.sender = kwargs.get("sender", "")
        self._messages = kwargs.get("messages", [])
        self._url = kwargs.get("url", "")

    def get_messages(self):
        return self._messages

    def get_url(self):
        return self._url


ck("空名单", bot.parse_listen([]) == [])
ck("默认提示词", bot.parse_listen([["甲", ""]]) == [("甲", "角色1")])
ck("去掉 md 后缀", bot.parse_listen([["甲", "角色1.md"]]) == [("甲", "角色1")])
try:
    bot.parse_listen(["坏的"])
    ck("非法名单要报错", False)
except ValueError:
    ck("非法名单要报错", True)

ck("忽略自己", bot.incoming_text(Msg(attr="self", content="我刚说的")) is None)
ck("忽略自己拍一拍", bot.incoming_text(Msg(attr="tickle", content="我拍了拍对方")) is None)
ck("对方拍一拍", bot.incoming_text(Msg(attr="tickle", content="对方拍了拍我")) == "[拍一拍] 对方拍了拍我")
ck("普通文本", bot.incoming_text(Msg(content="在吗")) == "在吗")
ck("系统通知丢掉", bot.incoming_text(Msg(type="system", content="你撤回了一条消息")) is None)
ck(
    "合并转发",
    bot.incoming_text(Msg(type="merge", messages=[["甲", "今晚"], ["乙", "好"]])) == "[合并转发]\n甲: 今晚\n乙: 好",
)
ck("反斜线拆条", bot.split_reply("在的\\刚看到") == ["在的", "刚看到"])
ck("思考标签丢掉", bot.split_reply("<think>内部</think>好呀") == ["好呀"])
ck("拍一拍标记不发出去", "[tickle]" not in "".join(bot.split_reply("喂\\[tickle]\\起来")))
ck("上下文只留最近几轮", len(bot.trim_history([{"role": "user", "content": str(i)} for i in range(10)], max_groups=2)) == 4)

print("\n%s" % ("失败 %d 项: %s" % (len(FAILS), FAILS) if FAILS else "全部通过"))
sys.exit(1 if FAILS else 0)
