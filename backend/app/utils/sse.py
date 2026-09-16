"""
SSE（Server-Sent Events）工具
============================

输出协议（前后端契约，不能随意改动）：
    data: [THINKING]        首帧心跳，防止前端判定超时
    data: [THINK] …         Agent 的思考过程
    data: [STEP] …          工具调用与观察结果
    data: [FINAL] …         最终答案
    data: [ERROR] …         标准化异常事件
    data: [DONE]            流结束
"""
import time

from flask import Response, stream_with_context

from app.logging_conf import get_logger, get_request_id, set_request_context

log = get_logger("utils.sse")


def _emit(text: str) -> str:
    """把一段可能含换行的文本编码为一条 SSE 事件。"""
    lines = "".join(f"data: {line}\n" for line in str(text).split("\n"))
    return lines + "\n"


def sse_response(generator_fn, *args, **kwargs):
    """
    把任意同步生成器包装成 Flask 的 SSE 流式响应。

    Args:
        generator_fn: 生成器函数，逐段 yield 文本
        *args, **kwargs: 透传给 generator_fn 的参数
    Returns:
        Flask Response（text/event-stream）
    """
    # 生成器是在响应返回之后才被消费的，此时 Flask 的请求上下文已经变化，
    # 这里把当前请求的链路 ID 捕获下来，在生成器内部恢复，保证流式阶段的日志
    # 也能和触发它的那次请求对上。
    rid = get_request_id()

    def generate():
        if rid and rid != "-":
            set_request_context(rid)
        started = time.perf_counter()
        chunks = 0
        aborted = False
        try:
            yield _emit("[THINKING]")
            for chunk in generator_fn(*args, **kwargs):
                if chunk:
                    chunks += 1
                    yield _emit(chunk)
        except GeneratorExit:
            # 客户端提前断开（刷新页面、切走路由、curl 提前退出）。
            # 这里必须**只清理、绝不 yield**：
            # Python 生成器收到 GeneratorExit 后再 yield 会抛
            # "RuntimeError: generator ignored GeneratorExit"，
            # 而 Flask 在响应头已发出的情况下只能把它打成一段难看的堆栈。
            aborted = True
            raise
        except Exception as exc:  # noqa: BLE001 - 流式过程中必须转成事件而不是 500
            log.error("SSE 流式输出过程中出错: %s: %s", type(exc).__name__, exc, exc_info=True)
            yield _emit(f"[ERROR] {exc}")
        finally:
            # 同样不能在 finally 里 yield（客户端提前断开时 finally 依然会执行），
            # 因此 [DONE] 放在正常路径的末尾发送，这里只记日志。
            elapsed = time.perf_counter() - started
            if aborted:
                log.info("SSE 连接被客户端提前关闭（常见于刷新页面/切换路由）: "
                         "已发送 %d 个数据块，耗时 %.1fs", chunks, elapsed)
            else:
                log.info("SSE 流结束: 共 %d 个数据块，耗时 %.1fs", chunks, elapsed)

        yield _emit("[DONE]")

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
