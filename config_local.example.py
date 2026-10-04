"""本地配置示例。

复制为 config_local.py 后填写。config_local.py 不会被 Git 跟踪。
API Key 和 OneBot Token 仍建议放在用户环境变量中，不要写进这个文件。
"""

# 微信模式可填写实际登录账号；留空时由底层自动选择。
WECHAT_ACCOUNT = ''

# 每项格式：[联系人昵称、prompt 文件名（不含 .md）]
# QQ 模式下建议使用对方 QQ 号或群号；不要填写机器人自己的账号。
LISTEN_LIST = [
    ['对方昵称或账号', '角色1'],
]

# 机器人 QQ 号建议保持为 0，由 OneBot 启动时自动识别。
QQ_SELF_ID = 0

# 群聊关键词可能包含姓名、群内称呼等私密信息，只放在本地配置。
GROUP_KEYWORD_LIST = ['机器人']
