"""
阶段 5 验证脚本：Skills 渐进式技能 + RAG 工具接入 Agent
=====================================================
检查：
  1. SkillsMiddleware 能扫描到 4 个技能，并解析出 name / description
  2. list_skills / read_skill 工具返回正确内容，未知技能有兜底提示
  3. Agent 收到「方法对比」请求时自动走 list_skills → read_skill → 输出 Markdown 表格
  4. Agent 能调用 cv_rag_search 检索知识库
  5. Agent 实际装载的工具清单包含 gpu_status / cv_rag_search / list_skills / read_skill

用法：
    python tests/verify_stage5.py
"""
import os
import re
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.llm.skill_middleware import SkillsMiddleware
from sse_client import collect, parse

BASE = "http://localhost:8124/api"
USERNAME = "stage5_demo"
PASSWORD = "cv123456"


def tools_used(steps):
    """从 [STEP] 事件里解析出被调用的工具名序列。"""
    names = []
    for s in steps:
        m = re.match(r"工具:\s*(\S+)", s)
        if m:
            names.append(m.group(1))
    return names


def login():
    httpx.post(f"{BASE}/auth/register",
               json={"username": USERNAME, "nickname": "阶段5演示", "password": PASSWORD}, timeout=20)
    resp = httpx.post(f"{BASE}/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=20).json()
    return {"Authorization": f"Bearer {resp['data']['token']}"}


def new_session(headers):
    return httpx.post(f"{BASE}/session/create", headers=headers,
                      json={"chat_type": "agent"}, timeout=20).json()["data"]["session_id"]


def main() -> int:
    print("=" * 70)
    print("【1】SkillsMiddleware 扫描结果")
    print("=" * 70)
    mw = SkillsMiddleware(sources=[Config.SKILLS_DIR])
    names = mw.list_skill_names()
    print(f"  技能目录: {Config.SKILLS_DIR}")
    print(f"  发现 {len(names)} 个技能: {names}")
    for n in names:
        info = mw._skills[n]
        print(f"  - {n} ({len(info['body'])} 字): {info['description'][:60]}…")

    expected = {"paper_digest", "experiment_plan", "method_compare", "paper_review"}
    skills_ok = expected.issubset(set(names))

    print("\n" + "=" * 70)
    print("【2】list_skills / read_skill 工具输出")
    print("=" * 70)
    list_tool, read_tool = mw.get_tools()
    listing = list_tool.invoke({})
    print("  list_skills 返回:")
    print("   " + listing.replace("\n", "\n   ")[:330])
    body = read_tool.invoke({"skill_name": "method_compare"})
    print(f"\n  read_skill('method_compare') 长度: {len(body)} 字")
    print(f"  未知技能兜底: {read_tool.invoke({'skill_name': 'not_exist'})}")
    read_ok = "method_compare" in listing and "第 1 步" in body and "不存在" in read_tool.invoke({"skill_name": "nope"})

    headers = login()

    # ── 用例 A：技能自动路由 ──
    print("\n" + "=" * 70)
    print("【3】Agent 技能自动路由：请求「目标检测实时部署选型对比」")
    print("=" * 70)
    sid = new_session(headers)
    result = parse(collect(f"{BASE}/ai/cv_agent/chat",
                           {"message": "帮我把目标检测的主流方法做个对比矩阵，我要选一个做实时部署。",
                            "session_id": sid}))
    used = tools_used(result["step"])
    final = result["final"]
    print(f"  工具调用序列: {used}")
    print(f"  思考条数: {len(result['think'])} | 最终答案长度: {len(final)} 字 | 错误: {result['error']}")
    print("  ---- 最终答案前 900 字 ----")
    print(final[:900])
    print(f"  ... (共 {len(final)} 字)")

    routed = "list_skills" in used and "read_skill" in used
    table_cols = final.count("| :---")
    has_table = table_cols >= 1 and final.count("|") > 30

    # ── 用例 B：RAG 工具接入 ──
    print("\n" + "=" * 70)
    print("【4】Agent 调用 cv_rag_search 检索本地知识库")
    print("=" * 70)
    sid2 = new_session(headers)
    result2 = parse(collect(f"{BASE}/ai/cv_agent/chat",
                            {"message": "查一下知识库：Swin Transformer 的移动窗口机制是怎么实现的？",
                             "session_id": sid2}))
    used2 = tools_used(result2["step"])
    final2 = result2["final"]
    print(f"  工具调用序列: {used2}")
    print(f"  最终答案长度: {len(final2)} 字")
    print("  ---- 最终答案前 500 字 ----")
    print(final2[:500])
    print(f"  ... (共 {len(final2)} 字)")
    rag_ok = "cv_rag_search" in used2

    # ── 用例 C：工具清单 ──
    print("\n" + "=" * 70)
    print("【5】Agent 实际装载的工具清单")
    print("=" * 70)
    from app.routes.cv_agent import build_agent
    executor = build_agent()
    tool_names = [t.name for t in executor.tools]
    print(f"  {tool_names}")

    # ── 用例 D：落库内容是否完整（不是只存了首行） ──
    print("\n" + "=" * 70)
    print("【6】落库内容完整性（多行回答不应被截断）")
    print("=" * 70)
    msgs = httpx.get(f"{BASE}/session/{sid}/messages", headers=headers, timeout=20).json()["data"]
    stored = msgs[-1]["content"] if msgs else ""
    print(f"  落库 assistant 消息长度: {len(stored)} 字")
    print(f"  与流式输出长度差: {abs(len(stored) - len(final))} 字")
    store_ok = abs(len(stored) - len(final)) <= 5 and len(stored) > 500

    print("\n" + "=" * 70)
    print("阶段 5 结论")
    print("=" * 70)
    print(f"  4 个技能被发现          : {'OK' if skills_ok else 'FAIL'}")
    print(f"  list/read_skill 工具正确: {'OK' if read_ok else 'FAIL'}")
    print(f"  技能自动路由生效        : {'OK' if routed else 'FAIL'}  ({used})")
    print(f"  输出 Markdown 对比表格  : {'OK' if has_table else 'FAIL'}  ({table_cols} 列表头)")
    print(f"  Agent 调用 RAG 工具     : {'OK' if rag_ok else 'FAIL'}")
    print(f"  完整回答落库            : {'OK' if store_ok else 'FAIL'}")
    print(f"  工具清单含 gpu_status   : {'OK' if 'gpu_status' in tool_names else 'FAIL'}")
    print(f"  工具清单含技能工具      : {'OK' if {'list_skills', 'read_skill'} <= set(tool_names) else 'FAIL'}")

    ok = (skills_ok and read_ok and routed and has_table and rag_ok and store_ok
          and "cv_rag_search" in tool_names)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
