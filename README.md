# 微信自动回复

监听你填的微信联系人或群聊，把收到的文字发给大模型，再把回复发回微信。

本仓库是 [fanyuantaier/wechatbot-new](https://github.com/fanyuantaier/wechatbot-new) 的精简版，只保留这条路径。许可证是 GPL-3.0。

## 需要

- 64 位 Windows 10/11
- 已经登录的电脑微信（4.1.12 及以上）
- Python 3.9 及以上

桌面不要锁屏。发送回复时，微信窗口会短暂出现在前台。

## 安装

在本目录打开命令行：

```bat
pip install -r requirements.txt
```

## 配置

1. 把 `config_local.example.py` 复制成 `config_local.py`。
2. 在 `LISTEN_LIST` 里填写对方的微信昵称或群名，必须和微信里显示的完全一致。第二项是提示词文件名，默认用 `prompts/角色1.md`。
3. 设置用户环境变量 `DEEPSEEK_API_KEY`。
4. 换服务商时，改 `config.py` 里的 `DEEPSEEK_BASE_URL` 和 `MODEL`。只要接口兼容 OpenAI 即可，例如 DeepSeek 官方是 `https://api.deepseek.com` 和 `deepseek-chat`。

人设写在 `prompts/角色1.md`。要换人设，另存一个 md，再把名单里的文件名改成新文件（不要带 `.md`）。

写进名单的群，群里每条消息都会回复。不要把不想自动回复的群加进去。

`config_local.py`、API Key、聊天记录不要提交到仓库。

## 启动

先登录微信，再双击 `启动机器人.cmd`，或在本目录执行：

```bat
python bot.py
```

## 停止

在运行窗口按 Ctrl+C，或双击 `停止机器人.cmd`。不要同时开两个机器人。
