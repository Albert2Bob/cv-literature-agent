"""JWT + Redis 登录态的独立单元测试（无需真实 MySQL/Redis）。"""
import os
import sys
import time
import unittest

import jwt
from flask import Flask, jsonify
from redis.exceptions import RedisError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth import auth_bp, login_required, make_token  # noqa: E402
from app.redis_store import revoke_session  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        existed = key in self.data
        self.data.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)


class UnavailableRedis(FakeRedis):
    def get(self, key):
        raise RedisError("connection unavailable")


class AuthRedisTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET="unit-test-secret-that-is-at-least-32-bytes",
            JWT_EXPIRE_DAYS=1,
            REDIS_TOKEN_PREFIX="test:auth:token:",
        )
        self.redis = FakeRedis()
        self.app.extensions["redis"] = self.redis
        self.app.register_blueprint(auth_bp)

        @self.app.route("/protected")
        @login_required
        def protected():
            from flask import request
            return jsonify({"user_id": request.current_user["user_id"]})

    def issue_token(self):
        with self.app.app_context():
            return make_token(7, "alice")

    def test_token_is_registered_with_matching_ttl(self):
        token = self.issue_token()
        payload = jwt.decode(token, self.app.config["JWT_SECRET"], algorithms=["HS256"])
        key = f"test:auth:token:{payload['jti']}"

        self.assertEqual(self.redis.data[key], "7")
        self.assertEqual(self.redis.ttls[key], 86400)
        self.assertNotIn(token, self.redis.data)
        self.assertGreater(payload["exp"], int(time.time()))

    def test_active_token_can_access_and_revoked_token_cannot(self):
        token = self.issue_token()
        headers = {"Authorization": f"Bearer {token}"}
        client = self.app.test_client()

        self.assertEqual(client.get("/protected", headers=headers).status_code, 200)
        payload = jwt.decode(token, self.app.config["JWT_SECRET"], algorithms=["HS256"])
        with self.app.app_context():
            self.assertTrue(revoke_session(payload["jti"]))
        self.assertEqual(client.get("/protected", headers=headers).status_code, 401)

    def test_logout_revokes_only_current_session(self):
        token_a = self.issue_token()
        token_b = self.issue_token()
        client = self.app.test_client()

        response = client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {token_a}"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            client.get("/protected", headers={"Authorization": f"Bearer {token_a}"}).status_code,
            401,
        )
        self.assertEqual(
            client.get("/protected", headers={"Authorization": f"Bearer {token_b}"}).status_code,
            200,
        )

    def test_legacy_jwt_without_jti_is_rejected(self):
        token = jwt.encode(
            {"user_id": 7, "username": "alice", "exp": int(time.time()) + 60},
            self.app.config["JWT_SECRET"],
            algorithm="HS256",
        )
        response = self.app.test_client().get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 401)

    def test_redis_failure_fails_closed_with_503(self):
        token = self.issue_token()
        self.app.extensions["redis"] = UnavailableRedis()
        response = self.app.test_client().get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
