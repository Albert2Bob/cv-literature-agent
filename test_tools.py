"""
工具触发测试脚本
================
用真实请求逐一验证 Agent 模式下 6 组工具是否被正确调用。

每组用例都设计成「必须调用某个工具才能答对」的形式，
判定依据是 SSE 流里的 [STEP] 事件（工具调用记录），而不是看回答内容。

用法：
    # 1) 确保后端已启动（端口 8124）
    # 2) 在 backend 目录下执行：
    python ..\test_tools.py

    # 只跑某一组（按组名过滤）
    python ..\test_tools.py calc
    python ..\test_tools.py --list
"""
import re
import sys
from pathlib import Path

import httpx

# 复用后端测试目录里严格按 SSE 规范分帧的客户端
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "tests"))
from sse_client import collect, parse  # noqa: E402

BASE = "http://localhost:8124/api"
USERNAME = "tool_tester"
PASSWORD = "cv123456"

# ============================================================
#  6 组测试用例
#  expected: 期望被调用的工具名（任一命中即算通过）
# ============================================================
CASES = [
    # ── 组 1：get_time ──
    ("get_time", "现在是几点？今天是星期几？", ["get_time"]),
    ("get_time", "帮我看一下当前系统时间，精确到秒。", ["get_time"]),

    # ── 组 2：calc ──
    ("calc", "帮我算一下 2048*7*7 等于多少？", ["calc"]),
    ("calc", "ResNet-50 的 backbone 输出是 2048×7×7，请算出总元素个数。", ["calc"]),
    ("calc", "计算 sqrt(224*224*3)，保留到整数。", ["calc"]),

    # ── 组 3：gpu_status ──
    ("gpu_status", "查一下我本机的 GPU 型号和显存占用情况。", ["gpu_status"]),
    ("gpu_status", "我想训一个 ViT-Base，先看看这台机器的显卡够不够用。", ["gpu_status"]),

    # ── 组 4：cv_rag_search（本地知识库）──
    ("cv_rag_search", "查一下知识库：Swin Transformer 的移动窗口机制是怎么实现的？", ["cv_rag_search"]),
    ("cv_rag_search", "从知识库里找一下 mAP50 和 mAP50-95 的区别。", ["cv_rag_search"]),
    ("cv_rag_search", "知识库里关于 Adam 和 AdamW 的区别是怎么写的？", ["cv_rag_search"]),

    # ── 组 5：search_arxiv（MCP，需先启动 MCP 服务端）──
    ("search_arxiv", "帮我在 arXiv 上找几篇 3D Gaussian Splatting 的论文。", ["search_arxiv"]),
    ("search_arxiv", "检索一下 arXiv 上最近的 vision transformer 目标检测工作。", ["search_arxiv"]),

    # ── 组 6：search_semantic_scholar（MCP，可能被限流）──
    ("search_semantic_scholar", "用 Semantic Scholar 查一下 vision transformer 的引用情况。",
     ["search_semantic_scholar"]),

    # ── 组 7：Skills（技能工具：list_skills → read_skill）──
    ("skills", "帮我把目标检测的主流方法做个对比矩阵，我要选一个做实时部署。", ["list_skills", "read_skill"]),
    ("skills", "帮我设计一下消融实验，我要验证新模块的贡献。", ["list_skills", "read_skill"]),
    ("skills", "这篇论文帮我模拟审稿意见：我们提出了一个轻量注意力模块，在 COCO 上 mAP 提升 1.2 个点。",
     ["list_skills", "read_skill"]),
    ("skills", "帮我给这篇论文写个精读报告：Swin Transformer 用移动窗口降低注意力复杂度。",
     ["list_skills", "read_skill"]),
]


def login() -> dict:
    httpx.post(f"{BASE}/auth/register",
               json={"username": USERNAME, "nickname": "工具测试", "password": PASSWORD}, timeout=20)
    resp = httpx.post(f"{BASE}/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=20).json()
    if resp.get("code") != 0:
        raise SystemExit(f"登录失败: {resp}")
    return {"Authorization": f"Bearer {resp['data']['token']}"}


def new_session(headers) -> str:
    return httpx.post(f"{BASE}/session/create", headers=headers,
                      json={"chat_type": "agent"}, timeout=20).json()["data"]["session_id"]


def tools_used(steps):
    """从 [STEP] 事件解析被调用的工具名（保持顺序）。"""
    names = []
    for s in steps:
        m = re.match(r"工具:\s*(\S+)", s)
        if m:
            names.append(m.group(1))
    return names


def main() -> int:
    if "--list" in sys.argv:
        groups = {}
        for g, q, _ in CASES:
            groups.setdefault(g, []).append(q)
        for g, qs in groups.items():
            print(f"\n【{g}】")
            for q in qs:
                print(f"  - {q}")
        return 0

    filt = [a for a in sys.argv[1:] if not a.startswith("--")]
    cases = [c for c in CASES if not filt or any(f in c[0] for f in filt)]

    headers = login()
    print("=" * 78)
    print(f"  工具触发测试 —— 共 {len(cases)} 个用例")
    print("=" * 78)

    passed = 0
    for i, (group, question, expected) in enumerate(cases, 1):
        sid = new_session(headers)
        try:
            result = parse(collect(f"{BASE}/ai/cv_agent/chat",
                                   {"message": question, "session_id": sid}, timeout=300))
        except Exception as exc:  # noqa: BLE001
            print(f"\n[{i}/{len(cases)}] 【{group}】异常: {exc}")
            continue

        used = tools_used(result["step"])
        ok = any(e in used for e in expected)
        passed += int(ok)

        print(f"\n[{i}/{len(cases)}] {'✅ 通过' if ok else '❌ 未触发'}  【{group}】")
        print(f"  提问  : {question}")
        print(f"  期望  : {expected}")
        print(f"  实际  : {used if used else '(未调用任何工具)'}")
        if result["error"]:
            print(f"  错误  : {result['error'][:200]}")
        # 打印首个工具调用的观察结果片段，便于确认工具真的返回了数据
        for s in result["step"][:2]:
            print(f"  观察  : {s[:220].replace(chr(10), ' ')}")
        print(f"  回答  : {result['final'][:150].replace(chr(10), ' ')}...")

    print("\n" + "=" * 78)
    print(f"  结果：{passed}/{len(cases)} 个用例成功触发了期望工具")
    print("=" * 78)
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
