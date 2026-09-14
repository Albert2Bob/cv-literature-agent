"""Redis 连接与登录会话存储。

Redis 只保存“当前仍有效”的会话 ID（JWT 的 jti），键本身带 TTL，因此
无需定时清理。JWT 仍由客户端携带，Redis 不保存完整 Token，避免泄露。
"""
from __future__ import annotations

from flask import current_app
from redis import Redis


def init_redis(app) -> Redis:
    """为 Flask 应用创建连接池，并挂到 app.extensions 供请求复用。"""
    client = Redis.from_url(
        app.config["REDIS_URL"],
        decode_responses=True,
        socket_connect_timeout=app.config["REDIS_CONNECT_TIMEOUT"],
        socket_timeout=app.config["REDIS_SOCKET_TIMEOUT"],
        health_check_interval=30,
    )
    app.extensions["redis"] = client
    return client


def get_redis() -> Redis:
    """取得当前应用的 Redis 客户端。"""
    client = current_app.extensions.get("redis")
    if client is None:
        raise RuntimeError("Redis 客户端尚未初始化")
    return client


def session_key(jti: str) -> str:
    """生成带环境前缀的会话键，避免多个应用共用 Redis 时冲突。"""
    prefix = current_app.config.get("REDIS_TOKEN_PREFIX", "lsb:auth:token:")
    return f"{prefix}{jti}"


def save_session(jti: str, user_id: int, ttl_seconds: int) -> None:
    """登记有效会话；Redis 会在 JWT 到期时同步清理该键。"""
    get_redis().set(session_key(jti), str(user_id), ex=ttl_seconds)


def session_is_active(jti: str, user_id: int) -> bool:
    """确认会话存在且确实属于 JWT 声明的用户。"""
    stored_user_id = get_redis().get(session_key(jti))
    return stored_user_id is not None and stored_user_id == str(user_id)


def revoke_session(jti: str) -> bool:
    """删除会话，使对应 JWT 即刻失效。"""
    return bool(get_redis().delete(session_key(jti)))
