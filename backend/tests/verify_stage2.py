"""
阶段 2 验证脚本：Chain 模式（论文精读助手）+ Agent 模式（CV科研智能体）
=====================================================================
直接以 HTTP 客户端身份调用后端 SSE 接口，检查：
  1. Chain 模式逐 token 流式输出，且 user/assistant 消息都落库
  2. Agent 模式产出 [THINK] / [STEP] / [FINAL] 三类事件，且触发工具调用
  3. 多轮上下文生效（第二轮能引用第一轮内容）
  4. 自动标题、会话列表、历史回显

用法：
    python tests/verify_stage2.py
"""
import json
import sys

import httpx

BASE = "http://localhost:8124/api"
USERNAME = "stage2_demo"
PASSWORD = "cv123456"


def ensure_user() -> str:
    """注册（已存在则忽略）并登录，返回 token。"""
    httpx.post(f"{BASE}/auth/register",
               json={"username": USERNAME, "nickname": "阶段2演示", "password": PASSWORD},
               timeout=20)
    resp = httpx.post(f"{BASE}/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=20).json()
    if resp.get("code") != 0:
        raise SystemExit(f"登录失败: {resp}")
    return resp["data"]["token"]


def new_session(headers, chat_type) -> str:
    resp = httpx.post(f"{BASE}/session/create", headers=headers,
                      json={"chat_type": chat_type}, timeout=20).json()
    return resp["data"]["session_id"]


def stream_sse(url, params, limit_seconds=180):
    """消费 SSE 流，返回事件列表。"""
    events = []
    with httpx.stream("GET", url, params=params, timeout=httpx.Timeout(limit_seconds, read=limit_seconds)) as resp:
        if resp.status_code != 200:
            return [f"[HTTP {resp.status_code}]"]
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            events.append(payload)
            if payload == "[DONE]":
                break
    return events


def summarize(events):
    """把事件列表压缩成可读摘要。"""
    think = [e for e in events if e.startswith("[THINK]")]
    step = [e for e in events if e.startswith("[STEP]")]
    final = [e for e in events if e.startswith("[FINAL]")]
    err = [e for e in events if e.startswith("[ERROR]")]
    tokens = len([e for e in events if not e.startswith("[")])
    return think, step, final, err, tokens


def main():
    token = ensure_user()
    headers = {"Authorization": f"Bearer {token}"}

    # ── 1. Chain 模式：论文精读助手 ──
    print("=" * 70)
    print("【1】Chain 模式 —— 论文精读助手（逐 token 流式）")
    print("=" * 70)
    sid = new_session(headers, "doc")
    print(f"会话 ID: {sid}")

    events = stream_sse(f"{BASE}/ai/paper_reader/chat/sse",
                        {"message": "用三句话解释什么是感受野（receptive field），并给出计算公式。",
                         "session_id": sid})
    think, step, final, err, tokens = summarize(events)
    text = "".join(e for e in events if not e.startswith("["))
    print(f"事件总数: {len(events)} | token 块数: {tokens} | 错误: {len(err)}")
    print(f"输出字符数: {len(text)}")
    print("---- 输出前 400 字 ----")
    print(text[:400])
    if err:
        print("!! 错误事件:", err[:3])

    msgs = httpx.get(f"{BASE}/session/{sid}/messages", headers=headers, timeout=20).json()["data"]
    print(f"\n落库消息: {[(m['role'], m['msg_order'], len(m['content'])) for m in msgs]}")
    store_ok_1 = len(msgs) == 2 and msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"

    # ── 2. Chain 多轮上下文 ──
    print("\n" + "=" * 70)
    print("【2】Chain 多轮上下文（第二轮追问需引用第一轮）")
    print("=" * 70)
    events2 = stream_sse(f"{BASE}/ai/paper_reader/chat/sse",
                         {"message": "刚才你给我的公式里，k 和 s 分别代表什么？",
                          "session_id": sid})
    text2 = "".join(e for e in events2 if not e.startswith("["))
    print("---- 第二轮输出前 300 字 ----")
    print(text2[:300])

    # ── 3. Agent 模式：CV 科研智能体 ──
    print("\n" + "=" * 70)
    print("【3】Agent 模式 —— CV科研问答智能体（ReAct + 工具调用）")
    print("=" * 70)
    sid2 = new_session(headers, "agent")
    print(f"会话 ID: {sid2}")

    events3 = stream_sse(f"{BASE}/ai/cv_agent/chat",
                         {"message": "现在是几点？另外帮我算一下 ResNet-50 的 2048*7*7 是多少。",
                          "session_id": sid2})
    think, step, final, err, tokens = summarize(events3)
    print(f"THINK 事件: {len(think)} | STEP 事件: {len(step)} | FINAL 事件: {len(final)} | ERROR: {len(err)}")
    for e in think[:6]:
        print("  ", e[:160])
    for e in step[:6]:
        print("  ", e[:200])
    for e in final[:2]:
        print("  ", e[:300])
    if err:
        print("!! 错误事件:", err[:3])

    msgs2 = httpx.get(f"{BASE}/session/{sid2}/messages", headers=headers, timeout=20).json()["data"]
    print(f"\n落库消息: {[(m['role'], m['msg_order'], len(m['content'])) for m in msgs2]}")
    store_ok_2 = len(msgs2) == 2

    # ── 4. 会话列表与自动标题 ──
    print("\n" + "=" * 70)
    print("【4】会话列表与自动标题")
    print("=" * 70)
    for ct in ("doc", "agent"):
        rows = httpx.get(f"{BASE}/session/list", headers=headers,
                         params={"chat_type": ct}, timeout=20).json()["data"]
        for r in rows[:3]:
            print(f"  [{ct}] {r['session_id']}  {r['title'][:40]}")

    # ── 5. 错误路径 ──
    print("\n" + "=" * 70)
    print("【5】错误路径")
    print("=" * 70)
    r = httpx.get(f"{BASE}/ai/paper_reader/chat/sse", params={"message": ""}, timeout=20)
    print(f"  空 message → HTTP {r.status_code} (期望 400)")
    ok_empty = r.status_code == 400
    r = httpx.get(f"{BASE}/ai/cv_agent/chat", timeout=20)
    print(f"  缺 message → HTTP {r.status_code} (期望 400)")

    print("\n" + "=" * 70)
    print("阶段 2 结论")
    print("=" * 70)
    print(f"  Chain 流式输出        : {'OK' if tokens > 0 else 'FAIL'}（{tokens} 个 token 块）")
    print(f"  Chain 消息落库        : {'OK' if store_ok_1 else 'FAIL'}")
    print(f"  Agent 思考事件        : {'OK' if think else 'FAIL'}（{len(think)} 条）")
    print(f"  Agent 工具调用事件    : {'OK' if step else 'FAIL'}（{len(step)} 条）")
    print(f"  Agent 最终答案        : {'OK' if final else 'FAIL'}")
    print(f"  Agent 消息落库        : {'OK' if store_ok_2 else 'FAIL'}")
    print(f"  空消息校验            : {'OK' if ok_empty else 'FAIL'}")

    all_ok = bool(tokens > 0 and store_ok_1 and final and store_ok_2 and ok_empty)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
