"""
MCP 工具适配器（客户端）
======================

职责：把 MCP 服务端（mcp_server，学术论文检索）暴露的**异步**工具，
包装成 LangChain ReAct Agent 可以直接调用的**同步**工具。

━━━ 关键问题与解法 ━━━
ReAct Agent 的工具调用格式是纯文本三行：
    Thought: ...
    Action: search_arxiv
    Action Input: 3D gaussian splatting
也就是说 **Action Input 永远是一个字符串**。

而 MCP 工具的 args_schema 是 JSON Schema（多参数对象），LangChain 会因此报错：
    ValueError: String tool inputs are not allowed when using tools with JSON schema args_schema.

检索工具有 query / max_results / sort_by 多个参数，必须处理。

解法：把每个 MCP 工具**降维**成「单字符串输入」工具——
  - schema 改为 {"input": str}
  - description 里明确写出支持的参数格式（JSON 或纯查询词）
  - 调用时把字符串解析回参数字典，再转交原始 MCP 工具

这样既保住了 MCP 的完整参数能力，又能被 ReAct 的文本协议正常调用。

其他改进：
  1. 连接失败不再永久缓存失败状态——每 RETRY_INTERVAL 秒允许重试一次，
     先启动后端、后启动 MCP 服务端也能自动恢复。
  2. MCP 服务地址从 Config.MCP_SERVER_URL 读取，不再硬编码。
  3. 返回文本做长度裁剪，避免超长 JSON 塞爆上下文。
"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, Field

from app.config import Config
from app.logging_conf import get_logger, shorten

log = get_logger("llm.mcp")

MCP_CALL_TIMEOUT = 30.0     # 单次工具调用超时（秒）
MCP_LOAD_TIMEOUT = 20.0     # 拉取工具列表超时（秒）
RETRY_INTERVAL = 30.0       # 上次失败后，多久允许再次尝试连接
MAX_RESULT_CHARS = 4000     # 单个工具返回文本的最大长度


class McpStringInput(BaseModel):
    """
    所有 MCP 工具统一使用「单字符串输入」schema。

    原因：ReAct Agent 的 `Action Input` 只能是字符串，若工具声明为多参数
    JSON Schema，LangChain 会抛出
    "String tool inputs are not allowed when using tools with JSON schema args_schema."
    详见本文件顶部说明。
    """
    input: str = Field(
        description='查询内容：可直接填查询词，或填 JSON，例如 {"query": "...", "max_results": 3}'
    )


# ==============================================================
#  1. 参数规格：从 MCP 工具的 JSON Schema 提取参数名与说明
# ==============================================================

_JSON_TYPE_NAMES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def _describe_tool_args(raw_tool) -> tuple:
    """
    读取 MCP 工具的 args_schema，返回 (参数名列表, 人类可读说明, 参数名->类型)。

    langchain-mcp-adapters 不同版本暴露的 args_schema 形态不同：
      - 有的版本是 pydantic 模型（有 model_fields / __fields__）
      - 有的是 **JSON Schema 字典**（{"type": "object", "properties": {...}}）
    两种都要支持，否则参数名解析为空，就会退化成 {"input": ...} 而调用失败。
    """
    schema = getattr(raw_tool, "args_schema", None)
    if schema is None:
        return [], "（无参数）", {}

    names: List[str] = []
    type_map: Dict[str, str] = {}
    lines: List[str] = []

    # ---------- 形态 A：JSON Schema 字典 ----------
    if isinstance(schema, dict):
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        for name, spec in properties.items():
            spec = spec or {}
            names.append(name)
            json_type = spec.get("type", "string")
            type_name = _JSON_TYPE_NAMES.get(json_type, json_type)
            type_map[name] = type_name

            detail = f"  - {name} ({type_name}{'' if name in required else '，可选'})"
            description = (spec.get("description") or "").strip().replace("\n", " ")
            if description:
                detail += f"：{description}"
            if "default" in spec:
                detail += f"（默认 {spec['default']!r}）"
            lines.append(detail)
        return names, "\n".join(lines) if lines else "（无参数）", type_map

    # ---------- 形态 B：pydantic 模型 ----------
    fields: Dict[str, Any] = {}
    if hasattr(schema, "model_fields"):          # pydantic v2
        fields = dict(schema.model_fields)
    elif hasattr(schema, "__fields__"):          # pydantic v1
        fields = dict(schema.__fields__)

    for name, field in fields.items():
        names.append(name)
        annotation = getattr(field, "annotation", None)
        field_type = getattr(annotation, "__name__", str(annotation))
        type_map[name] = field_type

        description = getattr(field, "description", None) or ""
        default = getattr(field, "default", None)
        required = default is None or str(default) in ("PydanticUndefined", "Ellipsis")

        detail = f"  - {name} ({field_type}{'' if required else '，可选'})"
        if description:
            detail += f"：{description}"
        lines.append(detail)

    return names, "\n".join(lines) if lines else "（无参数）", type_map


def _extract_query_hint(raw_tool, arg_names: List[str]) -> Optional[str]:
    """给单字符串输入挑一个「默认参数名」（优先 query / input / keyword）。"""
    for candidate in ("query", "input", "keyword", "keywords", "q"):
        if candidate in arg_names:
            return candidate
    return arg_names[0] if arg_names else None


def _coerce_value(value: Any, type_name: str) -> Any:
    """把字符串参数按目标类型转换。"""
    if not isinstance(value, str):
        return value
    if type_name in ("int", "integer"):
        try:
            return int(value)
        except ValueError:
            return value
    if type_name in ("float", "number"):
        try:
            return float(value)
        except ValueError:
            return value
    if type_name in ("bool", "boolean"):
        return value.strip().lower() in ("1", "true", "yes", "y", "是")
    return value


def _parse_action_input(text: str, arg_names: List[str], type_map: Dict[str, str],
                        query_hint: Optional[str]) -> Dict[str, Any]:
    """
    把 ReAct 传来的字符串转成 MCP 工具需要的参数字典。

    支持两种写法：
      1. 纯查询词：  3D gaussian splatting
         → {query: "3D gaussian splatting"}
      2. JSON 对象： {"query": "3D gaussian splatting", "max_results": 3}
         → 原样解析并做类型转换
    """
    text = (text or "").strip()
    if text in ("", "(none)", "none", "None"):
        return {}

    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return {k: _coerce_value(v, type_map.get(k, "")) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass  # 不是合法 JSON，按纯文本处理

    if query_hint is None:
        return {"input": text}
    return {query_hint: text}


# ==============================================================
#  2. 同步工具包装
# ==============================================================

def _build_description(raw_tool, arg_info: str, query_hint: Optional[str]) -> str:
    """重写工具描述，明确告诉模型这个工具只接收一个字符串。"""
    base = (raw_tool.description or "").strip()
    lines = [base, "", "【本工具接收单字符串输入】"]

    if query_hint:
        hint = f'纯查询词（等价于 {"{"}"{query_hint}": "你的查询词"{"}"}）'
    else:
        hint = "JSON 字符串"

    lines.append(f"可用写法一：{hint}")
    lines.append(
        '可用写法二：JSON 对象，例如 '
        '{"query": "3D gaussian splatting", "max_results": 3}'
    )
    lines.append("支持的参数：")
    lines.append(arg_info)
    return "\n".join(lines)


def _make_sync_tool(raw_tool, arg_names, arg_info, type_map, query_hint) -> StructuredTool:
    """
    把 MCP 异步工具包装为「单字符串输入」的同步 LangChain 工具。

    MCP 工具本身是异步的，而本项目用的是同步 LangChain Agent，因此需要这层桥接；
    同时又要把 JSON Schema 降维成单字符串，以适配 ReAct 的文本协议。
    """
    canonical = query_hint or (arg_names[0] if arg_names else None)

    def _to_mcp_kwargs(action_input: str) -> Dict[str, Any]:
        """
        解析输入并映射成 MCP 工具真正接受的参数名。

        MCPTool.ainvoke 会用「原始 MCP schema」校验入参，
        因此不能直接传 {"input": ...}，必须还原成 {"query": ...} 这样的真实参数名。
        """
        parsed = _parse_action_input(action_input, arg_names, type_map, query_hint)

        # 单字符串写法解析出的键名（query_hint 或 "input"）映射到真实参数名
        if len(parsed) == 1 and canonical:
            ((key, value),) = parsed.items()
            if key not in arg_names:
                parsed = {canonical: value}

        return parsed

    async def _call_async(action_input: str) -> str:
        kwargs = _to_mcp_kwargs(action_input)
        result = await raw_tool.ainvoke(kwargs)
        text = result if isinstance(result, str) else str(result)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n…（结果过长已截断，共 {len(text)} 字符）"
        return text

    def _call(action_input: str) -> str:
        loop = asyncio.new_event_loop()
        started = time.perf_counter()
        log.debug("MCP 工具调用: %s 输入=%r", raw_tool.name, shorten(action_input, 60))
        try:
            result = loop.run_until_complete(
                asyncio.wait_for(_call_async(action_input), timeout=MCP_CALL_TIMEOUT)
            )
            log.success("MCP 工具返回: %s 耗时 %.1fs 结果 %d 字符",
                        raw_tool.name, time.perf_counter() - started, len(result or ""))
            return result
        except asyncio.TimeoutError:
            log.error("MCP 工具调用超时（>%.0fs）: %s", MCP_CALL_TIMEOUT, raw_tool.name)
            return (f"工具 {raw_tool.name} 调用超时（>{MCP_CALL_TIMEOUT:.0f}s），"
                    f"请稍后重试或改用其他工具。")
        except Exception as exc:  # noqa: BLE001
            log.error("MCP 工具调用失败: %s -> %s: %s",
                      raw_tool.name, type(exc).__name__, exc, exc_info=True)
            return f"工具 {raw_tool.name} 调用失败: {exc}"
        finally:
            loop.close()

    return StructuredTool(
        name=raw_tool.name,
        description=_build_description(raw_tool, arg_info, query_hint),
        args_schema=McpStringInput,
        func=_call,
        coroutine=_call_async,
    )


# ==============================================================
#  3. 加载与缓存
# ==============================================================

def _load_tools_sync() -> List[Any]:
    """同步拉取 MCP 工具列表并转换为可被 ReAct 调用的形式。"""
    log.debug("连接 MCP 服务端拉取工具列表: %s", Config.MCP_SERVER_URL)
    client = MultiServerMCPClient({
        "academic_search": {
            "transport": "streamable_http",
            "url": Config.MCP_SERVER_URL,
            "timeout": MCP_LOAD_TIMEOUT,
        }
    })
    raw_tools = asyncio.run(
        asyncio.wait_for(client.get_tools(), timeout=MCP_LOAD_TIMEOUT)
    )

    tools = []
    for raw in raw_tools:
        arg_names, arg_info, type_map = _describe_tool_args(raw)
        query_hint = _extract_query_hint(raw, arg_names)
        log.debug("MCP 工具 %s 参数=%s 默认参数名=%s", raw.name, arg_names, query_hint)
        tools.append(_make_sync_tool(raw, arg_names, arg_info, type_map, query_hint))
    return tools


_tools: List[Any] = []
_last_attempt: float = 0.0
_last_error: str = ""


def get_mcp_tools(force: bool = False) -> List[Any]:
    """
    获取 MCP 工具列表（带重试窗口的轻量缓存）。

    Args:
        force: True 时忽略缓存，强制重新连接。
    Returns:
        同步 LangChain 工具列表；MCP 不可用时返回空列表（Agent 会跳过这些工具）。
    """
    global _tools, _last_attempt, _last_error

    if _tools and not force:
        return _tools
    if not force and _last_error and (time.time() - _last_attempt) < RETRY_INTERVAL:
        # 刚失败过，不重复重试，避免每个请求都卡在网络超时上
        return []

    _last_attempt = time.time()
    try:
        _tools = _load_tools_sync()
        _last_error = ""
        log.success("MCP 工具加载成功（%s）: %s", Config.MCP_SERVER_URL, [t.name for t in _tools])
    except Exception as exc:  # noqa: BLE001
        _tools = []
        _last_error = str(exc)
        log.warning("MCP 工具加载失败（%s）: %s", Config.MCP_SERVER_URL, exc)
        log.warning("   将在 %.0f 秒后允许重试；期间 Agent 仍可正常使用其他工具（降级运行）。",
                    RETRY_INTERVAL)
    return _tools


def reset_mcp_cache() -> None:
    """清空缓存，让下一次 get_mcp_tools() 立即重连。"""
    global _tools, _last_attempt, _last_error
    _tools = []
    _last_attempt = 0.0
    _last_error = ""


# ==============================================================
#  4. 直接运行本文件时做可用性自检
# ==============================================================

if __name__ == "__main__":
    import sys

    sys.path.insert(0, Config.BACKEND_DIR)
    from app.utils.console import use_utf8_console
    use_utf8_console()

    print(f"🔍 连接 MCP 服务端: {Config.MCP_SERVER_URL}")
    tools = get_mcp_tools(force=True)
    print(f"✅ 成功加载 {len(tools)} 个工具:")
    for t in tools:
        print(f"  - {t.name}")
        print(f"      schema: {t.args_schema}")
        print(f"      描述首行: {(t.description or '').strip().splitlines()[0]}")

    arxiv_tool = next((t for t in tools if t.name == "search_arxiv"), None)
    if arxiv_tool:
        print("\n🔬 测试 search_arxiv —— 纯查询词写法")
        raw = arxiv_tool.invoke("3D gaussian splatting")
        try:
            data = json.loads(raw)
            for p in data.get("papers", []):
                print(f"  - {p['published']} {p['title'][:70]}")
                print(f"    PDF: {p['pdf_url']}")
        except json.JSONDecodeError:
            print(raw[:600])

        print("\n🔬 测试 search_arxiv —— JSON 写法（带 max_results）")
        raw2 = arxiv_tool.invoke('{"query": "vision transformer detection", "max_results": 2}')
        try:
            data2 = json.loads(raw2)
            print(f"  返回 {data2.get('count')} 篇:")
            for p in data2.get("papers", []):
                print(f"  - {p['published']} {p['title'][:70]}")
        except json.JSONDecodeError:
            print(raw2[:400])
