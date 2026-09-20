"""
阶段 8 验证脚本：端到端集成回归
==============================
覆盖前几个阶段未覆盖的集成场景：
  1. 健康检查与配置自检
  2. 会话数据隔离：A 用户看不到 B 用户的会话
  3. 鉴权：所有 /api/session/* 接口在无 token / 坏 token 下必须 401
  4. 并发：同一用户两个会话同时请求，消息不串号、msg_order 连续
  5. 完整链路：新建会话 → Chain 提问 → 落库 → 历史回显 → 重命名 → 删除
  6. 边界：空 message、超长 message、不存在的 session_id、非法 chat_type

用法：
    python tests/verify_stage8.py
"""
import os
import sys
import threading

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sse_client import collect, parse

BASE = "http://localhost:8124/api"
PASSWORD = "cv123456"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def ensure_user(username, nickname):
    httpx.post(f"{BASE}/auth/register",
               json={"username": username, "nickname": nickname, "password": PASSWORD}, timeout=20)
    resp = httpx.post(f"{BASE}/auth/login",
                      json={"username": username, "password": PASSWORD}, timeout=20).json()
    return {"Authorization": f"Bearer {resp['data']['token']}"}


def new_session(headers, chat_type):
    return httpx.post(f"{BASE}/session/create", headers=headers,
                      json={"chat_type": chat_type}, timeout=20).json()["data"]["session_id"]


def main() -> int:
    print("=" * 70)
    print("【1】健康检查与配置")
    print("=" * 70)
    health = httpx.get(f"{BASE}/health", timeout=20).json()
    print(f"  {health}")
    check("健康检查返回 ok", health.get("status") == "ok")
    check("两种模式已注册", set(health.get("modes", {})) == {"chain", "agent"})

    print("\n" + "=" * 70)
    print("【2】鉴权保护")
    print("=" * 70)
    bad = {"Authorization": "Bearer not-a-real-token"}
    cases = [
        ("GET", "/session/list", None, "会话列表"),
        ("POST", "/session/create", {"chat_type": "doc"}, "新建会话"),
        ("PUT", "/session/rename", {"session_id": "x", "title": "y"}, "重命名"),
        ("DELETE", "/session/abc", None, "删除会话"),
        ("GET", "/session/abc/messages", None, "会话消息"),
        ("GET", "/auth/userinfo", None, "用户信息"),
    ]
    for method, path, body, label in cases:
        r1 = httpx.request(method, BASE + path, json=body, timeout=20)
        r2 = httpx.request(method, BASE + path, json=body, headers=bad, timeout=20)
        check(f"{label} 无 token → 401", r1.status_code == 401, f"实际 {r1.status_code}")
        check(f"{label} 坏 token → 401", r2.status_code == 401, f"实际 {r2.status_code}")

    print("\n" + "=" * 70)
    print("【3】用户数据隔离")
    print("=" * 70)
    ha = ensure_user("stage8_alice", "隔离测试A")
    hb = ensure_user("stage8_bob", "隔离测试B")

    sid_a = new_session(ha, "doc")
    sid_b = new_session(hb, "doc")

    list_a = {s["session_id"] for s in httpx.get(f"{BASE}/session/list", headers=ha,
                                                 params={"chat_type": "doc"}, timeout=20).json()["data"]}
    list_b = {s["session_id"] for s in httpx.get(f"{BASE}/session/list", headers=hb,
                                                 params={"chat_type": "doc"}, timeout=20).json()["data"]}
    check("A 的列表含自己的会话", sid_a in list_a)
    check("A 的列表不含 B 的会话", sid_b not in list_a)
    check("B 的列表含自己的会话", sid_b in list_b)
    check("B 的列表不含 A 的会话", sid_a not in list_b)
    # 清理 B 的会话，避免累积
    httpx.delete(f"{BASE}/session/{sid_b}", headers=hb, timeout=20)

    print("\n" + "=" * 70)
    print("【4】chain_type 与参数校验")
    print("=" * 70)
    r = httpx.post(f"{BASE}/session/create", headers=ha,
                   json={"chat_type": "不存在的模式"}, timeout=20)
    check("非法 chat_type → 400", r.status_code == 400, f"实际 {r.status_code}")

    r = httpx.get(f"{BASE}/ai/paper_reader/chat/sse", params={"message": "  "}, timeout=20)
    check("Chain 空 message（纯空格）→ 400", r.status_code == 400, f"实际 {r.status_code}")

    # 三种「空输入」都要被拒绝：完全不传 / 传空串 / 只传空格
    r = httpx.get(f"{BASE}/ai/cv_agent/chat", timeout=60)
    check("Agent 完全不传 message → 400", r.status_code == 400, f"实际 {r.status_code}")

    r = httpx.get(f"{BASE}/ai/cv_agent/chat", params={"message": ""}, timeout=60)
    check("Agent 传空 message → 400", r.status_code == 400, f"实际 {r.status_code}")

    r = httpx.get(f"{BASE}/ai/cv_agent/chat", params={"message": "   "}, timeout=60)
    check("Agent 只传空格 → 400", r.status_code == 400, f"实际 {r.status_code}")

    r = httpx.get(f"{BASE}/session/不存在的会话/messages", headers=ha, timeout=20)
    check("不存在的 session_id → 空列表而非报错",
          r.status_code == 200 and r.json()["data"] == [], f"实际 {r.status_code}")

    print("\n" + "=" * 70)
    print("【5】并发：两个会话同时提问，消息不串号")
    print("=" * 70)
    sid1 = new_session(ha, "doc")
    sid2 = new_session(ha, "doc")
    errors = []

    def ask(sid, question):
        try:
            res = parse(collect(f"{BASE}/ai/paper_reader/chat/sse",
                                {"message": question, "session_id": sid}, timeout=240),
                        mode="chain")
            if not res["final"]:
                errors.append(f"{sid} 无输出")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sid} 异常: {exc}")

    t1 = threading.Thread(target=ask, args=(sid1, "一句话解释什么是卷积。"))
    t2 = threading.Thread(target=ask, args=(sid2, "一句话解释什么是池化。"))
    t1.start(); t2.start(); t1.join(); t2.join()

    check("并发请求无异常", not errors, "; ".join(errors))

    m1 = httpx.get(f"{BASE}/session/{sid1}/messages", headers=ha, timeout=20).json()["data"]
    m2 = httpx.get(f"{BASE}/session/{sid2}/messages", headers=ha, timeout=20).json()["data"]
    check("会话1 恰好 2 条消息（user+assistant）", len(m1) == 2, f"实际 {len(m1)}")
    check("会话2 恰好 2 条消息（user+assistant）", len(m2) == 2, f"实际 {len(m2)}")
    check("会话1 msg_order 连续为 [1,2]",
          [m["msg_order"] for m in m1] == [1, 2], f"实际 {[m['msg_order'] for m in m1]}")
    check("会话2 msg_order 连续为 [1,2]",
          [m["msg_order"] for m in m2] == [1, 2], f"实际 {[m['msg_order'] for m in m2]}")
    if m1 and m2:
        check("两会话内容未串（问题不同）",
              m1[0]["content"] != m2[0]["content"],
              f"会话1 问题: {m1[0]['content'][:20]}")

    print("\n" + "=" * 70)
    print("【6】完整链路：新建 → 提问 → 落库 → 回显 → 重命名 → 删除")
    print("=" * 70)
    sid = new_session(ha, "doc")
    print(f"  会话 ID: {sid}")

    res = parse(collect(f"{BASE}/ai/paper_reader/chat/sse",
                        {"message": "用一句话说明什么是感受野。", "session_id": sid}, timeout=240),
                mode="chain")
    check("Chain 有流式输出", bool(res["final"]), f"{len(res['final'])} 字")
    check("Chain 无错误事件", not res["error"], "; ".join(res["error"]))

    msgs = httpx.get(f"{BASE}/session/{sid}/messages", headers=ha, timeout=20).json()["data"]
    check("历史回显返回 2 条消息", len(msgs) == 2, f"实际 {len(msgs)}")
    check("角色顺序为 user → assistant",
          [m["role"] for m in msgs] == ["user", "assistant"], str([m["role"] for m in msgs]))
    check("落库内容与流式输出一致",
          msgs and abs(len(msgs[-1]["content"]) - len(res["final"])) <= 5,
          f"落库 {len(msgs[-1]['content'])} 字 vs 流式 {len(res['final'])} 字")

    title = httpx.get(f"{BASE}/session/list", headers=ha,
                      params={"chat_type": "doc"}, timeout=20).json()["data"]
    mine = next((s for s in title if s["session_id"] == sid), None)
    check("会话按首条消息自动命名",
          bool(mine) and mine["title"] != "新对话",
          f"标题: {mine['title'][:30] if mine else '未找到'}")

    r = httpx.put(f"{BASE}/session/rename", headers=ha,
                  json={"session_id": sid, "title": "感受野专题"}, timeout=20)
    check("重命名成功", r.status_code == 200 and r.json()["code"] == 0)
    title2 = httpx.get(f"{BASE}/session/list", headers=ha,
                       params={"chat_type": "doc"}, timeout=20).json()["data"]
    check("重命名已生效",
          any(s["session_id"] == sid and s["title"] == "感受野专题" for s in title2))

    r = httpx.delete(f"{BASE}/session/{sid}", headers=ha, timeout=20)
    check("删除成功", r.status_code == 200)
    after = httpx.get(f"{BASE}/session/list", headers=ha,
                      params={"chat_type": "doc"}, timeout=20).json()["data"]
    check("删除后列表不含该会话", all(s["session_id"] != sid for s in after))
    left = httpx.get(f"{BASE}/session/{sid}/messages", headers=ha, timeout=20).json()["data"]
    check("删除后消息已级联清零", left == [], f"实际 {len(left)} 条")

    print("\n" + "=" * 70)
    print("【7】超长输入")
    print("=" * 70)
    long_msg = "请用一句话回答：" + "感受野" * 300
    r = httpx.get(f"{BASE}/ai/paper_reader/chat/sse",
                  params={"message": long_msg}, timeout=240)
    check("超长 message（无 session）返回 200", r.status_code == 200, f"实际 {r.status_code}")
    res_long = parse(collect(f"{BASE}/ai/paper_reader/chat/sse",
                             {"message": long_msg}, timeout=240), mode="chain")
    check("超长输入仍能产出回答", bool(res_long["final"]), f"{len(res_long['final'])} 字")

    # ---- 汇总 ----
    print("\n" + "=" * 70)
    print("阶段 8 结论")
    print("=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL: {name}  {detail}")
    print(f"  通过 {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
