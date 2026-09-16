"""
SSE 客户端测试辅助模块
=====================
严格按 SSE 规范解析事件流：**连续的 `data:` 行属于同一个事件，空行才是事件边界**。

这一点很关键：`[STEP]` 与 `[FINAL]` 的内容包含换行（Markdown 表格、代码块），
后端会把它拆成多个 `data:` 行。如果按「每个 data 行一个事件」去读，
长回答会被截断成第一行——这不是后端 bug，而是解析方式不对。

前端 `EventSource.onmessage` 由浏览器自动完成这个拼接，所以不会出现该问题。
"""
import httpx


def iter_events(url, params, timeout=300):
    """
    连接 SSE 接口，逐事件产出字符串（已合并多行 data）。

    Yields:
        str: 一个完整事件的文本内容
    """
    data_lines = []
    with httpx.stream("GET", url, params=params,
                      timeout=httpx.Timeout(timeout, read=timeout)) as resp:
        if resp.status_code != 200:
            yield f"[HTTP {resp.status_code}]"
            return
        for raw in resp.iter_lines():
            line = raw.rstrip("\r")
            if line == "":
                # 空行 = 事件结束
                if data_lines:
                    yield "\n".join(data_lines)
                    data_lines = []
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        yield "\n".join(data_lines)


def collect(url, params, timeout=300):
    """收集全部事件，返回列表。"""
    return list(iter_events(url, params, timeout=timeout))


def parse(events, mode="agent"):
    """
    把事件列表拆分成结构化结果。

    Args:
        events: collect() 返回的事件列表
        mode:   "agent" —— Agent 模式，事件带 [THINK]/[STEP]/[FINAL] 前缀，
                           且 [FINAL] 内容本身含换行（Markdown）
                "chain" —— Chain 模式，每个事件是一个**原始文本分片**，
                           必须直接拼接，**不能插入换行**，否则会和落库内容对不上

    Returns:
        dict: {
            "think": [str], "step": [str], "final": str,
            "error": [str], "tokens": int, "events": [str]
        }
    """
    think, step, error = [], [], []
    final_parts = []
    tokens = 0

    for e in events:
        if e == "[THINKING]":
            continue
        if e == "[DONE]":
            continue
        if e.startswith("[THINK]"):
            think.append(e[len("[THINK]"):].strip())
        elif e.startswith("[STEP]"):
            step.append(e[len("[STEP]"):].strip())
        elif e.startswith("[ERROR]"):
            error.append(e[len("[ERROR]"):].strip())
        elif e.startswith("[FINAL]"):
            final_parts.append(e[len("[FINAL]"):].lstrip())
        else:
            # Chain 模式：纯文本 token 流
            tokens += 1
            final_parts.append(e)

    if mode == "chain":
        # Chain 的每个事件就是一段连续文本，直接拼接
        final = "".join(final_parts).strip()
    else:
        # Agent 的多个 [FINAL] 事件之间保留换行
        final = "\n".join(final_parts).strip()

    return {
        "think": think,
        "step": step,
        "final": final,
        "error": error,
        "tokens": tokens,
        "events": events,
    }
