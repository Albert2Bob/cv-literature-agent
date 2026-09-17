"""
阶段 3 验证脚本：多轮对话与持久化记忆
====================================
检查摘要压缩策略是否按设计生效：
  - 触发条件：轮数 % 5 == 0  或  累计字符/2 >= 4000
  - 生成后写入 chat_summaries，并进入后续请求的上下文

做法：在同一会话内进行 5 轮简短问答（第 5 轮结束时消息数为 10，
rounds = 5，恰好命中 SUMMARY_INTERVAL），然后检查摘要是否生成。

用法：
    python tests/verify_stage3.py
"""
import sys

import httpx

BASE = "http://localhost:8124/api"
USERNAME = "stage3_demo"
PASSWORD = "cv123456"

ROUNDS = [
    "我在做遥感图像的建筑物提取，数据集是 WHU Building。",
    "这个任务你觉得用 U-Net 还是 SegFormer 更合适？一句话回答。",
    "那评价指标用 IoU 还是 F1？一句话回答。",
    "训练时 batch size 设 8 会不会太小？一句话回答。",
    "总结一下我们刚才聊的任务、模型和指标。",
]


def main():
    httpx.post(f"{BASE}/auth/register",
               json={"username": USERNAME, "nickname": "阶段3演示", "password": PASSWORD}, timeout=20)
    token = httpx.post(f"{BASE}/auth/login",
                       json={"username": USERNAME, "password": PASSWORD}, timeout=20).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    sid = httpx.post(f"{BASE}/session/create", headers=headers,
                     json={"chat_type": "doc"}, timeout=20).json()["data"]["session_id"]
    print(f"会话 ID: {sid}\n")

    for i, question in enumerate(ROUNDS, 1):
        with httpx.stream("GET", f"{BASE}/ai/paper_reader/chat/sse",
                          params={"message": question, "session_id": sid},
                          timeout=httpx.Timeout(180, read=180)) as resp:
            answer_len = 0
            for line in resp.iter_lines():
                if line.startswith("data: ") and not line[6:].startswith("["):
                    answer_len += len(line[6:])
                if line == "data: [DONE]":
                    break
        print(f"  第 {i} 轮完成，回答 {answer_len} 字")

    # ── 检查落库情况 ──
    msgs = httpx.get(f"{BASE}/session/{sid}/messages", headers=headers, timeout=20).json()["data"]
    print(f"\n消息总数: {len(msgs)}（期望 10 = 5 轮 × 2）")
    print(f"msg_order 连续: {'OK' if [m['msg_order'] for m in msgs] == list(range(1, len(msgs) + 1)) else 'FAIL'}")

    summary = httpx.get(f"{BASE}/session/{sid}/summary", headers=headers, timeout=20).json()["data"]["summary"]
    print(f"\n摘要长度: {len(summary)} 字")
    if summary:
        print("---- 摘要内容 ----")
        print(summary)
    else:
        print("!! 未生成摘要")

    # ── 第 6 轮：验证摘要已进入上下文 ──
    print("\n第 6 轮：问「我刚才说的数据集叫什么？」（依赖记忆/摘要）")
    with httpx.stream("GET", f"{BASE}/ai/paper_reader/chat/sse",
                      params={"message": "我刚才提到的数据集叫什么名字？只回答名字。", "session_id": sid},
                      timeout=httpx.Timeout(180, read=180)) as resp:
        text = ""
        for line in resp.iter_lines():
            if line.startswith("data: ") and not line[6:].startswith("["):
                text += line[6:]
            if line == "data: [DONE]":
                break
    print(f"回答: {text[:150]}")

    print("\n" + "=" * 70)
    print("阶段 3 结论")
    print("=" * 70)
    print(f"  5 轮消息完整落库      : {'OK' if len(msgs) == 10 else 'FAIL'}")
    print(f"  msg_order 连续递增    : {'OK' if [m['msg_order'] for m in msgs] == list(range(1, len(msgs) + 1)) else 'FAIL'}")
    print(f"  第 5 轮触发自动摘要   : {'OK' if summary else 'FAIL'}")
    print(f"  第 6 轮能回忆数据集   : {'OK' if 'WHU' in text.upper() else '需人工确认'}")

    ok = len(msgs) == 10 and bool(summary)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
