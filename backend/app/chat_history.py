"""
聊天历史管理（持久化记忆）
==========================

  三张表：
    sessions        会话元信息（user_id / session_id / chat_type / title / 时间）
    chat_messages   消息明细（role / content / msg_order）
    chat_summaries  对话摘要（长对话压缩）

  两个模式：
    chat_type = 'doc'    论文精读助手（Chain 模式）
    chat_type = 'agent'  CV科研问答智能体（ReAct Agent 模式）

  摘要策略：
    - 轮次触发：每 SUMMARY_INTERVAL 轮（user+assistant 算一轮）生成一次
    - Token 阈值触发：累计字符数 / 2 估算 token，超过 SUMMARY_TOKEN_THRESHOLD 强制生成
"""
import uuid

from app.auth import get_db
from app.logging_conf import get_logger, shorten

log = get_logger("chat_history")

# ── 常量 ──────────────────────────────────────────────────────────────

# 对话模式
CHAT_TYPE_DOC = "doc"        # 论文精读助手（Chain 模式）
CHAT_TYPE_AGENT = "agent"    # CV科研问答智能体（Agent 模式）
VALID_CHAT_TYPES = (CHAT_TYPE_DOC, CHAT_TYPE_AGENT)

# 上下文包含的最近消息数量
RECENT_LIMIT = 50

# 摘要更新策略
SUMMARY_INTERVAL = 5            # 每隔多少轮对话更新一次摘要
SUMMARY_TOKEN_THRESHOLD = 4000  # 累计消息估算 token 超过此值时强制触发摘要
SUMMARY_SOURCE_LIMIT = 20       # 生成摘要时读取的最近消息条数


# ── 表初始化 ──────────────────────────────────────────────────────────

def init_tables():
    """创建会话 / 聊天消息 / 聊天摘要三张表。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_id    INT NOT NULL,
                    session_id VARCHAR(100) NOT NULL UNIQUE,
                    chat_type  VARCHAR(20) NOT NULL COMMENT 'doc=论文精读助手 agent=CV科研智能体',
                    title      VARCHAR(200) DEFAULT '新对话',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_user_id (user_id),
                    INDEX idx_user_chat_type (user_id, chat_type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(100) NOT NULL,
                    role       VARCHAR(20) NOT NULL COMMENT 'user or assistant',
                    content    TEXT NOT NULL,
                    msg_order  INT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_session_id (session_id),
                    INDEX idx_session_order (session_id, msg_order)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_summaries (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(100) NOT NULL UNIQUE,
                    summary    TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_session_id (session_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
    finally:
        conn.close()


# ── 会话 CRUD ─────────────────────────────────────────────────────────

def create_session(user_id, chat_type, title=None):
    """创建新会话，返回 8 位 session_id。"""
    if chat_type not in VALID_CHAT_TYPES:
        chat_type = CHAT_TYPE_DOC
    session_id = str(uuid.uuid4())[:8]
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (user_id, session_id, chat_type, title) VALUES (%s, %s, %s, %s)",
                (user_id, session_id, chat_type, title or "新对话"),
            )
        conn.commit()
    finally:
        conn.close()
    log.info("会话已创建: session=%s 模式=%s 用户=%s", session_id, chat_type, user_id)
    return session_id


def get_user_sessions(user_id, chat_type):
    """获取用户某模式下的全部会话，按 updated_at 降序。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT session_id, title, chat_type, created_at, updated_at "
                "FROM sessions WHERE user_id=%s AND chat_type=%s ORDER BY updated_at DESC",
                (user_id, chat_type),
            )
            return cur.fetchall()
    finally:
        conn.close()


def rename_session(session_id, title):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET title=%s WHERE session_id=%s", (title, session_id))
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id):
    """删除会话及其全部消息与摘要。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_messages WHERE session_id=%s", (session_id,))
            cur.execute("DELETE FROM chat_summaries WHERE session_id=%s", (session_id,))
            cur.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))
        conn.commit()
    finally:
        conn.close()


def get_session_title(session_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title, chat_type FROM sessions WHERE session_id=%s", (session_id,))
            return cur.fetchone()
    finally:
        conn.close()


def maybe_auto_title(session_id, first_message):
    """
    会话仍是默认标题时，用首条用户消息自动命名。

    保留手动重命名能力，同时提供自动命名。
    """
    row = get_session_title(session_id)
    if not row or row.get("title") not in (None, "", "新对话"):
        return
    title = " ".join(first_message.strip().split())
    if len(title) > 30:
        title = title[:30] + "…"
    if title:
        rename_session(session_id, title)
        log.debug("会话已按首条消息自动命名: session=%s title=%r", session_id, title)


# ── 消息 CRUD ─────────────────────────────────────────────────────────

def save_message(session_id, role, content):
    """
    保存消息并自动分配 msg_order。

    使用 SELECT ... FOR UPDATE 在同一事务内取号，避免并发请求
    分配到相同 msg_order。
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(msg_order), 0) + 1 AS next_order "
                "FROM chat_messages WHERE session_id=%s FOR UPDATE",
                (session_id,),
            )
            next_order = cur.fetchone()["next_order"]
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content, msg_order) VALUES (%s, %s, %s, %s)",
                (session_id, role, content, next_order),
            )
        conn.commit()
        return next_order
    finally:
        conn.close()


def get_session_messages(session_id):
    """获取会话全部消息，按 msg_order 升序。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, msg_order, created_at FROM chat_messages "
                "WHERE session_id=%s ORDER BY msg_order ASC",
                (session_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def load_recent_messages(session_id, limit=RECENT_LIMIT):
    """加载最近 N 条消息（按时间正序返回），用于构建上下文。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id=%s ORDER BY msg_order DESC LIMIT %s",
                (session_id, limit),
            )
            rows = cur.fetchall()
            return list(reversed(rows))
    finally:
        conn.close()


def get_message_count(session_id):
    """会话消息总数。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM chat_messages WHERE session_id=%s", (session_id,))
            return cur.fetchone()["cnt"]
    finally:
        conn.close()


def get_total_chars(session_id):
    """会话全部消息字符数，用于粗略估算 token。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(CHAR_LENGTH(content)), 0) AS total "
                "FROM chat_messages WHERE session_id=%s",
                (session_id,),
            )
            return cur.fetchone()["total"]
    finally:
        conn.close()


# ── 摘要管理 ──────────────────────────────────────────────────────────

def load_summary(session_id):
    """读取会话摘要，无则返回空串。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT summary FROM chat_summaries WHERE session_id=%s", (session_id,))
            row = cur.fetchone()
            return row["summary"] if row and row["summary"] else ""
    finally:
        conn.close()


def save_summary(session_id, summary_text):
    """插入或更新会话摘要。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(

            )
        conn.commit()
    finally:
        conn.close()


# 科研语境摘要提示词
_SUMMARY_PROMPT = (
    "请将以下计算机视觉 / 深度学习科研问答的对话压缩为中文摘要，"
    "只保留以下信息：\n"
    "1. 用户的研究方向、任务背景与关注的模型 / 数据集\n"
    "2. 用户提出的核心技术问题或诉求\n"
    "3. 已经给出的关键结论、方法建议、公式或实验方案\n"
    "4. 仍然悬而未决的问题\n"
    "不要重复对话细节，只做概括，保持术语准确（模型名、指标名保留英文原文）。\n\n"
    "当前摘要：\n{summary}\n\n"
    "新的对话行：\n{new_lines}\n\n"
    "新的摘要（不超过 500 字）："
)


def should_update_summary(session_id):
    """
    判断是否应该触发摘要更新。

    条件 1：消息轮数达到 SUMMARY_INTERVAL 的整数倍
    条件 2：累计字符数估算的 token 超过 SUMMARY_TOKEN_THRESHOLD
    """
    msg_count = get_message_count(session_id)
    rounds = msg_count // 2
    if rounds > 0 and rounds % SUMMARY_INTERVAL == 0:
        return True
    estimated_tokens = get_total_chars(session_id) / 2
    return estimated_tokens >= SUMMARY_TOKEN_THRESHOLD


def update_summary(session_id, force=False):
    """
    按策略生成 / 更新对话摘要。

    Args:
        session_id: 会话 ID
        force:      True 时跳过触发条件判断，立即生成（用于调试）
    Returns:
        新摘要文本；跳过或失败时返回空串。
    """
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from app.llm import llm

    if not force and not should_update_summary(session_id):
        log.debug("摘要未到触发条件，跳过: session=%s", session_id)
        return ""

    recent = load_recent_messages(session_id, SUMMARY_SOURCE_LIMIT)
    if len(recent) < 2:
        return ""

    existing = load_summary(session_id)

    new_lines = ""
    for msg in recent:
        prefix = "用户" if msg["role"] == "user" else "AI"
        new_lines += f"{prefix}: {msg['content']}\n"

    prompt = ChatPromptTemplate.from_messages([("human", _SUMMARY_PROMPT)])
    chain = prompt | llm | StrOutputParser()

    try:
        new_summary = chain.invoke({"summary": existing, "new_lines": new_lines}).strip()
    except Exception as exc:  # noqa: BLE001 - 摘要失败不应影响主流程
        log.error("摘要生成失败（不影响本轮对话）: session=%s -> %s", session_id, exc, exc_info=True)
        return ""

    if new_summary:
        save_summary(session_id, new_summary)
        log.success("对话摘要已更新: session=%s 摘要 %d 字（覆盖最近 %d 条消息）",
                    session_id, len(new_summary), len(recent))
    return new_summary


def build_context(session_id):
    """构建上下文 = 【对话摘要】 + 【最近对话】。"""
    summary = load_summary(session_id)
    recent = load_recent_messages(session_id, RECENT_LIMIT)

    parts = []
    if summary:
        parts.append(f"【对话摘要】\n{summary}")
    if recent:
        lines = ["【最近对话】"]
        for msg in recent:
            prefix = "用户" if msg["role"] == "user" else "AI"
            lines.append(f"{prefix}: {msg['content']}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)
