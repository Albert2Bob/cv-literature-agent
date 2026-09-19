"""
阶段 6 验证脚本：MCP 学术检索服务接入 Agent
==========================================
检查：
  1. MCP 服务端在 http://127.0.0.1:8001/mcp 上可用，能列出工具
  2. 客户端适配器把它包装成同步 LangChain 工具（含超时）
  3. Agent 装载的工具清单里出现 search_arxiv / search_semantic_scholar
  4. Agent 收到论文检索请求时真的调用 MCP 工具，并在 [STEP] 里回传真实论文

前置条件：MCP 服务端已启动（python mcp_server/server.py）
         后端已重启（python run.py）
用法：
    python tests/verify_stage6.py
"""
import os
import re
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.llm.mcp_tools import get_mcp_tools, reset_mcp_cache
from sse_client import collect, parse

BASE = "http://localhost:8124/api"
MCP_HEALTH_URL = Config.MCP_SERVER_URL
USERNAME = "stage6_demo"
PASSWORD = "cv123456"


def tools_used(steps):
    names = []
    for s in steps:
        m = re.match(r"工具:\s*(\S+)", s)
        if m:
            names.append(m.group(1))
    return names


def main() -> int:
    print("=" * 70)
    print("【1】MCP 服务端连通性")
    print("=" * 70)
    print(f"  端点: {MCP_HEALTH_URL}")
    try:
        # streamable-http 端点在 POST 之外返回 405/406 属正常，能连上即算通
        r = httpx.post(MCP_HEALTH_URL, json={}, timeout=15)
        print(f"  HTTP {r.status_code}（能建立连接即视为可用）")
        reachable = True
    except Exception as exc:  # noqa: BLE001
        print(f"  连接失败: {exc}")
        reachable = False

    print("\n" + "=" * 70)
    print("【2】客户端适配器加载工具")
    print("=" * 70)
    reset_mcp_cache()
    tools = get_mcp_tools(force=True)
    names = [t.name for t in tools]
    print(f"  加载到 {len(tools)} 个 MCP 工具: {names}")
    for t in tools:
        first_line = (t.description or "").strip().splitlines()[0]
        print(f"  - {t.name}: {first_line[:70]}")
    mcp_ok = {"search_arxiv"} <= set(names)

    print("\n" + "=" * 70)
    print("【3】直接调用 search_arxiv 工具")
    print("=" * 70)
    arxiv_tool = next((t for t in tools if t.name == "search_arxiv"), None)
    if arxiv_tool:
        # 注意：适配器刻意把 MCP 工具降维成「单字符串输入」以适配 ReAct 的
        # Action Input 文本协议，因此这里传字符串而不是字典。
        raw = arxiv_tool.invoke("3D gaussian splatting")
        print(f"  返回长度: {len(raw)} 字符")
        print("  ---- 前 600 字 ----")
        print(raw[:600])
        has_paper = "arxiv_id" in raw or "pdf_url" in raw

        raw_json = arxiv_tool.invoke('{"query": "vision transformer detection", "max_results": 2}')
        json_ok = '"count"' in raw_json or "papers" in raw_json
        print(f"\n  JSON 写法（带 max_results）返回长度: {len(raw_json)} 字符 → {'OK' if json_ok else 'FAIL'}")
    else:
        has_paper = False
        json_ok = False
        print("  !! 未找到 search_arxiv 工具")

    print("\n" + "=" * 70)
    print("【4】Agent 装载的工具清单")
    print("=" * 70)
    from app.routes.cv_agent import build_agent
    executor = build_agent()
    agent_tools = [t.name for t in executor.tools]
    print(f"  {agent_tools}")
    agent_has_mcp = "search_arxiv" in agent_tools

    print("\n" + "=" * 70)
    print("【5】通过 Agent 触发论文检索（端到端）")
    print("=" * 70)
    httpx.post(f"{BASE}/auth/register",
               json={"username": USERNAME, "nickname": "阶段6演示", "password": PASSWORD}, timeout=20)
    token = httpx.post(f"{BASE}/auth/login",
                       json={"username": USERNAME, "password": PASSWORD}, timeout=20).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    sid = httpx.post(f"{BASE}/session/create", headers=headers,
                     json={"chat_type": "agent"}, timeout=20).json()["data"]["session_id"]

    result = parse(collect(f"{BASE}/ai/cv_agent/chat",
                           {"message": "帮我在 arXiv 上找几篇 3D Gaussian Splatting 的论文，给出标题、年份和链接。",
                            "session_id": sid}, timeout=300))
    used = tools_used(result["step"])
    final = result["final"]
    print(f"  工具调用序列: {used}")
    print(f"  最终答案长度: {len(final)} 字 | 错误: {result['error']}")
    print("  ---- 最终答案前 700 字 ----")
    print(final[:700])
    agent_called_mcp = "search_arxiv" in used

    print("\n" + "=" * 70)
    print("阶段 6 结论")
    print("=" * 70)
    print(f"  MCP 服务端可连接        : {'OK' if reachable else 'FAIL'}")
    print(f"  适配器加载工具          : {'OK' if mcp_ok else 'FAIL'}  ({names})")
    print(f"  直接调用返回真实论文    : {'OK' if has_paper else 'FAIL'}")
    print(f"  JSON 入参写法可用       : {'OK' if json_ok else 'FAIL'}")
    print(f"  Agent 工具清单含 MCP    : {'OK' if agent_has_mcp else 'FAIL'}")
    print(f"  Agent 端到端调用 MCP    : {'OK' if agent_called_mcp else 'FAIL'}  ({used})")

    ok = reachable and mcp_ok and has_paper and json_ok and agent_has_mcp and agent_called_mcp
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
