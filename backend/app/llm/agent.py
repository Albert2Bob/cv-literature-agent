"""
Agent 实现 —— CV 科研问答智能体
==============================

数据流完全一致：
    Prompt(system + tools + scratchpad) → ChatOpenAI → ReAct 输出解析
    → 执行工具 → 观察结果 → 循环，直到 Final Answer

ReAct 配置：
    max_iterations=15 / max_execution_time=90 / handle_parsing_errors=True
    early_stopping_method="generate"

领域改动：
  1. AGENT_TEMPLATE 的技能路由说明改为科研技能（论文精读 / 实验设计 / 方法对比 / 投稿审查）
  2. 工具集：保留 get_time / calc，新增 gpu_status，RAG 工具改名为 cv_rag_search
  3. calc 改用受限 AST 求值
"""
import ast
import math
import operator
import re
import time
from datetime import datetime

from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import tool
from langchain_core.prompts import PromptTemplate

from app.llm import llm
from app.logging_conf import get_logger, shorten

log = get_logger("llm.agent")


# ==============================================================
#  基础工具
# ==============================================================

@tool
def get_time():
    """获取当前日期与时间。当用户询问当前时间，或技能要求以真实时间作为输入时调用。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")
    log.debug("工具 get_time 执行 -> %s", now)
    return now


# ---- 受限 AST 求值：只允许算术运算与白名单数学函数 ----
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_NAMES = {
    "pi": math.pi,
    "e": math.e,
    "sqrt": math.sqrt,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "pow": pow,
    "min": min,
    "max": max,
}


def _safe_eval(node):
    """递归求值受限 AST 节点。"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("只支持数字常量")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[node.id]
        raise ValueError(f"不支持的标识符: {node.id}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_NAMES:
            raise ValueError("不支持的函数调用")
        func = _ALLOWED_NAMES[node.func.id]
        if not callable(func):
            raise ValueError(f"{node.func.id} 不是函数")
        return func(*[_safe_eval(a) for a in node.args])
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(e) for e in node.elts)
    raise ValueError(f"不支持的表达式类型: {type(node).__name__}")


@tool
def calc(expr: str):
    """
    计算数学表达式，适用于参数量、FLOPs、显存占用、指标换算等算术问题。

    输入示例："2**10 * 3"、"sqrt(224*224*3)"、"1152/1000"。
    支持 + - * / // % ** 与 sqrt/log/exp/sin/cos/abs/round/min/max 等函数，以及 pi、e 常量。
    """
    try:
        tree = ast.parse(expr, mode="eval")
        result = str(_safe_eval(tree))
        log.debug("工具 calc 执行: %s = %s", shorten(expr, 60), result)
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("工具 calc 拒绝执行: %s -> %s", shorten(expr, 60), exc)
        return f"计算失败: {exc}（仅支持算术表达式与常用数学函数）"


@tool
def gpu_status() -> str:
    """
    查询本机 GPU 的型号、显存占用与利用率，用于评估实验的算力是否够用。

    优先使用 pynvml（nvidia-ml-py）读取；未安装时自动回退到解析 nvidia-smi 输出，
    因此无需额外安装依赖也能工作。既没有 nvidia-smi 也没有 pynvml 时返回提示信息，
    不影响其他工具。
    """
    result = _gpu_status_via_pynvml() or _gpu_status_via_nvidia_smi() or (
        "未检测到可用的 GPU 查询方式（既未安装 pynvml，也未找到 nvidia-smi）。"
        "若本机无 NVIDIA 显卡可忽略此项；若确有显卡，请执行 pip install nvidia-ml-py。"
    )
    log.debug("工具 gpu_status 执行 -> %s", shorten(result, 80))
    return result


def _gpu_status_via_pynvml() -> str:
    """通过 pynvml 读取 GPU 状态；不可用时返回空串。"""
    try:
        import pynvml  # type: ignore
    except Exception:  # noqa: BLE001 - 未安装时走 nvidia-smi 回退
        log.debug("pynvml 不可用，改用 nvidia-smi 回退")
        return ""

    try:
        pynvml.nvmlInit()
        try:
            count = pynvml.nvmlDeviceGetCount()
            if count == 0:
                return "本机未检测到 NVIDIA GPU。"
            lines = [f"检测到 {count} 块 GPU（数据来源：pynvml）："]
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", "ignore")
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                lines.append(
                    f"  [{i}] {name} | 显存 {mem.used / 1024**3:.1f}/{mem.total / 1024**3:.1f} GB "
                    f"| 利用率 {util.gpu}%"
                )
            return "\n".join(lines)
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001 - 驱动异常时交给 nvidia-smi 回退
        return ""


def _gpu_status_via_nvidia_smi() -> str:
    """回退方案：解析 nvidia-smi 的 CSV 输出；不可用时返回空串。"""
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        log.debug("未找到 nvidia-smi")
        return ""

    try:
        proc = subprocess.run(
            [exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("nvidia-smi 调用失败: %s", exc)
        return ""

    if proc.returncode != 0 or not proc.stdout.strip():
        log.warning("nvidia-smi 返回异常: rc=%s stderr=%s", proc.returncode,
                    shorten(proc.stderr or "", 100))
        return ""

    lines = [f"检测到 {len(proc.stdout.strip().splitlines())} 块 GPU（数据来源：nvidia-smi）："]
    for i, row in enumerate(proc.stdout.strip().splitlines()):
        parts = [p.strip() for p in row.split(",")]
        if len(parts) < 4:
            continue
        name, used, total, util = parts[0], parts[1], parts[2], parts[3]
        try:
            used_gb = float(used) / 1024
            total_gb = float(total) / 1024
            lines.append(
                f"  [{i}] {name} | 显存 {used_gb:.1f}/{total_gb:.1f} GB | 利用率 {util}%"
            )
        except ValueError:
            lines.append(f"  [{i}] {name} | 显存 {used}/{total} MiB | 利用率 {util}%")
    return "\n".join(lines) if len(lines) > 1 else ""


# ==============================================================
#  ReAct Prompt 模板
# ==============================================================
# 必需变量：{tools} {tool_names} {input} {agent_scratchpad}
# {system_prompt} 在工厂函数里通过 .partial() 预填充。
AGENT_TEMPLATE = """{system_prompt}

你拥有一组「科研技能（Skills）」——它们是面向特定科研任务的多步骤工作流
（例如：论文精读报告、实验方案设计、方法对比矩阵、投稿前自审）。

与技能相关的工具是：
- `list_skills` —— 列出全部可用技能及其简介。
- `read_skill` —— 按技能名称读取该技能的完整指令正文。

【技能自动路由规则 —— 必须遵守】
当用户的请求属于以下情形时，不要给泛泛的回答，也不要要求用户输入特殊触发词，
你必须主动考虑使用技能：
1. 请求是模糊的、复杂的或创作型的（如「帮我精读这篇论文」「设计一下消融实验」）；
2. 请求需要多步骤产出结构化成果（报告、方案、对比表、审稿意见）。

你的决策流程：
步骤 A —— 判断任务类型。若符合上述情形，先调用 `list_skills` 看是否有匹配的技能。
步骤 B —— 若找到匹配技能（如 `paper_digest`），调用 `read_skill` 并传入其准确名称以载入完整指令。
步骤 C —— 严格按技能正文的步骤执行，其中可能需要调用其他基础工具
          （如 `get_time`、`cv_rag_search`、`search_arxiv`）。
步骤 D —— 严格按技能要求的格式与篇幅产出最终结果。

重要：你不需要用户重复任何特殊命令。技能一旦载入，就视为已激活，直接按其内部流程执行。

你可以使用以下工具：
{tools}

【严格格式规则 —— 必须逐字遵守】
每一次回复只能输出下面两种模式之一：

=== 模式 1 - 调用工具 ===
Thought: （你的推理）
Action: （工具名，必须是 [{tool_names}] 中的一个）
Action Input: （传给工具的输入）
之后系统会给你一个 Observation。收到 Observation 后，重复
Thought / Action / Action Input，或者进入模式 2。

=== 模式 2 - 给出最终答案 ===
Thought: （你的推理）
Final Answer: （给用户的完整回答）

【关键约束】
- "Final Answer:" 必须出现在最后，独占一行。
- 不要在上面的模式之外输出任何解释性文字。
- "Action:" 行只能包含工具名。
- "Action Input:" 行只能包含工具输入。
- 在 "Final Answer:" 之后不要再输出任何内容。

=== 示例 ===
Question: 现在几点？
Thought: 我需要获取当前时间。
Action: get_time
Action Input: (none)
Observation: 2026-07-16 10:00:00 (Thursday)
Thought: 我已经拿到时间了。
Final Answer: 当前时间是 2026-07-16 10:00。

Begin!
Question: {input}
Thought:{agent_scratchpad}"""


# ==============================================================
#  工厂与流式执行
# ==============================================================

def make_agent(system_prompt, context="", extra_tools=None):
    """
    构建一个 ReAct AgentExecutor（仅使用内置工具，不含 Skills 中间件）。

    Args:
        system_prompt: 角色指令
        context:       对话历史（可选）
        extra_tools:   额外工具列表，默认 [get_time, calc, gpu_status]
    Returns:
        AgentExecutor，支持 .stream() / .invoke()
    """
    full_prompt = system_prompt
    if context:
        full_prompt = system_prompt + "\n\n【对话历史】\n" + context

    tools = list(extra_tools) if extra_tools is not None else [get_time, calc, gpu_status]
    prompt = PromptTemplate.from_template(AGENT_TEMPLATE).partial(system_prompt=full_prompt)
    agent = create_react_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        handle_parsing_errors=True,
        max_iterations=15,
        early_stopping_method="generate",
        max_execution_time=90,
    )


def extract_thought(log_text: str) -> str:
    """从 LLM 输出日志中提取 Thought 内容。"""
    match = re.search(r"Thought:\s*(.*?)(?=\nAction:|\nFinal Answer:|$)", log_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return (log_text or "").strip()


def stream_agent(executor, message, session_id="", llm_ref=None):
    """
    同步流式执行 Agent，实时产出思考过程、工具调用与最终答案。

    Yields:
        str: SSE 事件字符串
             "[THINK] 思考:…" / "[STEP] 工具:… 输入:… 结果:…" / "[FINAL] …"
    """
    log.info("Agent 开始执行: session=%s 问题=%r 可用工具=%d 个",
             session_id or "(无)", shorten(message, 50), len(executor.tools))

    final_answer = ""
    step_index = 0
    started = time.perf_counter()

    try:
        for step in executor.stream({"input": message}):
            actions = step.get("actions", [])
            steps = step.get("steps", [])

            for action in actions:
                if getattr(action, "tool", None):
                    step_index += 1
                    thought_text = extract_thought(getattr(action, "log", "")) if hasattr(action, "log") else ""
                    if thought_text:
                        log.debug("Agent 第 %d 步 · 思考: %s", step_index, shorten(thought_text, 120))
                        yield f"[THINK] 思考:{thought_text}"
                    log.info("Agent 第 %d 步 · 调用工具 %s 输入=%s",
                             step_index, action.tool, shorten(str(action.tool_input), 60))

            for s in steps:
                obs = (s.observation or "").strip()
                if obs and "Invalid Format" not in obs and "Could not parse" not in obs:
                    tool_name = getattr(s.action, "tool", "?") if getattr(s, "action", None) else "?"
                    tool_in = getattr(s.action, "tool_input", "") if getattr(s, "action", None) else ""
                    log.success("Agent 工具返回: %s -> %s", tool_name, shorten(obs, 100))
                    yield f"[STEP] 工具: {tool_name} 输入: {tool_in} 结果: {obs[:300]}"
                elif obs:
                    # 格式解析失败会被 AgentExecutor 转成 Observation 再来一轮，
                    # 这类内容对排查 ReAct 格式问题很有用，但正常流程不该出现
                    log.warning("Agent 输出格式异常，触发重试: %s", shorten(obs, 120))

            if "output" in step:
                final_answer = step["output"]
                log.debug("Agent 最终答案: %s", shorten(final_answer, 150))
                yield f"[FINAL] {final_answer}"
    except Exception as exc:  # noqa: BLE001 - 记日志后继续抛给 SSE 层
        log.error("Agent 执行失败: session=%s 已完成 %d 步 -> %s: %s",
                  session_id or "(无)", step_index, type(exc).__name__, exc, exc_info=True)
        raise

    elapsed = time.perf_counter() - started
    if step_index >= 15:
        log.warning("Agent 达到最大推理轮次上限(15)，可能因问题过于复杂或陷入循环: session=%s",
                    session_id or "(无)")
    log.success("Agent 执行完成: session=%s 工具调用=%d 次 输出=%d 字 耗时=%.1fs",
                session_id or "(无)", step_index, len(final_answer), elapsed)

    # 流结束后落库 + 触发摘要
    if session_id and final_answer:
        try:
            from app.chat_history import save_message, update_summary
            save_message(session_id, "assistant", final_answer)
            log.debug("assistant 消息已落库: session=%s %d 字", session_id, len(final_answer))
            update_summary(session_id)
        except Exception as exc:  # noqa: BLE001
            log.error("保存 assistant 消息失败: session=%s -> %s", session_id, exc, exc_info=True)
