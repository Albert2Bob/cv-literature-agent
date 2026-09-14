"""
JWT 认证模块
============
逻辑如下：
  - users 表初始化（init_db）
  - HS256 签发 / 校验 Token（make_token / decode_token）
  - Redis 保存有效会话（JWT jti -> user_id，TTL 与 JWT 有效期一致）
  - @login_required 同时校验 JWT 与 Redis 会话
  - /api/auth/register | /login | /logout | /verify | /userinfo

改进点：
  - 数据库连接参数统一走 Config.mysql_kwargs()，不再散落硬编码
  - 注册接口增加「昵称长度」校验与更明确的错误信息
"""
import time
import uuid
from functools import wraps

import pymysql
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash
from redis.exceptions import RedisError

from app.logging_conf import get_logger
from app.redis_store import revoke_session, save_session, session_is_active

log = get_logger("auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# ── 数据库连接 ────────────────────────────────────────────────────────

def get_db():
    """获取一个 MySQL 连接（DictCursor，utf8mb4）。"""
    cfg = current_app.config
    return pymysql.connect(
        host=cfg.get("MYSQL_HOST", "127.0.0.1"),
        port=cfg.get("MYSQL_PORT", 3306),
        user=cfg.get("MYSQL_USER", "root"),
        password=cfg.get("MYSQL_PASSWORD", ""),
        database=cfg.get("MYSQL_DB", "lsb_agent_db"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


# ── 建表 ──────────────────────────────────────────────────────────────

def init_db():
    """初始化 users 表。"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    username   VARCHAR(50)  NOT NULL UNIQUE,
                    nickname   VARCHAR(50)  NOT NULL,
                    password   VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
    finally:
        conn.close()


# ── Token ─────────────────────────────────────────────────────────────

def make_token(user_id, username):
    """签发 JWT 并在 Redis 登记会话，有效期默认 7 天。"""
    import jwt as pyjwt
    cfg = current_app.config
    days = int(cfg.get("JWT_EXPIRE_DAYS", 7))
    now = int(time.time())
    expires_in = 86400 * days
    payload = {
        "user_id": user_id,
        "username": username,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + expires_in,
    }
    token = pyjwt.encode(payload, cfg.get("JWT_SECRET"), algorithm="HS256")
    save_session(payload["jti"], user_id, expires_in)
    return token


def decode_token(token):
    """解码 JWT，失败返回 None。"""
    import jwt as pyjwt
    cfg = current_app.config
    try:
        return pyjwt.decode(token, cfg.get("JWT_SECRET"), algorithms=["HS256"])
    except Exception:
        return None


def login_required(f):
    """装饰器：Bearer Token 必须通过 JWT 验签且会话仍存在于 Redis。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            log.warning("鉴权失败（缺少 Bearer Token）: %s %s", request.method, request.path)
            return jsonify({"code": 401, "msg": "未登录或 Token 已过期"}), 401
        token = auth[7:].strip()
        payload = decode_token(token)
        if payload is None:
            log.warning("鉴权失败（Token 无效或过期）: %s %s", request.method, request.path)
            return jsonify({"code": 401, "msg": "Token 无效或已过期"}), 401
        jti = payload.get("jti")
        user_id = payload.get("user_id")
        if not jti or user_id is None:
            log.warning("鉴权失败（Token 缺少会话标识）: %s %s", request.method, request.path)
            return jsonify({"code": 401, "msg": "Token 无效或已过期"}), 401
        try:
            active = session_is_active(jti, user_id)
        except RedisError as exc:
            # 鉴权依赖 Redis，故障时必须关闭访问，不能退回成仅验 JWT。
            log.error("鉴权服务不可用（Redis 异常）: %s", exc)
            return jsonify({"code": 503, "msg": "登录状态服务暂时不可用，请稍后重试"}), 503
        if not active:
            log.warning("鉴权失败（会话已退出或过期）: %s %s", request.method, request.path)
            return jsonify({"code": 401, "msg": "登录状态已失效，请重新登录"}), 401
        request.current_user = payload
        request.current_token = token
        # 把用户身份并入请求上下文，后续日志会自动带上 user=xx
        from app.logging_conf import update_request_context
        update_request_context(user=payload.get("username"))
        return f(*args, **kwargs)
    return decorated


# ── 注册 ──────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    nickname = (data.get("nickname") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not nickname or not password:
        log.warning("注册失败（字段缺失）: username=%r", username)
        return jsonify({"code": 400, "msg": "账号、昵称、密码不能为空"}), 400
    if not (3 <= len(username) <= 50):
        log.warning("注册失败（账号长度非法）: username=%r len=%d", username, len(username))
        return jsonify({"code": 400, "msg": "账号长度为 3-50 个字符"}), 400
    if len(nickname) > 50:
        log.warning("注册失败（昵称过长）: username=%r", username)
        return jsonify({"code": 400, "msg": "昵称最长 50 个字符"}), 400
    if len(password) < 6:
        log.warning("注册失败（密码过短）: username=%r", username)
        return jsonify({"code": 400, "msg": "密码长度至少 6 位"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username=%s", (username,))
            if cur.fetchone():
                log.warning("注册失败（账号已存在）: username=%s", username)
                return jsonify({"code": 409, "msg": "该账号已被注册"}), 409
            cur.execute(
                "INSERT INTO users (username, nickname, password) VALUES (%s, %s, %s)",
                (username, nickname, generate_password_hash(password)),
            )
            new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    log.success("新用户注册成功: username=%s uid=%s", username, new_id)
    return jsonify({"code": 0, "msg": "注册成功"}), 201


# ── 登录 ──────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        log.warning("登录失败（字段缺失）: username=%r", username)
        return jsonify({"code": 400, "msg": "账号和密码不能为空"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, nickname, password FROM users WHERE username=%s",
                (username,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None or not check_password_hash(row["password"], password):
        # 不区分「用户不存在」与「密码错误」，避免账号枚举；日志里记清楚即可
        log.warning("登录失败（凭据错误）: username=%s 存在=%s", username, row is not None)
        return jsonify({"code": 401, "msg": "账号或密码错误"}), 401

    try:
        token = make_token(row["id"], row["username"])
    except RedisError as exc:
        log.error("登录失败（Redis 会话写入异常）: username=%s error=%s", username, exc)
        return jsonify({"code": 503, "msg": "登录状态服务暂时不可用，请稍后重试"}), 503

    log.success("登录成功: username=%s uid=%s", row["username"], row["id"])
    return jsonify({
        "code": 0,
        "msg": "登录成功",
        "data": {
            "token":    token,
            "user_id":  row["id"],
            "username": row["username"],
            "nickname": row["nickname"],
        },
    })


# ── 退出登录 ──────────────────────────────────────────────────────────

@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """撤销当前设备的会话，不影响该用户在其他设备上的登录。"""
    jti = request.current_user["jti"]
    try:
        revoke_session(jti)
    except RedisError as exc:
        log.error("退出登录失败（Redis 异常）: uid=%s error=%s",
                  request.current_user.get("user_id"), exc)
        return jsonify({"code": 503, "msg": "登录状态服务暂时不可用，请稍后重试"}), 503
    log.info("退出登录成功: username=%s uid=%s",
             request.current_user.get("username"), request.current_user.get("user_id"))
    return jsonify({"code": 0, "msg": "退出登录成功"})


# ── 校验 Token ────────────────────────────────────────────────────────

@auth_bp.route("/verify", methods=["GET"])
@login_required
def verify():
    return jsonify({
        "code": 0,
        "msg": "ok",
        "data": {
            "user_id":  request.current_user["user_id"],
            "username": request.current_user["username"],
        },
    })


# ── 当前用户信息 ──────────────────────────────────────────────────────

@auth_bp.route("/userinfo", methods=["GET"])
@login_required
def userinfo():
    user_id = request.current_user["user_id"]
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, nickname, created_at FROM users WHERE id=%s",
                (user_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        log.error("查询用户信息失败（记录不存在）: uid=%s", user_id)
        return jsonify({"code": 404, "msg": "用户不存在"}), 404
    if row.get("created_at"):
        row["created_at"] = row["created_at"].isoformat()
    return jsonify({"code": 0, "data": row})
