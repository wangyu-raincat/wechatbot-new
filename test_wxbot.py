# -*- coding: utf-8 -*-
"""wxbot 收消息的桩测试：不启动微信、不碰界面。

    python test_wxbot.py

real_sender_id 是分片内的短编号，不能写死 == 2，否则会把旧历史里的自己
当成对方，机器人就会回复自己。
"""
import sys
import time

sys.path.insert(0, ".")
import wxbot

FAILS = []
T0 = 1750000000


def ck(name, cond, got=""):
    print("%-4s %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "  <- %r" % (got,)))
    if not cond:
        FAILS.append(name)


def row(sid, ts, content="嗯", type_cn="文本", sort_seq=None):
    return dict(sender_id=sid, create_time=ts, content=content, type=type_cn,
                sort_seq=sort_seq if sort_seq is not None else ts, local_id=ts,
                sender_username="")


# 1) 判定：status==2 是主证据，表情 XML 里的 fromusername 是辅证据
votes = {"4": [43, 43], "69": [50, 0], "2": [53, 44], "94": [34, 0], "7": [4, 0]}
rows = [row(4, T0), row(69, T0 + 5), row(2, T0 + 10), row(94, T0 + 15),
        row(7, T0 + 20, "<?xml?><sysmsg/>", "系统消息"),
        row(4, T0 + 25, '<msg><emoji fromusername = "wxid_me" /></msg>', "动画表情"),
        row(94, T0 + 30, '<msg><emoji fromusername = "wxid_other" /></msg>', "动画表情")]
ids, ev = wxbot.classify_senders(rows, "wxid_me", votes)
ck("旧编号年代 status=2 的 4 判成我", "4" in ids)
ck("当前编号的 2 判成我", "2" in ids)
ck("对方 69/94 没混进来", not ({"69", "94"} & set(ids)), sorted(ids))
ck("系统消息的 id 不算我", "7" not in ids)
plain = [row(2, T0), row(4, T0 + 5), row(94, T0 + 10)]
ck("零证据时才退回 sender_id==2", wxbot.classify_senders(plain, "wxid_other", {})[0] == {"2"},
   wxbot.classify_senders(plain, "wxid_other", {})[0])
ck("只有 XML 证据也认（读不到 status 时）",
   wxbot.classify_senders([row(9, T0, '<emoji fromusername="wxid_me"/>', "动画表情")],
                          "wxid_me", {"9": [1, 0]})[0] == {"9"})
ck("名片里的 username 不算自证",
   wxbot.classify_senders([row(11, T0, '<msg username="wxid_me"/>', "42")], "wxid_me", {})[0] == set())
gids = wxbot.classify_senders([row(s, T0 + i) for i, s in enumerate([2, 4, 5, 8])],
                              "wxid_me", {"2": [9, 0], "4": [10, 10], "5": [86, 0], "8": [367, 0]})[0]
ck("群里判得出我之后，id=2 不再靠兜底冒充我", gids == {"4"}, sorted(gids))
ck("表情 XML 收成一行", wxbot._fold_xml_content('<msg><emoji fromusername="wxid_me"/></msg>', "动画表情") == "[动画表情]")
ck("普通文本保持原样", wxbot._fold_xml_content("你好", "文本") == "你好")

# 合并转发：解析失败时给空列表，不要把整段 XML 交给模型
blob = ('<?xml version="1.0"?><msg chatrecord count="2" title="群聊的聊天记录">'
        '<record displaytype="4">'
        '<item type="0" sender="wxid_aaa" sname="甲" msg="今晚八点" asmantime="1750000000" />'
        '<item type="0" sender="wxid_bbb" sname="乙" msg="收到&amp;好的" asmantime="1750000600" />'
        '</record></msg>')
got = wxbot._parse_merge_records(blob)
ck("合并转发解析出两条", len(got) == 2, got)
ck("每条是 [发送者, 内容, 时间] 三元素", all(len(x) == 3 for x in got), got)
ck("HTML 实体还原", got[1][1] == "收到&好的", got[1])
ck("时间戳转成了可读时间", got[0][2].startswith(time.strftime("%m-%d", time.localtime(1750000000))), got[0][2])
ck("解析不出来给空列表不是 None", wxbot._parse_merge_records("<msg>没有 item</msg>") == [])

print("\n%s" % ("失败 %d 项: %s" % (len(FAILS), FAILS) if FAILS else "全部通过"))
sys.exit(1 if FAILS else 0)
