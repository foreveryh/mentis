# 文件路径示例: reason_graph/research_agent.py

from typing import Any, List, Optional, Union, Callable, Type, cast
from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import SystemMessage
from langgraph.types import Checkpointer

# 内部导入 - 请确保路径正确
from core.agents.base.react_agent import ReactAgent
# 导入工具 Registry 相关 - 只需要 get_tools_by_category 和 ToolCategory
from core.tools.registry import get_tools_by_category, ToolCategory
# *** 不再需要导入 get_tool 或 get_registered_tools ***

import logging
logger = logging.getLogger(__name__)

# 假设 ToolCategory 包含 SEARCH 和 WEB_Browse
if not hasattr(ToolCategory, 'SEARCH'): ToolCategory.SEARCH = ToolCategory.OTHER
if not hasattr(ToolCategory, 'WEB_Browse'): ToolCategory.WEB_Browse = ToolCategory.OTHER


class ResearchAgent(ReactAgent):
    """
    研究 Agent (重构版)
    - 继承自新的 ReactAgent
    - 专注于定义自身工具和 Prompt
    - 移除了自定义的状态管理和方法
    """

    def __init__(
        self,
        name: str = "research_expert",
        model: LanguageModelLike = None,
        tools: Optional[List[Union[BaseTool, Callable]]] = None,
        checkpointer: Optional[Checkpointer] = None,
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = 8000,
        debug: bool = False,
        **kwargs
    ):

        # 1. 定义 Agent 描述 (不变)
        description = "Expert at finding, extracting, and synthesizing the latest information, data, and background knowledge on specific topics using search engines (like Tavily, Google Search) and web Browse tools (like Firecrawl, Arxiv). Capable of providing source links and content summaries."

        # 2. --- 从 Registry 获取和合并工具 ---
        agent_tools: List[Union[BaseTool, Callable]] = []
        search_tools_loaded: List[Union[BaseTool, Callable]] = [] # 用于后续检查
        Browse_tools_loaded: List[Union[BaseTool, Callable]] = []

        try:
            search_tools_loaded = get_tools_by_category(ToolCategory.SEARCH)
            agent_tools.extend(search_tools_loaded)
            try:
                 Browse_tools_loaded = get_tools_by_category(ToolCategory.WEB_Browse)
                 agent_tools.extend(Browse_tools_loaded)
            except Exception as e:
                 if debug: print(f"[{name}] Info: Failed to get WEB_Browse tools: {e}")
            print(f"[{name}] Loaded tools from registry: {[t.name for t in agent_tools if hasattr(t,'name')]}")

            # --- 简化核心工具检查 ---
            if not search_tools_loaded: # 直接检查从 Registry 加载的搜索工具列表是否为空
                 print(f"CRITICAL Warning: ResearchAgent '{name}' initialized without any SEARCH tools from registry!")
            # ------------------------

        except Exception as e:
             print(f"Warning: Failed to get tools from registry for {name}: {e}")

        # 合并外部传入的 `tools` 参数 (逻辑不变)
        if tools:
            # ... (合并逻辑不变) ...
             existing_tool_names = {t.name for t in agent_tools if hasattr(t, 'name')}
             added_external_count = 0
             for tool in tools:
                 tool_name = getattr(tool, 'name', None)
                 if tool_name and tool_name not in existing_tool_names:
                      agent_tools.append(tool)
                      existing_tool_names.add(tool_name)
                      added_external_count +=1
                 elif not tool_name: 
                      agent_tools.append(tool)
                      added_external_count += 1
             if added_external_count > 0: print(f"[{name}] Merged {added_external_count} external tool(s).")


        # --- 简化最终工具检查 ---
        if not agent_tools:
             print(f"CRITICAL Warning: ResearchAgent '{name}' initialized with NO tools configured!")
        # 不再需要那个复杂的 any(...) 检查
        # ----------------------

        # 3. 定义 Agent 的 System Prompt (逻辑不变)
        base_prompt = f"""You are a professional Research Analyst expert...
Available Tools:
{self._format_tools_for_prompt(agent_tools)} 
Instructions:

- Analyze the request in the message history.

- If the request requires searching for current information, facts, data, or background knowledge, you MUST use one of your search tools (like 'tavily_search_results').

- When using tools, formulate concise and effective search queries based on the request.

- Synthesize the information found from the tools into a clear and informative answer.

- If you use information from a tool, cite the source implicitly in your response (e.g., "According to [Source Title], ...").

- If the initial search is insufficient, analyze the results and decide if further searches with refined queries or different tools are needed.

- If you cannot find the information after thorough searching, or if the tools return errors, clearly state the limitations encountered. Do not invent information.
"""

        # 4. 调用父类 __init__ (逻辑不变)
        super().__init__(
            name=name,
            model=model,
            tools=agent_tools,
            prompt=base_prompt,
            description=description,
            checkpointer=checkpointer,
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            debug=debug,
            **kwargs
        )
        print(f"ResearchAgent '{self.name}' initialized with final tools: {[t.name for t in self.tools if hasattr(t,'name')]}")
