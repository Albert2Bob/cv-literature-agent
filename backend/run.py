"""启动入口。

用法：
    python run.py

提供启动前「配置自检 + 端口预检」与清晰的启动横幅。

可用环境变量：
    LOG_LEVEL=DEBUG            控制台日志等级
    FLASK_USE_RELOADER=1       开启 Flask 自动重载（默认关闭，见下方说明）
"""
import os
import ssl
import sys

# Windows + 旧版本 Python 的 SSL 兼容处理
if sys.platform == "win32" and sys.version_info < (3, 10):
    ssl._create_default_https_context = ssl._create_unverified_context
    ssl.create_default_context = ssl._create_unverified_context

# Windows 控制台编码兼容：必须在任何 print 之前执行
from app.utils.console import use_utf8_console

use_utf8_console()

from app import create_app
from app.config import Config
from app.logging_conf import get_logger, log_banner, mask_secret, setup_logging

# 日志系统要在 create_app 之前就绪，这样初始化过程的每一步都能被记录
setup_logging()
log = get_logger("run")


# ==============================================================
#  端口预检
# ==============================================================
# 为什么需要预检：
#   create_app() 要加载 embedding 模型与向量库，耗时 20~30 秒。如果等那时才发现
#   端口被占用，等于白等半分钟；而 Werkzeug 在端口被占用时只会打印一句系统级报错
#   （Windows 下是「以一种访问权限不允许的方式做了一个访问套接字的尝试」）然后
#   直接退出——既不抛异常，也走不到 except OSError，用户完全看不出是端口冲突。
#   所以这里提前探测并给出可执行的解决办法。

def _port_available(host: str, port: int) -> bool:
    """探测端口是否可绑定（只探测，不实际占用）。"""
    import socket

    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((probe_host, port))
            return True
        except OSError:
            return False


def _port_owner(port: int) -> str:
    """
    尽力查出占用端口的进程 PID。

    查不到时返回空串——沙箱或权限受限环境下 netstat 可能不可用，
    这不影响主流程（我们只是想让报错信息更有用）。
    """
    import subprocess

    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return ""

    pids = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        # 形如：TCP  0.0.0.0:8124  0.0.0.0:0  LISTENING  12345
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and f":{port}" in parts[1]:
            pids.add(parts[-1])
    return ", ".join(sorted(pids))


def _fail_port_in_use(port: int) -> None:
    """端口被占用时给出可执行的指引。"""
    owner = _port_owner(port)
    log.critical("=" * 62)
    log.critical("启动失败：端口 %s 已被占用", port)
    if owner:
        log.critical("占用该端口的进程 PID: %s", owner)
    log.critical("最常见的原因是上一次的后端进程没有正常退出（或另一个终端还开着）。")
    log.critical("解决办法（任选其一）：")
    log.critical("  1) 结束占用进程（推荐）——PowerShell 里执行：")
    log.critical("     Get-NetTCPConnection -LocalPort %s -State Listen | "
                 "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }", port)
    log.critical("  2) 若上面查不到，用 netstat 找 PID 再杀：")
    log.critical("     netstat -ano | findstr :%s     然后  taskkill /PID <PID> /F", port)
    log.critical("  3) 换个端口：在 .env 里改 BACKEND_PORT，"
                 "并同步修改前端 api/index.js 的 API_BASE_URL。")
    log.critical("确认是否已释放：netstat -ano | findstr :%s  （无输出即已释放）", port)
    log.critical("=" * 62)


def _preflight_port() -> None:
    """启动前检查端口；被占用则打印指引并以退出码 1 结束。"""
    if _port_available("0.0.0.0", Config.BACKEND_PORT):
        return
    _fail_port_in_use(Config.BACKEND_PORT)
    sys.exit(1)


# ---------- 端口预检必须在 create_app 之前 ----------
if __name__ == "__main__":
    _preflight_port()

app = create_app()


if __name__ == "__main__":
    log_banner(log, f"{Config.SYSTEM_TITLE}（{Config.SYSTEM_NAME}）", [
        "Chain 模式 -> 论文精读助手    Agent 模式 -> CV科研问答智能体",
        f"API   : http://localhost:{Config.BACKEND_PORT}",
        f"DB    : {Config.MYSQL_USER}@{Config.MYSQL_HOST}:{Config.MYSQL_PORT}/{Config.MYSQL_DB}",
        "Redis : 登录会话存储（连接信息已隐藏）",
        f"LLM   : {Config.DEEPSEEK_MODEL} @ {Config.DEEPSEEK_API_BASE}",
        f"密钥  : {mask_secret(Config.DEEPSEEK_API_KEY)}",
        f"日志  : 控制台 {Config.LOG_LEVEL} / 文件 {Config.LOG_DIR if Config.LOG_TO_FILE else '已关闭'}",
    ])

    # 关于 use_reloader：
    #   Flask debug 的自动重载会 fork 出第二个进程，两个进程都会执行 create_app()，
    #   其中包含 RAG 知识库的启动同步。两个进程同时操作同一个 Chroma 持久化目录，
    #   会让其中一个进程手里的集合句柄失效，报
    #   "Collection [...] does not exist"。
    #   因此这里默认关闭重载（向量库初始化本身较重，重载收益也有限）。
    #   需要热重载时设环境变量 FLASK_USE_RELOADER=1。
    use_reloader = os.getenv("FLASK_USE_RELOADER", "0") == "1"
    if not use_reloader:
        log.debug("自动重载已关闭（设 FLASK_USE_RELOADER=1 可开启）")

    log.success("HTTP 服务启动中，监听 0.0.0.0:%s ...", Config.BACKEND_PORT)
    try:
        app.run(host="0.0.0.0", port=Config.BACKEND_PORT, debug=True, threaded=True,
                use_reloader=use_reloader)
    except KeyboardInterrupt:
        log.info("收到中断信号，服务正在关闭")
    except OSError as exc:
        # 兜底：预检通过但绑定仍失败（例如端口在预检之后被抢占）
        log.critical("服务启动失败: %s", exc)
        _fail_port_in_use(Config.BACKEND_PORT)
        sys.exit(1)
    finally:
        log.info("服务已停止")
