"""One-time consent / ethics gate.

ChatRelay refuses to decrypt anything until the operator explicitly acknowledges,
once, that they are accessing *their own* WeChat account on *their own* device.

This is deliberate friction and a good-faith safeguard, not a security control:
anyone with the machine can satisfy it. Its job is to make sure that reading a
person's private messages is always a conscious, acknowledged act — never
something that happens silently just because a tool was pointed at an unlocked
computer.

Satisfy it in either way:
  * run once:   python wxcore/consent.py accept
  * or set env: CHATRELAY_I_OWN_THIS_DATA=1
"""
import os, sys

_FLAG = os.path.join(os.path.expanduser("~"), ".chatrelay_consent")

NOTICE = """\
============================ ChatRelay — 使用须知 ============================
本工具通过读取微信进程内存与本地数据库，解密并索引聊天记录。使用前请确认：

  1. 你读取的是【你本人拥有】、或你在【自有设备上有权访问】的微信数据。
  2. 你【不会】用它读取、监控、跟踪他人的微信，也不会部署到他人设备或
     远程静默运行。
  3. 解密依赖逆向手段，很可能违反微信服务条款，存在账号风控/封禁风险，
     后果由你自行承担。

This tool decrypts and indexes WeChat messages by reading process memory and
local databases. By continuing you confirm you are accessing ONLY your own
account on your own device, you will not use it to read anyone else's messages,
and you accept the account/ToS risk.
=============================================================================
"""


def consented():
    """True if consent has been given (flag file or env var)."""
    if os.environ.get("CHATRELAY_I_OWN_THIS_DATA") == "1":
        return True
    return os.path.exists(_FLAG)


class ConsentError(RuntimeError):
    """Raised when the operator has not acknowledged the usage notice."""


def require_consent():
    """Call before any decryption. Raises ConsentError (a normal Exception, so an
    MCP tool returns it as an error instead of hanging — SystemExit/BaseException
    would never reach the client) if the notice has not been acknowledged."""
    if consented():
        return
    raise ConsentError(
        "使用须知未确认，已拒绝解密。请先运行  python wxcore/consent.py accept  "
        "（或设置环境变量 CHATRELAY_I_OWN_THIS_DATA=1），再重试。")


def _accept():
    sys.stdout.write(NOTICE)
    with open(_FLAG, "w", encoding="utf-8") as f:
        f.write("accepted\n")
    sys.stdout.write(f"\n[ChatRelay] 已记录确认：{_FLAG}\n撤销：删除该文件即可。\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "accept":
        _accept()
    elif len(sys.argv) > 1 and sys.argv[1] == "revoke":
        try:
            os.remove(_FLAG)
            sys.stdout.write("[ChatRelay] 已撤销确认。\n")
        except FileNotFoundError:
            sys.stdout.write("[ChatRelay] 本来就没有确认记录。\n")
    else:
        sys.stdout.write(NOTICE)
        sys.stdout.write("\nusage: python wxcore/consent.py [accept|revoke]\n")
