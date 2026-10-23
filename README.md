# 微信自动回复 · 精简版

![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Windows 10 / 11](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4)
![OpenAI compatible](https://img.shields.io/badge/API-OpenAI%20compatible-62745B)
[![GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue)](LICENSE)

在已登录的 Windows 电脑微信上，监听指定联系人或群聊，将收到的文字交给大模型，再把生成的回复发回原会话。

本仓库是 [fanyuantaier/wechatbot-new](https://github.com/fanyuantaier/wechatbot-new) 的精简 fork，聚焦一条完整路径：

**指定微信会话 → 文字消息队列 → OpenAI 兼容模型接口 → 微信回复**

> 当前公开 `main` 分支为微信精简版，不包含 QQ / NapCat / OneBot 通道或 Web 配置台。安装与使用请以本 README 和当前分支源码为准。

## 能做什么

- 按名单监听私聊或群聊，为不同会话指定不同的 Markdown 人设文件。
- 调用 DeepSeek 等兼容 OpenAI Chat Completions 的接口生成文字回复。
- 将连续收到的消息合并处理，并为每个会话保留有限轮次的上下文。

**群聊行为：**加入 `LISTEN_LIST` 的群，其有效新消息都会进入回复队列，不要求有人 @ 机器人；连续消息可能合并回复。不要添加不希望自动回复的群。

## 运行前准备

- 64 位 Windows 10 / 11。
- Python 3.9 或以上，且命令行能够执行 `python`。
- 已登录的电脑微信，版本 4.1.12 或以上；具体兼容性取决于微信版本与自动化依赖。
- 可用的模型服务 API Key，以及对应的接口地址和模型名称。

运行期间保持桌面会话可用，不要锁屏。发送回复时，微信窗口会短暂出现在前台。

## 三步上手

### 1. 下载源码并安装依赖

下载本仓库源码并解压，在包含 `bot.py` 的根目录打开 PowerShell：

```powershell
python -m pip install -r requirements.txt
```

依赖中的 `wechatauto-replica[guia]` 用于微信收发，`openai` 用于调用模型服务。

### 2. 设置监听名单、人设和 API Key

先复制本机配置：

```powershell
Copy-Item config_local.example.py config_local.py
```

编辑 `config_local.py`，将示例名字替换为微信中显示的联系人昵称或群名，必须完全一致：

```python
WECHAT_ACCOUNT = ""  # 默认使用当前登录的微信；多开时再指定账号标识

LISTEN_LIST = [
    ["对方的微信昵称", "角色1"],
    # ["需要自动回复的群名", "角色1"],
]
```

第二项对应 `prompts/角色1.md`，填写时不带 `.md`。人设直接写在该文件中；要使用不同人设，可另存为 `prompts/新角色.md`，再把名单中的第二项改为 `新角色`。

在 Windows 的**用户环境变量**中添加 `DEEPSEEK_API_KEY`，值填写模型服务提供的真实 Key。也可在 PowerShell 中执行以下命令，先替换示例值：

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "替换成你的_API_Key", "User")
```

当前默认服务为 DeepSeek 官方：

```python
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"
```

默认值位于 `config.py`。更换服务商时可修改这些默认值，也可以将同名变量放入 `config_local.py` 覆盖；接口地址和模型名必须配套。

`.env.example` 仅列出变量名，程序不会自动加载 `.env`。API Key 请使用环境变量保存，不要写进源码或提交到仓库。

### 3. 登录微信并启动

确认电脑微信已登录，在仓库根目录运行：

```powershell
python bot.py
```

也可以双击 `启动机器人.cmd`。看到“正在监听私聊 / 群聊”和“机器人已启动”后，从名单中的会话发送一条新消息进行验证。

不要同时启动两个机器人实例。

## 常用配置

`config.py` 提供默认值，`config_local.py` 用于本机覆盖。调整配置后重新启动机器人。

| 配置项 | 默认值 / 用途 |
| --- | --- |
| `LISTEN_LIST` | 自动回复名单及各自的人设文件，必须自行填写 |
| `WECHAT_ACCOUNT` | 默认留空；多开微信时选择账号 |
| `DEEPSEEK_API_KEY` | 从用户环境变量读取模型服务 Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `MODEL` | `deepseek-chat` |
| `MAX_GROUPS` | `12`，每个会话保留的最近对话轮数 |
| `QUEUE_WAITING_TIME` | `4` 秒，连续消息静默后再合并生成回复 |
| `MAX_TOKEN` | `2000`，单次生成的最大 token 数 |
| `TEMPERATURE` | `1.0` |

## 停止运行

优先在运行窗口按 **Ctrl+C**，等待“已停止”提示。

也可双击 `停止机器人.cmd`。该脚本读取本目录的 `bot.pid`，强制结束记录的进程；它不是优雅退出方式。

## 常见问题

| 现象 | 检查方向 |
| --- | --- |
| 提示“监听名单是空的” | 确认已复制 `config_local.example.py`，并在 `config_local.py` 填写 `LISTEN_LIST`。 |
| 提示“没有 API Key” | 检查 Windows 用户环境变量 `DEEPSEEK_API_KEY`。Windows 上会优先读取已有的用户变量，再读取当前进程变量。 |
| 提示“找不到提示词文件” | 确认对应 `.md` 文件存在于 `prompts/`，名单中不要填写文件夹路径。 |
| 提示“监听某会话失败” | 核对昵称或群名与微信显示是否完全一致，并确认当前登录的是目标账号。 |
| 提示“微信自动化库不可用” | 在实际用于启动机器人的 Python 环境中重新安装 `requirements.txt`。 |
| 提示“连接微信失败”或无法发送 | 先登录微信，解除锁屏，保持桌面可用；微信升级后还需核对自动化依赖的兼容性。 |
| 收到消息但没有模型回复 | 查看运行窗口中的 API 错误，检查 Key、接口地址、模型名及服务额度。 |
| 停止脚本找不到 `bot.pid` | 机器人可能尚未成功启动或已经退出；检查原运行窗口，不要重复启动。 |

## 数据与能力边界

- 当前模型请求传递的是文字。图片、表情、语音、视频等可能转换为文字描述或占位标记，不提供图片识别、语音转写或语音回复。
- 接收到的文字、配置的人设与最近会话上下文，会发送到你配置的模型服务。
- 会话上下文保存在仓库根目录的 `chat_contexts.json`；运行窗口也会显示部分消息内容。
- `config_local.py`、真实 API Key、聊天记录和运行日志不要提交到仓库。`.gitignore` 已排除常见本机配置与运行数据，但提交前仍应检查实际文件。
- 本项目依赖 Windows 桌面微信自动化，不提供 Linux 无桌面运行方式，也不保证未来所有微信版本兼容。

## 项目来源与许可证

本 fork 基于 [fanyuantaier/wechatbot-new](https://github.com/fanyuantaier/wechatbot-new) 精简，保留原有版权与许可声明。

[LICENSE](LICENSE) 记载了 WeChatBot_WXAUTO_SE 项目的来源与版权信息，包括 Copyright © 2025 **umaru**、**iwyxdxl**，并指向 [iwyxdxl/WeChatBot_WXAUTO_SE](https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE)。当前代码亦注明基于 KouriChat / WeChatBot 的收发循环精简而来。

本项目遵循 **GNU GPL 第 3 版或任何更高版本（GPL-3.0-or-later）**，按现状提供，不作任何担保。请保留原有版权与许可证声明，并以仓库中的完整 [LICENSE](LICENSE) 为准。
