"""本机配置示例。

复制为 config_local.py 后再改。config_local.py 不会被 Git 跟踪。
API Key 放在环境变量 DEEPSEEK_API_KEY，不要写在这个文件里。
"""

# 多开微信时才需要填。留空则用当前登录的号。
WECHAT_ACCOUNT = ""

# 每一项：[对方微信昵称或群名, 提示词文件名]
# 名字必须和微信里显示的完全一致。写进名单的群，群里的消息都会回复。
LISTEN_LIST = [
    ["对方昵称或群名", "角色1"],
]
