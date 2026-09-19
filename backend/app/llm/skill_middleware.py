"""
Skills 中间件（渐进式技能模板）
==============================

设计理念：
  - 渐进式暴露：Agent 先用 `list_skills` 查看有哪些技能，
    再用 `read_skill` 拉取某个技能的完整指令，然后按指令逐步执行。
  - 技能以 Markdown 文件形式存放于 backend/skills/ 目录，
    文件头用 YAML Front Matter 声明 name 与 description。

技能文件格式：
    ---
    name: paper_digest
    description: 一句话说明什么时候该用这个技能
    ---

    ## Body
    （完整的多步骤指令，Agent 会严格按此执行）
"""
import os as _os

from langchain.tools import tool


class SkillsMiddleware:
    """扫描目录下的 .md 文件，暴露为可渐进式加载的技能。"""

    def __init__(self, sources):
        self.sources = sources
        self._skills = {}  # name -> {"description": ..., "body": ...}
        self._discover()

    def _discover(self):
        for src in self.sources:
            skill_dir = _os.path.abspath(src)
            if not _os.path.isdir(skill_dir):
                continue
            for fname in sorted(_os.listdir(skill_dir)):
                if fname.endswith(".md"):
                    self._load(fname, skill_dir)

    def _load(self, fname, skill_dir):
        filepath = _os.path.join(skill_dir, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        name = fname[:-3]  # 默认用文件名，Front Matter 可覆盖
        description = ""
        body = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                front_matter = parts[1].strip()
                body = parts[2].strip()
                for line in front_matter.split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()

        self._skills[name] = {"description": description, "body": body}

    def list_skill_names(self):
        return list(self._skills.keys())

    def get_tools(self):
        """返回 [list_skills, read_skill] 两个 LangChain 工具。"""
        skills_ref = self._skills

        @tool
        def list_skills():
            """列出所有可用的科研技能模块名称和简介。当用户请求模糊、复杂、需要多步骤结构化产出时先调用本工具。"""
            if not skills_ref:
                return "当前没有可用的技能模块。"
            result = ["可用的科研技能模块："]
            for name, info in skills_ref.items():
                desc = info.get("description", "暂无描述")
                result.append(f"  - {name}: {desc}")
            result.append("\n请选择最匹配的技能，并用 read_skill 读取它的完整指令。")
            return "\n".join(result)

        @tool
        def read_skill(skill_name: str):
            """读取指定科研技能的完整指令正文。输入必须是 list_skills 返回的技能名称之一。"""
            if skill_name in skills_ref:
                return skills_ref[skill_name]["body"]
            available = ", ".join(skills_ref.keys())
            return f'技能 "{skill_name}" 不存在。可用的技能: {available}'

        return [list_skills, read_skill]


def create_agent(system_prompt, middleware=None, extra_tools=None, context=""):
    """
    创建一个带中间件的 ReAct Agent。

    Args:
        system_prompt: 系统提示词
        middleware:    SkillsMiddleware 实例列表
        extra_tools:   额外工具列表（如 [get_time, calc, gpu_status]）
        context:       对话历史字符串（可选，会追加到系统提示词后）
    Returns:
        AgentExecutor，支持 .stream() / .invoke()
    """
    from langchain.agents import AgentExecutor
    from langchain.agents import create_react_agent as _create_react
    from langchain_core.prompts import PromptTemplate

    from app.llm import llm
    from app.llm.agent import AGENT_TEMPLATE

    tools = list(extra_tools or [])
    if middleware:
        for m in middleware:
            if hasattr(m, "get_tools"):
                tools.extend(m.get_tools())

    full_prompt = system_prompt
    if context:
        full_prompt = system_prompt + "\n\n【对话历史】\n" + context

    prompt = PromptTemplate.from_template(AGENT_TEMPLATE).partial(system_prompt=full_prompt)
    agent = _create_react(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        handle_parsing_errors=True,
        max_iterations=15,
        early_stopping_method="force",
        max_execution_time=600,
    )
