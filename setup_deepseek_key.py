"""Secure, local first-run setup for the DeepSeek API key."""

from __future__ import annotations

import ctypes
import getpass
import sys
import winreg

from openai import OpenAI


def main() -> int:
    print("DeepSeek 首次配置")
    print("密钥输入时不会显示，也不会写入项目文件。")
    api_key = getpass.getpass("请输入 DeepSeek API Key: ").strip()
    if not api_key:
        print("未输入密钥，配置已取消。")
        return 1

    try:
        response = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        ).chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "只回复OK"}],
            max_tokens=8,
            temperature=0,
        )
        reply = response.choices[0].message.content.strip()
        if reply != "OK":
            raise RuntimeError("接口返回异常")
    except Exception as exc:
        print(f"验证失败：{type(exc).__name__}。未保存密钥。")
        return 2

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "DEEPSEEK_API_KEY", 0, winreg.REG_SZ, api_key)

    # Notify Explorer and future processes that the user environment changed.
    result = ctypes.c_void_p()
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF, 0x001A, 0, "Environment", 2, 5000, ctypes.byref(result)
    )
    print("配置成功，DeepSeek 官方接口验证通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
