"""
控制台输出兼容工具
==================
Windows 下 Python 默认用 GBK 编码标准输出，打印 emoji / 特殊符号会抛
UnicodeEncodeError：'gbk' codec can't encode character ...

大量使用 ✅ ⚠️ 等符号打印进度，在部分 Windows 控制台会直接崩溃。
这里在启动时统一切换为 UTF-8，避免环境差异导致的启动失败。
"""
import sys


def use_utf8_console() -> None:
    """尽量把 stdout / stderr 切换为 UTF-8，失败时静默忽略。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 纯兼容处理，失败不影响业务
            pass
