"""
RAG 文档元数据存储（MySQL）
==========================
知识库文件的「权威记录」存在 MySQL，向量数据存在 Chroma，两边通过文件名关联。

  一次解析 → 两次保存
    ① ChromaDB   : 存切片的向量（负责语义检索）
    ② MySQL      : 存文档元信息 + 切片原文（负责管理界面展示与重建索引）

  两张表
    rag_documents : 文档级元信息（名称/标题/格式/大小/切片数/内容哈希/状态）
    rag_chunks    : 切片级记录（所属文档/序号/正文/来源/章节）

设计要点：
  - documents.name 是业务主键（前端就按文件名定位文档），同时作为 Chroma 的 doc_id
  - content_hash 用于判断「内容是否真的变了」——没变就不重建向量
  - 删除文档时级联删除其切片记录（外键 ON DELETE CASCADE）
"""
import hashlib
import json
from datetime import datetime

from app.auth import get_db

# 支持的文档格式 → 前端展示用的扩展名
SUPPORTED_EXTENSIONS = {"md", "markdown", "txt", "pdf", "docx", "doc"}

# 文档处理状态
STATUS_READY = "ready"        # 已解析并写入向量库
STATUS_FAILED = "failed"      # 解析或索引失败
STATUS_PENDING = "pending"    # 已登记但尚未索引


# ── 建表 ──────────────────────────────────────────────────────────────

def init_rag_tables():
    """创建 RAG 文档与切片两张表。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    name          VARCHAR(255) NOT NULL UNIQUE COMMENT '文件名，业务主键',
                    title         VARCHAR(255) NOT NULL DEFAULT '',
                    extension     VARCHAR(16)  NOT NULL DEFAULT '',
                    size          INT          NOT NULL DEFAULT 0,
                    chunk_count   INT          NOT NULL DEFAULT 0,
                    content       LONGTEXT     NULL COMMENT '文档全文，用于查看与重建索引',
                    content_hash  VARCHAR(64)  NOT NULL DEFAULT '',
                    status        VARCHAR(16)  NOT NULL DEFAULT 'ready',
                    error_msg     VARCHAR(500) NOT NULL DEFAULT '',
                    owner_id      INT          NULL COMMENT '上传者 user_id，可为空',
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_updated (updated_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    doc_name   VARCHAR(255) NOT NULL,
                    chunk_index INT         NOT NULL COMMENT '切片序号，从 0 开始',
                    content    TEXT        NOT NULL,
                    source     VARCHAR(255) NOT NULL DEFAULT '' COMMENT '来源文件名',
                    section    VARCHAR(255) NOT NULL DEFAULT '' COMMENT '所属章节标题',
                    char_count INT          NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_doc_name (doc_name),
                    INDEX idx_doc_order (doc_name, chunk_index),
                    CONSTRAINT fk_rag_chunk_doc FOREIGN KEY (doc_name)
                        REFERENCES rag_documents(name) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
    finally:
        conn.close()


# ── 工具函数 ──────────────────────────────────────────────────────────

def compute_hash(content: str) -> str:
    """计算内容哈希，用于判断文档是否发生变化。"""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def get_extension(name: str) -> str:
    """从文件名提取小写扩展名。"""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def normalize_name(name: str) -> str:
    """
    规范化文件名：去掉路径分隔符、首尾空白，防止目录穿越。
    只保留文件名部分，例如 "../../etc/passwd" → "passwd"。
    """
    safe = (name or "").strip().replace("\\", "/").split("/")[-1]
    return safe.strip()


# ── 文档 CRUD ─────────────────────────────────────────────────────────

def upsert_document(name, title, ext, size, content, chunk_count,
                    status=STATUS_READY, error_msg="", owner_id=None):
    """
    插入或更新一条文档记录。

    以 name 为唯一键：已存在则更新（保留原 id），不存在则插入。
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rag_documents
                    (name, title, extension, size, chunk_count, content,
                     content_hash, status, error_msg, owner_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    extension = VALUES(extension),
                    size = VALUES(size),
                    chunk_count = VALUES(chunk_count),
                    content = VALUES(content),
                    content_hash = VALUES(content_hash),
                    status = VALUES(status),
                    error_msg = VALUES(error_msg)
            """, (name, title, ext, size, chunk_count, content,
                  compute_hash(content), status, error_msg, owner_id))
        conn.commit()
    finally:
        conn.close()


def replace_chunks(doc_name, chunks):
    """
    用新的切片集合替换某个文档的全部切片记录（先删后插，保证一致性）。

    Args:
        doc_name: 文件名
        chunks:   [{"index":0,"content":"...","source":"x.md","section":"..."}]
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE doc_name=%s", (doc_name,))
            if chunks:
                cur.executemany(
                    "INSERT INTO rag_chunks (doc_name, chunk_index, content, source, section, char_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (doc_name, c["index"], c["content"],
                         c.get("source", doc_name), c.get("section", ""), len(c["content"]))
                        for c in chunks
                    ],
                )
        conn.commit()
    finally:
        conn.close()


def list_documents():
    """列出全部文档（不含 content 大字段，避免列表接口过重）。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, title, extension, size, chunk_count,
                       content_hash, status, error_msg, created_at, updated_at
                FROM rag_documents ORDER BY updated_at DESC
            """)
            return cur.fetchall()
    finally:
        conn.close()


def get_document(name):
    """按文件名取单个文档（含全文）。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, title, extension, size, chunk_count, content,
                       content_hash, status, error_msg, created_at, updated_at
                FROM rag_documents WHERE name=%s
            """, (name,))
            return cur.fetchone()
    finally:
        conn.close()


def get_chunks(doc_name):
    """取某个文档的全部切片，按序号升序。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT chunk_index, content, source, section, char_count
                FROM rag_chunks WHERE doc_name=%s ORDER BY chunk_index ASC
            """, (doc_name,))
            return cur.fetchall()
    finally:
        conn.close()


def delete_document(name):
    """删除文档记录（其切片由外键级联删除）。返回是否真的删掉了。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # 显式删切片，避免外键未生效时残留脏数据
            cur.execute("DELETE FROM rag_chunks WHERE doc_name=%s", (name,))
            affected = cur.execute("DELETE FROM rag_documents WHERE name=%s", (name,))
        conn.commit()
        return affected > 0
    finally:
        conn.close()


def count_documents():
    """文档总数与切片总数，供概览使用。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS docs, COALESCE(SUM(chunk_count), 0) AS chunks FROM rag_documents")
            return cur.fetchone()
    finally:
        conn.close()


def all_document_names():
    """全部文件名集合，用于向量库与 MySQL 的一致性比对。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM rag_documents")
            return {r["name"] for r in cur.fetchall()}
    finally:
        conn.close()


def to_api_dict(row):
    """把 MySQL 行转成前端 normalizeDocument 期望的字段名。"""
    def _iso(value):
        return value.isoformat() if isinstance(value, datetime) else value

    return {
        "id": row["name"],
        "name": row["name"],
        "title": row["title"] or row["name"].rsplit(".", 1)[0],
        "extension": (row.get("extension") or "").upper(),
        "size": row.get("size") or 0,
        "chunk_count": row.get("chunk_count") or 0,
        "status": row.get("status") or STATUS_READY,
        "error_msg": row.get("error_msg") or "",
        "updated_at": _iso(row.get("updated_at")),
        "created_at": _iso(row.get("created_at")),
    }
