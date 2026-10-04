# 安全说明

## 敏感信息

请勿提交 API Key、OneBot Token、QQ/微信账号、二维码、Cookie、会话文件、聊天记录、记忆文件、日志或本机路径配置。

- DeepSeek Key 使用用户环境变量 `DEEPSEEK_API_KEY`。
- NapCat/OneBot Token 使用用户环境变量 `QQ_ONEBOT_TOKEN`。
- 本机账号、监听对象和路径可写入 `config_local.py`；该文件已被 Git 忽略。
- `.env.example` 只列变量名，真实 `.env` 文件会被 Git 忽略。
- 用户自定义 Prompt 写入 `prompts_local/`，聊天记忆写入 `CoreMemory/`；两者均不纳入发布。
- 导入前备份默认写入用户数据目录，不放在仓库内；可用 `WECHATBOT_BACKUP_DIR` 另行指定。

提交前请检查当前工作树和完整 Git 历史。若密钥曾进入提交历史，仅删除当前文件是不够的：应立即吊销或轮换密钥，并清理历史后再发布。

不要直接压缩整个工作目录发布：Git 忽略规则不会阻止压缩工具收入本地日志、记忆和会话文件。应使用 Git 导出或已验证的源码发行包。

## 网络边界

OneBot HTTP 与 WebSocket 默认只连接 `127.0.0.1`。不要把 3000/3001 端口直接暴露到公网；启用 Token，并限制管理端口的访问范围。

本地 WebUI 默认只接受 `localhost` / `127.0.0.1` / `::1` 主机头，并拒绝浏览器跨站写请求。请勿通过反向代理对公网开放它。

## 漏洞报告

请通过 GitHub Security Advisory 私下报告漏洞，不要在公开 Issue 中附带真实密钥、账号、聊天内容或可识别个人身份的数据。
