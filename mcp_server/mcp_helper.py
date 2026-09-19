"""
MCP 命令行助手（stdio 客户端）
=============================
用途：不启动 FastMCP 服务端，直接用官方 mcp 库以 stdio 方式
      拉起 server.py 并调用其工具，便于排查 MCP 工具本身的问题。

用法：
    python mcp_helper.py                          # 列出全部工具
    python mcp_helper.py search_arxiv '{"query": "3D gaussian splatting"}'
    python mcp_helper.py search_semantic_scholar '{"query": "vision transformer", "limit": 3}'
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=[SERVER], env=None)


async def list_tools():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"✅ 服务端共提供 {len(tools.tools)} 个工具：")
            for t in tools.tools:
                desc = (t.description or "").strip().split("\n")[0]
                print(f"  - {t.name}: {desc}")
            return tools


async def call_tool(name: str, arguments: dict):
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"🔧 调用工具 {name}，参数: {json.dumps(arguments, ensure_ascii=False)}")
            result = await session.call_tool(name, arguments)
            for block in result.content:
                text = getattr(block, "text", None)
                if text is not None:
                    try:
                        print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
                    except json.JSONDecodeError:
                        print(text)
            return result


def main():
    if len(sys.argv) == 1:
        asyncio.run(list_tools())
        return

    name = sys.argv[1]
    arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    asyncio.run(call_tool(name, arguments))


if __name__ == "__main__":
    main()
