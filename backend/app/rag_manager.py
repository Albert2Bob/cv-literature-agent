"""
RAG 文档管理器（编排层）
======================
把「文件 → 文本 → 切片 → 双写」这条链路收口到一个地方，供路由层调用。

  ┌─────────────┐   解析    ┌────────┐   切分    ┌────────┐
  │ 上传/新建文件 │ ───────▶ │ 纯文本  │ ───────▶ │ 切片列表 │
  └─────────────┘           └────────┘           └────────┘
                                                     │
                                          一次解析 → 两次保存
                                                     │
                        ┌────────────────────────────┴────────────────────────────┐
                        ▼                                                         ▼
             ① ChromaDB（切片向量）                                ② MySQL（文档元信息 + 切片原文）
                rag.engine.index_document()                          rag_store.upsert_document()
                                                                     rag_store.replace_chunks()

删除文档时反向执行：先从 Chroma 摘除该文档的全部向量，再删除 MySQL 记录（切片级联删除），
两步都完成后返回，保证「前端删除成功」与「后端两处存储」始终一致。

支持格式：
    .md / .markdown / .txt  → 直接按 UTF-8 读取（自动兼容 gbk）
    .pdf                    → pypdf 提取文本
    .docx / .doc            → python-docx 提取段落与表格文本
"""
import io
import os
import threading
import time

from app import rag_store
from app.llm.rag import (
    RAGEngine,
    get_engine,
    list_disk_documents,
    split_text,
)
from app.logging_conf import get_logger, shorten

log = get_logger("rag_manager")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024      # 单文件上限 20MB
MAX_TEXT_CHARS = 2_000_000               # 提取文本上限，防止超长文档拖垮切分

TEXT_EXTENSIONS = {"md", "markdown", "txt"}
PDF_EXTENSIONS = {"pdf"}
DOCX_EXTENSIONS = {"docx", "doc"}

# 首次启动同步只需做一次
_bootstrap_lock = threading.Lock()
_bootstrapped = False


class RAGError(Exception):
    """带用户可读信息的业务异常。"""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ==============================================================
#  文本提取
# ==============================================================

def _decode_text(raw: bytes) -> str:
    """字节流 → 文本，优先 UTF-8，失败后依次尝试 gbk / latin-1。"""
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text_from_pdf(raw: bytes) -> str:
    """用 pypdf 提取 PDF 文本。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RAGError("服务器缺少 pypdf 依赖，无法解析 PDF，请改用 .md/.txt 或先安装 pypdf", 500) from exc

    try:
        reader = PdfReader(io.BytesIO(raw))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                raise RAGError("PDF 已加密，无法解析")
        pages = []
        for i, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"## 第 {i} 页\n\n{text}")
        return "\n\n".join(pages)
    except RAGError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RAGError(f"PDF 解析失败：{exc}") from exc


def extract_text_from_docx(raw: bytes) -> str:
    """用 python-docx 提取 Word 段落与表格文本。"""
    try:
        import docx
    except ImportError as exc:
        raise RAGError("服务器缺少 python-docx 依赖，无法解析 Word，请改用 .md/.txt 或先安装 python-docx", 500) from exc

    try:
        document = docx.Document(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise RAGError(f"Word 解析失败：{exc}") from exc

    parts = []
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (getattr(getattr(para, "style", None), "name", "") or "").lower()
        # 标题样式转成 Markdown 标题，让后续按标题切分也能生效
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            parts.append("#" * min(int(level), 6) + " " + text)
        else:
            parts.append(text)

    for table in getattr(document, "tables", []) or []:
        rows = []
        for row in table.rows:
            cells = [(cell.text or "").strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        if rows:
            parts.append("\n".join(rows))

    return "\n\n".join(parts)


def extract_text(filename: str, raw: bytes) -> str:
    """
    按扩展名分派文本提取。返回纯文本（可能为空）。

    Raises:
        RAGError: 格式不支持 / 解析失败
    """
    ext = rag_store.get_extension(filename)

    if ext not in rag_store.SUPPORTED_EXTENSIONS:
        raise RAGError(
            f"不支持的文件格式 .{ext}；支持：{', '.join(sorted(rag_store.SUPPORTED_EXTENSIONS))}"
        )

    if ext in TEXT_EXTENSIONS:
        text = _decode_text(raw)
    elif ext in PDF_EXTENSIONS:
        text = extract_text_from_pdf(raw)
    elif ext in DOCX_EXTENSIONS:
        text = extract_text_from_docx(raw)
    else:
        raise RAGError(f"暂不支持解析 .{ext}")

    text = (text or "").strip()
    if not text:
        raise RAGError("文档解析后内容为空，可能是扫描版 PDF（图片型）或空文件")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def _derive_title(content: str, filename: str) -> str:
    """从内容的一级标题推断文档标题，取不到就用文件名（去扩展名）。"""
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:255]
    return filename.rsplit(".", 1)[0][:255]


# ==============================================================
#  核心：一次解析 → 两次保存
# ==============================================================

def _write_to_stores(name, title, ext, size, content, owner_id):
    """
    把一份文档写进两个存储：
      ① Chroma（向量）
      ② MySQL（元信息 + 切片原文）

    Returns:
        (chunk_count, engine)
    """
    engine = get_engine()

    # ① 向量库：切分并写入（同文档会先摘除旧切片，天然幂等）
    chunks = engine.index_document(name, content)

    # ② MySQL：文档元信息 + 切片明细
    rag_store.upsert_document(
        name=name,
        title=title or _derive_title(content, name),
        ext=ext,
        size=size,
        content=content,
        chunk_count=len(chunks),
        status=rag_store.STATUS_READY,
        owner_id=owner_id,
    )
    rag_store.replace_chunks(name, [
        {
            "index": i,
            "content": c.page_content,
            "source": c.metadata.get("source", name),
            "section": (c.metadata.get("问题标题") or c.metadata.get("文档标题") or "").strip(),
        }
        for i, c in enumerate(chunks)
    ])

    log.debug("双写完成: %s -> 向量 %d 条 / MySQL 元信息+切片 %d 条",
              name, len(chunks), len(chunks))
    return len(chunks), engine


def save_document(name, content, title=None, size=None, owner_id=None):
    """
    新建/覆盖一份文档（按文件名）。已存在则覆盖并重新索引。

    Returns:
        dict: 该文档的 API 视图（含 chunk_count）
    """
    name = rag_store.normalize_name(name)
    if not name:
        raise RAGError("文档名称不能为空")
    if not re_has_valid_extension(name):
        raise RAGError("文档名称需要包含扩展名，例如 notes.md")

    ext = rag_store.get_extension(name)
    if ext not in rag_store.SUPPORTED_EXTENSIONS:
        raise RAGError(f"不支持的文件格式 .{ext}")

    content = (content or "").strip()
    if not content:
        raise RAGError("文档内容不能为空")

    existed = rag_store.get_document(name) is not None

    try:
        chunk_count, _ = _write_to_stores(
            name=name,
            title=(title or "").strip() or _derive_title(content, name),
            ext=ext,
            size=size if size is not None else len(content.encode("utf-8")),
            content=content,
            owner_id=owner_id,
        )
    except RAGError:
        raise
    except Exception as exc:  # noqa: BLE001
        _record_failure(name, title, ext, size, content, owner_id, exc)
        log.error("文档索引失败: %s -> %s", name, exc, exc_info=True)
        raise RAGError(f"文档索引失败：{exc}", 500) from exc

    log.success("%s文档: %s（%d 个切片，%d 字）",
                "覆盖" if existed else "新建", name, chunk_count, len(content))
    row = rag_store.get_document(name)
    result = rag_store.to_api_dict(row)
    result["replaced"] = existed
    result["chunk_count"] = chunk_count
    return result


def save_uploaded_file(filename, raw, owner_id=None):
    """
    保存上传的文件：解析 → 双写。

    Returns:
        dict: 该文档的 API 视图
    """
    name = rag_store.normalize_name(filename)
    if not name:
        raise RAGError("文件名不能为空")
    if len(raw) == 0:
        raise RAGError("上传的文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise RAGError(f"文件超过上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")

    ext = rag_store.get_extension(name)
    existed = rag_store.get_document(name) is not None

    try:
        content = extract_text(name, raw)
    except RAGError as exc:
        _record_failure(name, name.rsplit(".", 1)[0], ext, len(raw), "", owner_id, exc)
        log.error("文件解析失败: %s (%d 字节, .%s) -> %s", name, len(raw), ext, exc.message)
        raise

    log.debug("文件解析成功: %s -> %d 字文本", name, len(content))

    try:
        chunk_count, _ = _write_to_stores(
            name=name,
            title=_derive_title(content, name),
            ext=ext,
            size=len(raw),
            content=content,
            owner_id=owner_id,
        )
    except RAGError:
        raise
    except Exception as exc:  # noqa: BLE001
        _record_failure(name, name.rsplit(".", 1)[0], ext, len(raw), content, owner_id, exc)
        log.error("文件索引失败: %s -> %s", name, exc, exc_info=True)
        raise RAGError(f"文件索引失败：{exc}", 500) from exc

    log.success("%s文件: %s（.%s，%d 字节 → %d 个切片）",
                "覆盖" if existed else "上传", name, ext, len(raw), chunk_count)
    row = rag_store.get_document(name)
    result = rag_store.to_api_dict(row)
    result["replaced"] = existed
    result["chunk_count"] = chunk_count
    return result


def delete_document(name):
    """
    删除文档：先从向量库摘除，再删 MySQL 记录。

    Returns:
        dict: {"name":..., "removed_chunks": N}
    """
    name = rag_store.normalize_name(name)
    row = rag_store.get_document(name)
    if row is None:
        raise RAGError(f"文档不存在：{name}", 404)

    # ① 向量库
    try:
        removed = get_engine().remove_document(name)
    except Exception as exc:  # noqa: BLE001
        log.error("删除向量失败: %s -> %s", name, exc, exc_info=True)
        raise RAGError(f"删除向量失败：{exc}", 500) from exc

    # ② MySQL（切片级联删除）
    rag_store.delete_document(name)

    log.success("文档已删除: %s（向量移除 %d 个切片，MySQL 记录与切片已清除）", name, removed)
    return {"name": name, "removed_chunks": removed}


def refresh_document(name):
    """
    用 MySQL 里存的原文重新索引单个文档。

    用途：向量库与 MySQL 不一致时修复某个文档，无需全量重建。
    """
    name = rag_store.normalize_name(name)
    row = rag_store.get_document(name)
    if row is None:
        raise RAGError(f"文档不存在：{name}", 404)
    if not row.get("content"):
        raise RAGError(f"文档 {name} 没有保存原文，无法重建索引", 400)

    chunk_count, _ = _write_to_stores(
        name=name,
        title=row.get("title") or "",
        ext=row.get("extension") or rag_store.get_extension(name),
        size=row.get("size") or 0,
        content=row["content"],
        owner_id=row.get("owner_id"),
    )
    result = rag_store.to_api_dict(rag_store.get_document(name))
    result["chunk_count"] = chunk_count
    return result


def rebuild_all():
    """
    全量重建：以 MySQL 记录为准，重新切分并重写整个向量库。

    适用场景：更换 embedding 模型、向量库损坏、维护页面上的「重建索引」按钮。
    """
    rows = rag_store.list_documents()
    payload = []
    for row in rows:
        full = rag_store.get_document(row["name"])
        if full and full.get("content"):
            payload.append({"name": full["name"], "content": full["content"]})

    engine = get_engine()
    total = engine.replace_from_documents(payload)

    # 回写每个文档的真实切片数，并同步切片明细表
    for item in payload:
        chunks = split_text(item["content"], source=item["name"])
        rag_store.replace_chunks(item["name"], [
            {
                "index": i,
                "content": c.page_content,
                "source": c.metadata.get("source", item["name"]),
                "section": (c.metadata.get("问题标题") or c.metadata.get("文档标题") or "").strip(),
            }
            for i, c in enumerate(chunks)
        ])
        rag_store.upsert_document(
            name=item["name"],
            title=(rag_store.get_document(item["name"]) or {}).get("title") or "",
            ext=rag_store.get_extension(item["name"]),
            size=len(item["content"].encode("utf-8")),
            content=item["content"],
            chunk_count=len(chunks),
            status=rag_store.STATUS_READY,
        )

    return {
        "documents": len(payload),
        "chunks": total,
        "skipped": len(rows) - len(payload),
    }


def _record_failure(name, title, ext, size, content, owner_id, exc):
    """
    索引失败时把失败原因记到已有文档上，方便前端看到 status=failed 与原因。

    注意：**只在文档本来就有记录时才写**。如果是一份全新的、被拒绝的文件
    （格式不支持、解析失败），不应该留下一条「幽灵记录」——否则它会出现在
    文档列表里但永远没有切片，也会让「MySQL 与向量库一致性」检查永远失败。
    """
    try:
        if rag_store.get_document(name) is None:
            return
        rag_store.upsert_document(
            name=name,
            title=title or name,
            ext=ext,
            size=size or 0,
            content=content or "",
            chunk_count=0,
            status=rag_store.STATUS_FAILED,
            error_msg=str(exc)[:500],
            owner_id=owner_id,
        )
    except Exception:  # noqa: BLE001 - 记录失败不应掩盖原始异常
        pass


# ==============================================================
#  启动同步
# ==============================================================

def ensure_knowledge_base(verbose=False) -> dict:
    """
    保证「MySQL 记录」与「Chroma 向量」一致。进程内只执行一次。

    三种情况：
      A. 向量库已建好（带索引标记）且 MySQL 有记录
         → 只把切片正文从 MySQL 载回内存，重建 BM25 与「文件→切片」映射。
           **不重算 embedding**，进程重启几乎瞬时完成。
      B. MySQL 有记录但向量库不可用（首次运行 / 换了 embedding 模型 / 库被删）
         → 全量重建一次向量库。
      C. MySQL 空但 documents/ 目录有 md
         → 首次初始化：把这些文件导入 MySQL 并建向量库。

    注意：绝不在「索引已有效」时删除集合——Flask debug 重载会起两个进程，
    其中一个删集合会让另一个进程手里的句柄失效（曾导致
    "Collection [...] does not exist" 错误）。
    """
    global _bootstrapped
    if _bootstrapped:
        return {"skipped": True}

    with _bootstrap_lock:
        if _bootstrapped:
            return {"skipped": True}

        engine = get_engine(verbose=verbose)
        rows = rag_store.list_documents()
        names = [r["name"] for r in rows]

        # ---- 情况 A：向量库有效 → 只恢复内存索引 ----
        if rows and engine.is_ready():
            pairs = []
            for name in names:
                chunks = rag_store.get_chunks(name)
                if chunks:
                    pairs.append((name, [c["content"] for c in chunks]))
            total = engine.load_from_pairs(pairs)
            _bootstrapped = True
            if verbose:
                log.info("复用已有向量库（无需重算 embedding）: %d 个文档 / %d 个切片",
                         len(pairs), total)
            return {"documents": len(pairs), "chunks": total, "source": "reuse"}

        # ---- 准备文档正文 ----
        payload = []
        for name in names:
            full = rag_store.get_document(name)
            if full and full.get("content"):
                payload.append({"name": name, "content": full["content"]})

        source = "mysql"
        if not payload:
            # ---- 情况 C：首次初始化，从 documents/ 导入 ----
            disk_docs = list_disk_documents()
            if disk_docs:
                source = "documents_dir"
                for d in disk_docs:
                    chunks = split_text(d["content"], source=d["name"])
                    rag_store.upsert_document(
                        name=d["name"], title=d["title"], ext=d["extension"],
                        size=d["size"], content=d["content"],
                        chunk_count=len(chunks), status=rag_store.STATUS_READY,
                    )
                    rag_store.replace_chunks(d["name"], [
                        {
                            "index": i,
                            "content": c.page_content,
                            "source": c.metadata.get("source", d["name"]),
                            "section": (c.metadata.get("问题标题") or c.metadata.get("文档标题") or "").strip(),
                        }
                        for i, c in enumerate(chunks)
                    ])
                payload = [{"name": d["name"], "content": d["content"]} for d in disk_docs]

        if not payload:
            _bootstrapped = True
            log.info("知识库为空：MySQL 无记录，documents/ 目录也没有 md 文件")
            return {"documents": 0, "chunks": 0, "source": "empty"}

        # ---- 情况 B：全量重建一次 ----
        log.warning("向量库不可用或不存在，开始全量重建（%d 个文档，需重算全部 embedding，请稍候）",
                    len(payload))
        started = time.perf_counter()
        total = engine.replace_from_documents(payload)
        _bootstrapped = True

        log.success("知识库构建完成（来源=%s）: %d 个文档 / %d 个切片，耗时 %.1fs",
                    source, len(payload), total, time.perf_counter() - started)
        return {"documents": len(payload), "chunks": total, "source": source}


def reset_bootstrap():
    """测试用：允许重新执行一次启动同步。"""
    global _bootstrapped
    _bootstrapped = False


def re_has_valid_extension(name: str) -> bool:
    """新建文档时要求带扩展名。"""
    return "." in name and len(name.rsplit(".", 1)[-1]) > 0
