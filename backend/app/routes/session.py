"""
会话管理 API
============

接口清单：
    GET    /api/session/list?chat_type=doc|agent   会话列表
    POST   /api/session/create                     新建会话
    PUT    /api/session/rename                     重命名会话
    DELETE /api/session/<session_id>               删除会话
    GET    /api/session/<session_id>/messages      会话消息
"""
from flask import Blueprint, jsonify, request

from app.auth import login_required
from app.chat_history import (
    CHAT_TYPE_AGENT,
    CHAT_TYPE_DOC,
    VALID_CHAT_TYPES,
    create_session,
    delete_session,
    get_session_messages,
    get_user_sessions,
    rename_session,
)
from app.logging_conf import get_logger

session_bp = Blueprint("session", __name__, url_prefix="/api/session")

log = get_logger("routes.session")


def _iso(value):
    """datetime → ISO 字符串，None 安全。"""
    return value.isoformat() if value else None


@session_bp.route("/list", methods=["GET"])
@login_required
def list_sessions():
    """获取当前用户在指定模式下的会话列表。"""
    user_id = request.current_user["user_id"]
    chat_type = request.args.get("chat_type", CHAT_TYPE_DOC)
    if chat_type not in VALID_CHAT_TYPES:
        chat_type = CHAT_TYPE_DOC

    rows = get_user_sessions(user_id, chat_type)
    log.debug("会话列表: user=%s 模式=%s -> %d 条", user_id, chat_type, len(rows))
    return jsonify({
        "code": 0,
        "data": [
            {
                "session_id": r["session_id"],
                "title": r["title"],
                "chat_type": r["chat_type"],
                "created_at": _iso(r.get("created_at")),
                "updated_at": _iso(r.get("updated_at")),
            }
            for r in rows
        ],
    })


@session_bp.route("/create", methods=["POST"])
@login_required
def new_session():
    """创建新会话。"""
    user_id = request.current_user["user_id"]
    data = request.get_json(force=True, silent=True) or {}
    chat_type = data.get("chat_type", CHAT_TYPE_DOC)
    if chat_type not in VALID_CHAT_TYPES:
        return jsonify({"code": 400, "msg": f"chat_type 必须是 {VALID_CHAT_TYPES} 之一"}), 400

    session_id = create_session(user_id, chat_type, data.get("title"))
    log.success("新建会话: session=%s 模式=%s user=%s", session_id, chat_type, user_id)
    return jsonify({"code": 0, "msg": "创建成功", "data": {"session_id": session_id}}), 201


@session_bp.route("/rename", methods=["PUT"])
@login_required
def rename():
    """重命名会话。"""
    data = request.get_json(force=True, silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    title = (data.get("title") or "").strip()
    if not session_id or not title:
        return jsonify({"code": 400, "msg": "参数不完整"}), 400
    rename_session(session_id, title[:200])
    log.info("会话重命名: session=%s -> %r", session_id, title[:40])
    return jsonify({"code": 0, "msg": "更新成功"})


@session_bp.route("/<session_id>", methods=["DELETE"])
@login_required
def remove(session_id):
    """删除指定会话（含消息与摘要）。"""
    delete_session(session_id)
    log.success("会话已删除（含消息与摘要）: session=%s user=%s",
                session_id, request.current_user["user_id"])
    return jsonify({"code": 0, "msg": "删除成功"})


@session_bp.route("/<session_id>/messages", methods=["GET"])
@login_required
def messages(session_id):
    """获取指定会话的全部消息，用于前端历史回显。"""
    rows = get_session_messages(session_id)
    return jsonify({
        "code": 0,
        "data": [
            {
                "role": r["role"],
                "content": r["content"],
                "msg_order": r["msg_order"],
                "created_at": _iso(r.get("created_at")),
            }
            for r in rows
        ],
    })


@session_bp.route("/<session_id>/summary", methods=["GET"])
@login_required
def summary(session_id):
    """查看会话当前的持久化摘要（调试用）。"""
    from app.chat_history import load_summary
    return jsonify({"code": 0, "data": {"summary": load_summary(session_id)}})
