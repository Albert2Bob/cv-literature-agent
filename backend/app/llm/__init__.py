"""
共享 LLM 实例
=============
Chain 模式与 Agent 模式共用同一个 ChatOpenAI 实例（DeepSeek，OpenAI 兼容接口）。
"""
from langchain_openai import ChatOpenAI

from app.config import Config

llm = ChatOpenAI(
    model=Config.DEEPSEEK_MODEL,
    api_key=Config.DEEPSEEK_API_KEY,
    base_url=Config.DEEPSEEK_API_BASE,
    temperature=0.7,
    timeout=120,
    max_retries=2,
)

__all__ = ["llm"]
