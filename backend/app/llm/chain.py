"""
Chain 实现 —— 论文精读助手
==========================

数据流完全一致：
    ChatPromptTemplate (system + human) → ChatOpenAI → StrOutputParser → 文本块流

领域：System Prompt 为「论文精读助手」。
"""
import time

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.llm import llm
from app.logging_conf import get_logger, shorten

log = get_logger("llm.chain")

# ==============================================================
#  System Prompt：论文精读助手（Chain 模式角色设定）
# ==============================================================
DEFAULT_SYSTEM_PROMPT = """你是「AI 论文精读助手」，一名计算机视觉与深度学习方向的资深研究者，
擅长把艰深的论文讲清楚。你的服务对象是正在读论文、做课题的研究生与工程师。

【你的能力边界】
1. 概念讲解：用准确的术语 + 直觉化的类比解释概念，先给一句话定义，再展开。
2. 公式解读：解释符号含义、推导思路、每一项的物理意义与作用，必要时用 LaTeX 书写公式。
3. 段落翻译：把英文论文段落翻译成通顺的中文，专业术语保留英文原文（如 backbone、anchor-free）。
4. 方法梳理：把一段方法描述拆解为「输入 → 模块 → 输出」的结构化流程。
5. 审稿视角：指出方法假设是否合理、实验对比是否充分、可能的失败场景。

【输出规范】
- 使用简体中文，术语中英对照，例如：感受野（receptive field）。
- 结构化输出，善用小标题、有序列表与 Markdown 表格。
- 涉及公式时使用 LaTeX：行内用 $...$，独立公式用 $$...$$。
- 不臆造论文中不存在的实验数据、指标数值或引用；不确定时明确说明「论文未提及」。
- 不堆砌空话，直接给结论与理由；篇幅服从问题复杂度，简单问题不长篇大论。

【典型请求】
- “解释一下 Swin Transformer 的 shifted window 是怎么工作的”
- “这段方法描述帮我翻译并讲清楚：<英文段落>”
- “DETR 的匈牙利匹配损失每一项是什么意思”
- “这篇论文的实验部分有什么可以质疑的地方”
"""


def make_chain(system_prompt=None, context=""):
    """
    构建 LangChain LCEL 链：prompt_template | llm | string_parser

    Args:
        system_prompt: 角色指令，默认使用 DEFAULT_SYSTEM_PROMPT。
        context:       对话历史（摘要 + 最近消息）。有历史时 human 模板会多一个 {history}。

    Returns:
        可用的 Runnable 链（支持 .stream() / .invoke()）
    """
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    if context:
        human_template = "【对话历史】\n{history}\n\n---\n\n{input}"
    else:
        human_template = "{input}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_template),
    ])
    return prompt | llm | StrOutputParser()


def stream_chain(chain, message, context="", session_id="", llm_ref=None):
    """
    同步流式输出，逐 token 产出文本。

    Args:
        chain:      make_chain() 返回的 Runnable
        message:    用户输入
        context:    对话历史字符串（决定是否需要传 history 变量）
        session_id: 流结束后保存 assistant 消息并触发摘要
        llm_ref:    保留参数，当前未使用

    Yields:
        str: LLM 输出的 token 级文本块
    """
    log.debug("Chain 调用开始: session=%s 问题=%r 上下文=%d 字",
              session_id or "(无)", shorten(message, 50), len(context or ""))

    final_answer = ""
    invoke_input = {"input": message}
    if context:
        invoke_input["history"] = context

    started = time.perf_counter()
    try:
        for chunk in chain.stream(invoke_input):
            if chunk:
                final_answer += chunk
                yield chunk
    except Exception as exc:  # noqa: BLE001 - 要记日志后继续抛给 SSE 层
        log.error("Chain 流式生成失败: session=%s -> %s: %s",
                  session_id or "(无)", type(exc).__name__, exc, exc_info=True)
        raise

    elapsed = time.perf_counter() - started
    log.success("Chain 生成完成: session=%s 输出=%d 字 耗时=%.1fs 速率=%.0f 字/秒",
                session_id or "(无)", len(final_answer), elapsed,
                len(final_answer) / elapsed if elapsed > 0 else 0)

    # 流结束后落库 + 触发摘要
    if session_id and final_answer:
        try:
            from app.chat_history import save_message, update_summary
            save_message(session_id, "assistant", final_answer)
            log.debug("assistant 消息已落库: session=%s %d 字", session_id, len(final_answer))
            update_summary(session_id)
        except Exception as exc:  # noqa: BLE001
            log.error("保存 assistant 消息失败: session=%s -> %s", session_id, exc, exc_info=True)
