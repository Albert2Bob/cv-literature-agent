"""
RAG 文件管理 API
===============
对应前端 views/RagDocuments.vue 的调用约定（前缀 /api/rag/documents）：

    GET    /api/rag/documents                 文档列表
    POST   /api/rag/documents                 新建文档（JSON）
    POST   /api/rag/documents/upload          上传文件（multipart，字段名 file）
    GET    /api/rag/documents/<name>          单个文档（含全文）
    GET    /api/rag/documents/<name>/chunks   文档切片明细
    DELETE /api/rag/documents/<name>          删除文档

另外提供两个运维接口：
    POST   /api/rag/documents/<name>/refresh  按 MySQL 原文重建该文档索引
    POST   /api/rag/rebuild                   全量重建整个向量库

写操作完成后都会同步刷新「向量库 + MySQL 记录」，并返回最新的文档视图，
前端拿到响应即可直接刷新列表。

鉴权：文件管理会改动共享知识库，因此要求登录（与 session 接口一致）。
前端 Axios 拦截器会自动附带 Bearer Token。
"""
from flask import Blueprint, jsonify, request

from app import rag_manager, rag_store
from app.auth import login_required
from app.logging_conf import get_logger

log = get_logger("routes.rag")

rag_bp = Blueprint("rag", __name__, url_prefix="/api/rag")


# ── 统一响应 ──────────────────────────────────────────────────────────

def _ok(data=None, msg="ok", status=200):
    return jsonify({"code": 0, "msg": msg, "data": data}), status


def _fail(message, status=400):
    return jsonify({"code": status, "msg": message, "data": None}), status


def _handle(fn):
    """把 RAGError 转成规范响应，其他异常转 500。"""
    try:
        return fn()
    except rag_manager.RAGError as exc:
        # 业务异常：客户端可读信息走响应，服务端只记一行简洁日志
        log.warning("RAG 操作被拒绝(%s): %s", exc.status_code, exc.message)
        return _fail(exc.message, exc.status_code)
    except Exception as exc:  # noqa: BLE001
        log.error("RAG 接口未捕获异常: %s", exc, exc_info=True)
        return _fail(f"服务器内部错误：{exc}", 500)


def _owner_id():
    """当前登录用户 id（本路由已要求登录，正常不会为空）。"""
    return getattr(request, "current_user", {}).get("user_id")


# ── 列表 ──────────────────────────────────────────────────────────────

@rag_bp.route("/documents", methods=["GET"])
@login_required
def list_documents():
    """
    文档列表。

    返回结构同时满足前端两种取值方式（res.data.items 与 res.data 数组）：
        {"code":0, "data": {"items": [...], "total": N, "total_chunks": M}}
    前端 normalizeDocument 会读取 name/title/extension/size/chunk_count/updated_at。
    """
    def _run():
        rows = rag_store.list_documents()
        items = [rag_store.to_api_dict(r) for r in rows]
        stats = rag_store.count_documents()
        log.debug("文档列表查询: %d 个文档 / %d 个切片",
                  stats.get("docs", len(items)), stats.get("chunks", 0))
        return _ok({
            "items": items,
            "total": stats.get("docs", len(items)),
            "total_chunks": stats.get("chunks", 0),
        })
    return _handle(_run)


# ── 新建文档（JSON） ──────────────────────────────────────────────────

@rag_bp.route("/documents", methods=["POST"])
@login_required
def create_document():
    """
    新建或覆盖一份 Markdown/文本文档并立即索引。

    请求体：{"name": "notes.md", "title": "可选", "content": "..."}
    """
    def _run():
        payload = request.get_json(force=True, silent=True) or {}
        name = payload.get("name") or ""
        content = payload.get("content") or ""
        title = payload.get("title") or ""

        if not name.strip():
            return _fail("文档名称不能为空")
        if not content.strip():
            return _fail("文档内容不能为空")

        result = rag_manager.save_document(
            name=name,
            content=content,
            title=title,
            owner_id=_owner_id(),
        )
        msg = f"文档已覆盖并重新索引（{result['chunk_count']} 个切片）" if result.get("replaced") \
            else f"文档已创建并索引（{result['chunk_count']} 个切片）"
        return _ok(result, msg, 200 if result.get("replaced") else 201)
    return _handle(_run)


# ── 上传文件（multipart） ─────────────────────────────────────────────

@rag_bp.route("/documents/upload", methods=["POST"])
@login_required
def upload_document():
    """
    上传文件并立即解析、索引。

    前端用法：FormData，字段名 `file`。
    支持 .md/.markdown/.txt/.pdf/.docx/.doc
    """
    def _run():
        uploaded = request.files.get("file") or request.files.get("upload")
        if uploaded is None:
            log.warning("上传失败（请求中没有 file 字段）")
            return _fail("未收到上传文件（字段名应为 file）")
        if not uploaded.filename:
            log.warning("上传失败（文件缺少文件名）")
            return _fail("上传文件缺少文件名")

        raw = uploaded.read()
        log.info("收到文件上传: %s (%d 字节) 由用户 %s 发起",
                 uploaded.filename, len(raw), _owner_id())
        result = rag_manager.save_uploaded_file(
            filename=uploaded.filename,
            raw=raw,
            owner_id=_owner_id(),
        )
        msg = f"文件已覆盖并重新索引（{result['chunk_count']} 个切片）" if result.get("replaced") \
            else f"文件已上传并索引（{result['chunk_count']} 个切片）"
        return _ok(result, msg, 200 if result.get("replaced") else 201)
    return _handle(_run)


# ── 单文档 ────────────────────────────────────────────────────────────

@rag_bp.route("/documents/<path:name>", methods=["GET"])
@login_required
def get_document(name):
    """取单个文档（含全文，供前端「查看完整文档」弹窗）。"""
    def _run():
        safe = rag_store.normalize_name(name)
        row = rag_store.get_document(safe)
        if row is None:
            return _fail(f"文档不存在：{safe}", 404)
        data = rag_store.to_api_dict(row)
        data["content"] = row.get("content") or ""
        return _ok(data)
    return _handle(_run)


@rag_bp.route("/documents/<path:name>/chunks", methods=["GET"])
@login_required
def get_document_chunks(name):
    """取某个文档的切片明细（供前端「查看文档切片」弹窗）。"""
    def _run():
        safe = rag_store.normalize_name(name)
        if rag_store.get_document(safe) is None:
            return _fail(f"文档不存在：{safe}", 404)

        rows = rag_store.get_chunks(safe)
        items = [
            {
                "id": f"{safe}::{r['chunk_index']}",
                "index": r["chunk_index"],
                "content": r["content"],
                "length": r.get("char_count") or len(r["content"] or ""),
                "source": r.get("source") or safe,
                "section": r.get("section") or "",
            }
            for r in rows
        ]
        return _ok({"items": items, "total": len(items), "name": safe})
    return _handle(_run)


# ── 删除文档 ──────────────────────────────────────────────────────────

@rag_bp.route("/documents/<path:name>", methods=["DELETE"])
@login_required
def delete_document(name):
    """
    删除文档：先摘除向量库切片，再删 MySQL 记录（切片级联删除）。
    """
    def _run():
        result = rag_manager.delete_document(rag_store.normalize_name(name))
        return _ok(result, f"已删除 {result['name']}（移除 {result['removed_chunks']} 个切片）")
    return _handle(_run)


# ── 运维：单文档重建 / 全量重建 ───────────────────────────────────────

@rag_bp.route("/documents/<path:name>/refresh", methods=["POST"])
@login_required
def refresh_document(name):
    """按 MySQL 中保存的原文重新索引该文档（不触碰其他文档）。"""
    def _run():
        result = rag_manager.refresh_document(rag_store.normalize_name(name))
        return _ok(result, f"已重建 {result['name']} 的索引（{result['chunk_count']} 个切片）")
    return _handle(_run)


@rag_bp.route("/rebuild", methods=["POST"])
@login_required
def rebuild():
    """以 MySQL 记录为准，全量重建向量库。"""
    def _run():
        result = rag_manager.rebuild_all()
        return _ok(result, f"全量重建完成：{result['documents']} 个文档 / {result['chunks']} 个切片")
    return _handle(_run)

# ── 运维：一致性自检 ──────────────────────────────────────────────────

@rag_bp.route("/status", methods=["GET"])
@login_required
def status():
    """
    查看知识库状态：MySQL 记录数、向量库切片数、两边是否一致。
    便于排查「管理页面显示的切片数与实际检索不一致」这类问题。
    """
    def _run():
        from app.llm.rag import get_engine

        rows = rag_store.list_documents()
        mysql_names = {r["name"] for r in rows}
        engine = get_engine(verbose=False)
        engine_names = set(engine.source_names())

        only_mysql = sorted(mysql_names - engine_names)
        only_vector = sorted(engine_names - mysql_names)
        consistent = mysql_names == engine_names

        if consistent:
            log.debug("知识库一致性自检通过: %d 个文档 / %d 个切片",
                      len(mysql_names), engine.chunk_count())
        else:
            # 不一致是运维信号：说明 MySQL 与向量库脱节，需要 rebuild 或 refresh
            log.warning("知识库不一致: 仅 MySQL 有 %s；仅向量库有 %s",
                        only_mysql, only_vector)

        return _ok({
            "mysql_documents": len(mysql_names),
            "mysql_chunks": sum((r.get("chunk_count") or 0) for r in rows),
            "vector_documents": len(engine_names),
            "vector_chunks": engine.chunk_count(),
            "only_in_mysql": only_mysql,
            "only_in_vector": only_vector,
            "consistent": consistent,
        })
    return _handle(_run)
