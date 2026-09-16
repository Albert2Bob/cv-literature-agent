"""
CV科研问答智能体路由（Agent 模式）
================================

接口：
    GET /api/ai/cv_agent/chat?message=xxx&session_id=xxx

工具集（按可用性动态装配，缺哪个就跳过哪个，不阻断整个 Agent）：
    基础   get_time / calc / gpu_status
    知识库 cv_rag_search        （阶段 4 接入）
    MCP    search_arxiv 等       （阶段 6 接入）
    技能   list_skills / read_skill（阶段 5 接入）
"""
import os

from flask import Blueprint, request

from app.config import Config
from app.llm import llm
from app.logging_conf import get_logger, shorten
from app.utils.sse import sse_response

log = get_logger("routes.cv_agent")

cv_agent_bp = Blueprint("cv_agent", __name__)

# ==============================================================
#  System Prompt：CV 科研问答智能体
# ==============================================================
SYSTEM_PROMPT = """你是「AI 科研问答智能体」，服务于计算机视觉与深度学习方向的研究人员。

【定位】
你不是一个只会闲聊的助手，而是能调用工具、查知识库、查论文、按流程办事的科研助理。
你的回答要能直接用于课题推进：给出结论、依据与可执行步骤。

【能力范围】
- 计算机视觉：图像分类、目标检测、语义/实例分割、关键点、跟踪、3D 视觉、多模态、生成模型。
- 深度学习：网络结构、损失函数、优化器、训练技巧、分布式训练、模型压缩与部署。
- 科研流程：方法选型、基线选择、消融实验设计、评价指标、论文写作与投稿。

【工作原则】
1. 先判断是否需要外部信息：涉及具体论文、最新进展、数据集指标时，优先调用检索工具，
   不要凭记忆编造论文标题、作者、年份或数值。
2. 涉及知识库中的方法原理与经验技巧时，调用 `cv_rag_search` 获取依据后再作答。
3. 涉及算力可行性时，可调用 `gpu_status` 查看本机 GPU 情况。
4. 涉及计算（参数量、FLOPs、显存、指标换算）时，调用 `calc` 而不是心算。
5. 当请求需要多步骤结构化产出（精读报告、实验方案、方法对比、审稿意见）时，
   按系统提示的技能路由规则先 `list_skills` 再 `read_skill`，严格按技能格式执行。

【输出规范】
- 使用简体中文；专业术语中英对照，如 特征金字塔（FPN）。
- 结构化：小标题 + 要点列表；方法对比用 Markdown 表格。
- 公式用 LaTeX：行内 $...$，独立 $$...$$。
- 明确区分「有依据的结论」与「我的推测」，推测必须标注。
- 不编造引用；信息不足时直接说明需要哪些补充信息。

若消息末尾附带了【对话历史】，请结合上下文理解用户的追问
（例如「那它的缺点呢」指的是上文提到的方法）。
"""

# ==============================================================
#  工具装配
# ==============================================================

# ---- Skills 中间件（扫描 backend/skills/*.md） ----
from app.llm.skill_middleware import SkillsMiddleware

_skill_middleware = SkillsMiddleware(sources=[Config.SKILLS_DIR])


def _load_rag_tools():
    """加载 RAG 检索工具；知识库或依赖不可用时返回空列表。"""
    try:
        from app.llm.rag import RAG_TOOLS
        return list(RAG_TOOLS)
    except Exception as exc:  # noqa: BLE001
        log.error("RAG 工具未启用（知识库相关功能将不可用）: %s", exc, exc_info=True)
        return []


def _load_mcp_tools():
    """加载 MCP 远端工具；MCP 服务端未启动时返回空列表。"""
    try:
        from app.llm.mcp_tools import get_mcp_tools
        tools = get_mcp_tools()
        if tools:
            log.debug("MCP 工具已加载: %s", [t.name for t in tools])
        return tools
    except Exception as exc:  # noqa: BLE001
        log.warning("MCP 工具未启用（可忽略，MCP 服务端未启动时正常）: %s", exc)
        return []


def build_agent(context=""):
    """按当前可用性装配工具并创建 AgentExecutor。"""
    from app.llm.agent import calc, get_time, gpu_status
    from app.llm.skill_middleware import create_agent

    extra_tools = [get_time, calc, gpu_status]
    extra_tools += _load_rag_tools()
    extra_tools += _load_mcp_tools()

    prompt = SYSTEM_PROMPT

    names = [t.name for t in extra_tools]
    log.debug("Agent 工具装配完成，共 %d 个: %s", len(names), names)

    return create_agent(
        prompt,
        middleware=[_skill_middleware],
        extra_tools=extra_tools,
        context=context,
    )


# ==============================================================
#  路由
# ==============================================================

@cv_agent_bp.route("/api/ai/cv_agent/chat")
def chat():
    message = (request.args.get("message") or "").strip()
    session_id = request.args.get("session_id", "")

    if not message:
        log.warning("CV 智能体请求缺少 message 参数，已拒绝")
        return {"error": "message is required"}, 400

    context = ""
    if session_id:
        from app.chat_history import build_context, maybe_auto_title, save_message
        context = build_context(session_id)
        save_message(session_id, "user", message)
        maybe_auto_title(session_id, message)
        log.info("CV 智能体（多轮）: session=%s 上下文=%d 字 问题=%r",
                 session_id, len(context), shorten(message, 40))
    else:
        log.info("CV 智能体（单轮，无会话历史）: 问题=%r", shorten(message, 40))

    executor = build_agent(context)
    from app.llm.agent import stream_agent
    return sse_response(stream_agent, executor, message, session_id, llm)
