# QQ 接入说明（NapCat / OneBot v11）

本项目原本只能对接桌面版微信（解密本地数据库收消息 + GUI 坐标/OCR 发消息）。
现在新增了一条 QQ 通道：走 **NapCat** 的 OneBot v11 接口，收发都走网络，
**不再依赖桌面窗口**，可以后台无人值守运行。

微信链路完整保留，两条通道通过 `config.py` 里的 `PLATFORM` 开关切换。

---

## ⚠️ 先读这三条

1. **务必使用 QQ 小号。** QQ 官方对第三方协议客户端的态度和微信类似，
   主号有被限制登录的风险。本项目的所有测试都应先在小号上做。
2. **同一个 QQ 号不能同时登录官方 NTQQ 和 NapCat。** 两者会互相踢下线。
   要跑机器人，就得让那个号只登在 NapCat 上。
3. **NapCat 不要解压到 `Program Files`。** 那个目录没有写权限，
   NapCat 运行时要写配置和缓存，会直接起不来。放桌面或 `D:\` 下都行。

---

## 第一步：装 NapCat

1. 打开 [NapCatQQ Releases](https://github.com/NapNeko/NapCatQQ/releases)，
   下载 `NapCat.Shell.Windows.OneKey.zip`。
2. 解压到一个**有写权限**的目录，运行里面的 `NapCatInstaller.exe`。
3. 装完后进入生成的 `NapCat.<版本>.Shell` 目录，双击 `napcat.bat`。
4. 终端里会出现一个二维码。用**手机 QQ（小号）**扫码登录。

> 如果没看到二维码，检查 `napcat.bat` 所在目录下的 `logs/` 日志；
> 常见原因是 QQ 版本不匹配或目录无写权限。

## 第二步：开 HTTP 和 WebSocket 服务

1. 浏览器打开 WebUI：`http://127.0.0.1:6099`
   （端口和登录 token 在 `napcat.bat` 的启动日志里，翻一下就能看到）
2. **立刻修改默认密码。**
3. 进「网络配置」，**新建两个**服务：

   | 类型 | 端口 | 说明 |
   |---|---|---|
   | HTTP 服务器 | `3000` | 本程序用来**发**消息 |
   | WebSocket 服务器 | `3001` | 本程序用来**收**消息 |

   两个都要：
   - 勾选**启用**
   - **务必启用 Token**（公网/局域网环境下不设 token 等于把机器人裸奔）
   - 勾选「保存时启用」

4. 记下你设置的 Token，下一步把它保存为用户环境变量；不要写进源码。

## 第三步：配置本项目

`config.py` 已提供本地默认地址：

```python
PLATFORM = 'qq'                            # 从 'wechat' 改成 'qq'

QQ_ONEBOT_HTTP  = 'http://127.0.0.1:3000'  # 对应上面的 HTTP 服务器
QQ_ONEBOT_WS    = 'ws://127.0.0.1:3001'    # 对应上面的 WebSocket 服务器
QQ_ONEBOT_TOKEN = _read_user_environment('QQ_ONEBOT_TOKEN')
QQ_SELF_ID      = 0                        # 留 0，启动时自动获取
QQ_AUTO_MARK_READ = True                   # 收到消息后标记已读
```

在 Windows“编辑账户的环境变量”中新增 `QQ_ONEBOT_TOKEN`，值与 NapCat WebUI 中的 Token 一致。修改后重启机器人进程。真实 Token 不应出现在 `config.py`、`.env.example`、Issue 或日志中。

把 `config_local.example.py` 复制为 `config_local.py`，再配置 `LISTEN_LIST`。该本地文件已被 Git 忽略。QQ 模式下填 **QQ 号或群号** 最稳妥：

```python
LISTEN_LIST = [
    ['123456789', '角色名'],      # 私聊：填对方 QQ 号
    ['987654321', '角色名'],      # 群聊：填群号
]
```

> 也支持填好友昵称、备注名、群名（会用 `get_friend_list` /
> `get_group_list` 解析），但昵称会变、还可能重名，
> **号码是稳定的，建议优先用号码。**

**不要**在 NapCat 里打开 `reportSelfMessage`。本程序在发送成功后会在本地
合成自己发的消息（`[tickle_self]`、`[recall]` 依赖它），开了反而多一份。

## 第四步：启动

用「QQ 小号 AI 控制台」启动即可。控制台检测到 `PLATFORM = 'qq'` 后，
会去确认 NapCat 的 HTTP 接口通不通，而不再检查 `weixin.exe`。

也可以直接命令行跑：

```bash
.venv\Scripts\python.exe bot.py
```

---

## 排障

先脱离本项目，单独确认 NapCat 本身是通的：

```bash
curl -s http://127.0.0.1:3000/get_login_info -H "Authorization: Bearer <你的Token>"
```

期望返回：

```json
{"status":"ok","retcode":0,"data":{"user_id":123456789,"nickname":"..."}}
```

- **连不上** → NapCat 没启动，或 HTTP 服务器没启用 / 端口不对。
- **返回 401 / token 错误** → `QQ_ONEBOT_TOKEN` 和 WebUI 里设的不一致。
- **能收消息但不回复** → 检查 `LISTEN_LIST` 里的号是否和实际发消息的号一致。
- **群聊里 @机器人 不触发** → 已处理。QQ 的 `at` 段和微信格式不同，
  传输层会把指向机器人自己的 `at` 段归一化成 `@{机器人昵称}\u2005`，
  让 `bot.py` 现有的正则能命中；如果没有触发，先确认 NapCat 登录的昵称
  和 `config.py` 里角色配置对得上。

## 已知降级项

这两项在 QQ 通道下不可用，程序会安全降级并记日志，**不会崩溃**：

| 功能 | 行为 | 原因 |
|---|---|---|
| 表情包识别（`capture()`） | 返回 `None` | OneBot 无法截图 QQ 表情 |
| 语音通话提醒（`VoiceCall()`） | 返回 `False` | OneBot 无此能力 |

`USE_VOICE_CALL_FOR_REMINDERS` 默认已是 `False`，无需额外处理。

## 切回微信

把 `config.py` 里的 `PLATFORM` 改回 `'wechat'` 即可，微信功能和配置
一个都没动。
