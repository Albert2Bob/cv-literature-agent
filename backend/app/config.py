# ============================================================
#  AI 科研问答系统 · 全局配置
#  ------------------------------------------------------------
#  所有敏感信息统一从 .env / 环境变量读取，代码中不硬编码。
#  首次使用请复制 .env.example 为 .env 并填写真实值。
# ============================================================
import os

from dotenv import load_dotenv

# 加载后端根目录下的 .env（不覆盖已存在的系统环境变量）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))


def _env(key: str, default: str = "") -> str:
    """读取环境变量并去除首尾空白。"""
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip()


def _env_int(key: str, default: int) -> int:
    """读取整数型环境变量，解析失败时回退默认值。"""
    try:
        return int(_env(key, str(default)))
    except (TypeError, ValueError):
        return default


class Config:
    """中央配置：LLM / MySQL / Redis / JWT / 服务端口。"""

    # ---------- LLM（DeepSeek，OpenAI 兼容接口） ----------
    DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE = _env("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")

    # ---------- 系统标识 ----------
    SYSTEM_NAME = _env("SYSTEM_NAME", "AI-RESEARCH")
    SYSTEM_TITLE = "AI 科研问答系统"

    # ---------- MySQL ----------
    MYSQL_HOST = _env("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = _env_int("MYSQL_PORT", 3306)
    MYSQL_USER = _env("MYSQL_USER", "root")
    MYSQL_PASSWORD = _env("MYSQL_PASSWORD", "")
    MYSQL_DB = _env("MYSQL_DB", "lsb_agent_db")

    # ---------- Redis（登录会话） ----------
    REDIS_URL = _env("REDIS_URL", "redis://127.0.0.1:6379/0")
    REDIS_TOKEN_PREFIX = _env("REDIS_TOKEN_PREFIX", "lsb:auth:token:")
    REDIS_CONNECT_TIMEOUT = _env_int("REDIS_CONNECT_TIMEOUT", 2)
    REDIS_SOCKET_TIMEOUT = _env_int("REDIS_SOCKET_TIMEOUT", 2)

    # ---------- JWT ----------
    JWT_SECRET = _env("JWT_SECRET", "ai-research-jwt-secret-32-bytes-minimum")
    JWT_EXPIRE_DAYS = _env_int("JWT_EXPIRE_DAYS", 7)

    # ---------- 服务端口 ----------
    BACKEND_PORT = _env_int("BACKEND_PORT", 8124)
    MCP_SERVER_URL = _env("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")

    # ---------- 日志 ----------
    # 控制台等级：DEBUG / INFO / SUCCESS / WARNING / ERROR / CRITICAL
    LOG_LEVEL = _env("LOG_LEVEL", "INFO")
    # 是否写文件（logs/backend.log 全量 + logs/error.log 仅 WARNING 以上）
    LOG_TO_FILE = _env("LOG_TO_FILE", "1") not in ("0", "false", "False", "")
    # 日志目录，默认 backend/logs
    LOG_DIR = _env("LOG_DIR", "") or os.path.join(_BACKEND_DIR, "logs")
    # 是否打印请求/响应体摘要（生产建议关闭；只影响摘要打印，不影响正文脱敏逻辑）
    LOG_REQUEST_BODY = _env("LOG_REQUEST_BODY", "1") not in ("0", "false", "False", "")

    # ---------- 路径 ----------
    BACKEND_DIR = _BACKEND_DIR
    DOCUMENTS_DIR = os.path.join(_BACKEND_DIR, "documents")
    CHROMA_DIR = os.path.join(_BACKEND_DIR, "chroma_db")
    SKILLS_DIR = os.path.join(_BACKEND_DIR, "skills")

    @classmethod
    def mysql_kwargs(cls) -> dict:
        """供 pymysql.connect(**kwargs) 直接展开使用的连接参数。"""
        return {
            "host": cls.MYSQL_HOST,
            "port": cls.MYSQL_PORT,
            "user": cls.MYSQL_USER,
            "password": cls.MYSQL_PASSWORD,
            "database": cls.MYSQL_DB,
            "charset": "utf8mb4",
            "cursorclass": __import__("pymysql").cursors.DictCursor,
        }

    @classmethod
    def check(cls) -> list:
        """启动前自检，返回配置问题列表（空列表表示配置完整）。"""
        problems = []
        if not cls.DEEPSEEK_API_KEY:
            problems.append("DEEPSEEK_API_KEY 未配置，LLM 调用会失败（请在 .env 中填写）")
        if not cls.MYSQL_PASSWORD:
            problems.append("MYSQL_PASSWORD 为空，若数据库已设密码请检查 .env")
        return problems
