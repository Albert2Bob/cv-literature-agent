"""
AI 科研问答系统 · Flask 应用工厂
====================================

职责：
  1. 初始化日志系统（必须在最前面，后续所有初始化都要能打日志）
  2. 创建 Flask 实例并载入配置
  3. 启动时自动建表 + 同步 RAG 知识库
  4. 请求级日志中间件（request_id 链路追踪 + 耗时统计）
  5. 统一 CORS 响应头（SSE 场景下必须允许跨域）
  6. 注册路由蓝图与全局错误处理
  7. 提供 /api/health 健康检查
"""
import os
import sys
import time

from flask import Flask, g, jsonify, request

# 日志必须先于一切初始化，这样后面所有步骤都能被记录
from app.logging_conf import (
    clear_request_context,
    get_logger,
    get_request_id,
    mask_secret,
    set_request_context,
    setup_logging,
    shorten,
)

# 保证即使不是通过 run.py 启动（如 flask CLI、调试重载），控制台也能输出中文与符号
from app.utils.console import use_utf8_console

use_utf8_console()
setup_logging()

log = get_logger("app")

# 这些路径不记访问日志，避免健康检查刷屏
_QUIET_PATHS = {"/api/health", "/favicon.ico"}


def create_app():
    """Flask 应用工厂。"""
    # 允许通过本地 pylib 目录补充依赖
    _lib = os.path.join(os.path.dirname(__file__), "..", "pylib")
    if os.path.isdir(_lib) and _lib not in sys.path:
        sys.path.insert(0, _lib)

    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    from app.config import Config

    log.info("正在初始化 %s (%s)", Config.SYSTEM_TITLE, Config.SYSTEM_NAME)
    log.debug("配置详情: 后端端口=%s 数据库=%s@%s:%s/%s LLM=%s 日志级别=%s",
              Config.BACKEND_PORT, Config.MYSQL_USER, Config.MYSQL_HOST,
              Config.MYSQL_PORT, Config.MYSQL_DB, Config.DEEPSEEK_MODEL, Config.LOG_LEVEL)
    log.debug("DeepSeek API Key: %s", mask_secret(Config.DEEPSEEK_API_KEY))

    # ---------- 启动自检 ----------
    for problem in Config.check():
        log.warning("配置告警: %s", problem)

    # ---------- 初始化 Redis 连接池 ----------
    # 登录态采用 fail-closed：Redis 不可用时应用仍可启动并提供健康检查，
    # 但登录和受保护接口会返回 503，避免绕过服务端会话校验。
    from app.redis_store import init_redis

    redis_client = init_redis(app)
    try:
        redis_client.ping()
        log.success("Redis 登录状态存储连接成功")
    except Exception as exc:  # noqa: BLE001 - 启动时保留可诊断性，鉴权请求会精确处理
        log.critical("Redis 连接失败，登录与鉴权暂不可用: %s", exc)

    # ---------- 初始化数据库表 ----------
    # 数据库不可用时只告警、不阻断启动，方便先验证服务骨架。
    try:
        with app.app_context():
            from app.auth import init_db
            from app.chat_history import init_tables as init_chat_tables
            from app.rag_store import init_rag_tables
            init_db()
            init_chat_tables()
            init_rag_tables()
        log.success("数据库表初始化完成 "
                    "(users / sessions / chat_messages / chat_summaries / rag_documents / rag_chunks)")
    except Exception as exc:  # noqa: BLE001 - 启动期需吞掉任何连接异常
        log.critical("数据库初始化失败，服务仍会启动但持久化功能不可用: %s", exc)

    # ---------- 同步 RAG 知识库（MySQL ↔ Chroma） ----------
    # 首次启动会把 documents/ 里的存量 Markdown 导入 MySQL 并建向量库；
    # 之后每次启动以 MySQL 为准，索引有效时只恢复内存索引不重算向量。
    # 失败不阻断启动：检索时还会再尝试一次。
    try:
        with app.app_context():
            from app.rag_manager import ensure_knowledge_base
            info = ensure_knowledge_base(verbose=False)
            if info.get("source") == "empty":
                log.info("RAG 知识库为空，可到「RAG 文件管理」页面上传文档")
            else:
                log.success("RAG 知识库就绪: %s 个文档 / %s 个切片 (来源=%s)",
                            info.get("documents"), info.get("chunks"), info.get("source"))
    except Exception as exc:  # noqa: BLE001
        log.error("RAG 知识库同步失败，检索时会重试: %s", exc, exc_info=True)

    # ---------- 请求日志中间件 ----------
    @app.before_request
    def _log_request_start():
        if request.path in _QUIET_PATHS:
            g.skip_logging = True
            return

        g.skip_logging = False
        g.start_time = time.perf_counter()
        # 生成链路 ID 并绑定到本次请求（后续所有日志都会带上它）
        set_request_context(endpoint=request.endpoint or "-")
        log.debug("→ %s %s 参数=%s", request.method, request.path, _summarize_args())

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    @app.after_request
    def _log_request_end(response):
        if getattr(g, "skip_logging", False):
            return response

        elapsed_ms = (time.perf_counter() - getattr(g, "start_time", time.perf_counter())) * 1000
        status = response.status_code

        # SSE 流式响应：正文会很长，只记状态与建立时间
        is_stream = str(response.mimetype or "").startswith("text/event-stream")

        fields = (request.method, request.path, status, elapsed_ms)
        if status >= 500:
            log.error("← %s %s %s (%.0fms)", *fields)
        elif status >= 400:
            log.warning("← %s %s %s (%.0fms)", *fields)
        elif is_stream:
            log.success("← %s %s %s 流式响应已建立 (%.0fms) rid=%s",
                        *fields, get_request_id())
        else:
            log.info("← %s %s %s (%.0fms)", *fields)
        return response

    @app.teardown_request
    def _log_request_teardown(exc):
        clear_request_context()

    # ---------- 全局错误处理 ----------
    @app.errorhandler(404)
    def _handle_404(err):
        log.warning("请求了不存在的路径: %s %s", request.method, request.path)
        return jsonify({"code": 404, "msg": f"接口不存在: {request.path}", "data": None}), 404

    @app.errorhandler(405)
    def _handle_405(err):
        log.warning("请求方法不允许: %s %s", request.method, request.path)
        return jsonify({"code": 405, "msg": f"方法不允许: {request.method} {request.path}", "data": None}), 405

    @app.errorhandler(Exception)
    def _handle_uncaught(err):
        from werkzeug.exceptions import HTTPException

        if isinstance(err, HTTPException):
            log.warning("HTTP %s: %s %s", err.code, request.method, request.path)
            return err

        log.error("未捕获异常: %s %s -> %s: %s",
                  request.method, request.path, type(err).__name__, err, exc_info=True)
        return jsonify({"code": 500, "msg": "服务器内部错误，请查看后端日志", "data": None}), 500

    # 浏览器/客户端在 SSE 流还没结束时关掉连接是很常见的情况（刷新页面、切走路由），
    # httpx 抛出的 ReadError 会经由 Flask 冒成 500 并打一整段堆栈，纯属噪音。
    # 注意 SSE 路由返回的是流式 Response，其生成器在请求上下文之外运行，
    # 抛出的异常不会走到这里，而是由 sse 工具层捕获并转成 [ERROR] 事件。
    try:
        import httpx as _httpx

        @app.errorhandler(_httpx.HTTPError)
        def _handle_httpx_error(err):
            log.warning("客户端连接中断（常见于刷新页面/切换路由）: %s %s -> %s",
                        request.method, request.path, type(err).__name__)
            return jsonify({"code": 499, "msg": "客户端提前断开连接", "data": None}), 499
    except ImportError:  # pragma: no cover - httpx 是必需依赖，这里只是防御
        pass

    # ---------- 业务蓝图 ----------
    from app.auth import auth_bp
    from app.routes.session import session_bp
    from app.routes.paper_reader import paper_bp
    from app.routes.cv_agent import cv_agent_bp
    from app.routes.rag import rag_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(paper_bp)
    app.register_blueprint(cv_agent_bp)
    app.register_blueprint(rag_bp)

    registered = sorted(
        f"{','.join(sorted(m for m in r.methods if m in ('GET', 'POST', 'PUT', 'DELETE')))} {r.rule}"
        for r in app.url_map.iter_rules() if "static" not in r.rule
    )
    log.info("已注册 %d 个路由", len(registered))
    for rule in registered:
        log.debug("  路由 %s", rule)

    # ---------- 健康检查 ----------
    @app.route("/api/health")
    def health():
        try:
            redis_client.ping()
            redis_status = "ok"
        except Exception:  # noqa: BLE001 - 健康检查不能因依赖故障自身返回 500
            redis_status = "unavailable"
        body = {
            "status": "ok" if redis_status == "ok" else "degraded",
            "mode": Config.SYSTEM_NAME,
            "title": Config.SYSTEM_TITLE,
            "modes": {
                "chain": "论文精读助手 (paper_reader)",
                "agent": "CV科研问答智能体 (cv_agent)",
            },
            "llm": Config.DEEPSEEK_MODEL,
            "redis": redis_status,
        }
        return jsonify(body), 200 if redis_status == "ok" else 503

    log.success("应用初始化完成，等待请求")
    return app


def _summarize_args() -> str:
    """
    汇总请求参数用于日志。

    刻意只记长度与前若干字：用户提问、文档正文都可能很长，
    也不适合完整落盘。敏感字段（密码、token）直接掩码。
    """
    from app.config import Config

    if not Config.LOG_REQUEST_BODY:
        return "(已关闭)"

    parts = []
    for key, value in list(request.args.items())[:6]:
        if key.lower() in ("password", "token", "secret", "api_key"):
            parts.append(f"{key}=***")
        elif key in ("message", "content"):
            parts.append(f"{key}={shorten(value, 40)!r}")
        else:
            parts.append(f"{key}={shorten(value, 40)}")

    if request.method in ("POST", "PUT") and request.is_json:
        body = request.get_json(silent=True) or {}
        for key, value in list(body.items())[:6]:
            if key.lower() in ("password", "token", "secret"):
                parts.append(f"{key}=***")
            elif key in ("content",):
                parts.append(f"{key}=<{len(str(value))} 字>")
            else:
                parts.append(f"{key}={shorten(value, 40)}")

    if not parts and request.method in ("POST", "PUT"):
        # multipart 上传
        if request.files:
            for key, file in list(request.files.items())[:3]:
                parts.append(f"{key}=<文件 {file.filename}>")

    return " ".join(parts) if parts else "-"
