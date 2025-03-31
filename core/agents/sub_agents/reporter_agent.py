# 文件路径: reason_graph/reporter_agent.py

import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Type, cast, Sequence

# --- LangChain / LangGraph ---
from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from langchain_core.runnables import RunnableConfig, Runnable
from langgraph.graph import StateGraph, END, START # 导入 StateGraph, END, START
from langgraph.graph.graph import CompiledGraph
from langgraph.types import Checkpointer

# --- 内部导入 ---
from core.agents.base.base_agent import BaseAgent # 导入最终版 BaseAgent
# 导入最终报告的 Prompt 模板

import logging
logger = logging.getLogger(__name__)

class ReporterAgent(BaseAgent):
    """
    报告 Agent (最终版)
    - 继承自 BaseAgent。
    - 负责基于完整的消息历史和明确指令生成最终 Markdown 报告。
    - 内部包含一个简单的图用于执行报告生成任务。
    """

    FINAL_REPORT_SYSTEM_PROMPT_TEMPLATE = """You are a professional writer and editor AI assistant. Your primary goal is to generate high-quality, well-structured text content based on the specific instructions provided in the latest message and the relevant information available in the preceding conversation history.

The current date is {current_date}.

**Your Task Execution Workflow:**
1.  **Identify Instructions:** Carefully read the **last message** you received, which contains the specific writing task assigned to you by the supervisor. Understand the desired output (e.g., summary, report section, full report), format, tone, and any other requirements.
2.  **Gather Context:** Review the preceding messages in the conversation history to find the necessary information, data points, findings, or creative elements needed to complete the assigned task.
3.  **Compose Output:** Write the text according to the instructions.
    * If asked for creative content (like a poem), focus on fulfilling the creative request.
    * If asked for a summary or section, synthesize the relevant information concisely and accurately.
    * If asked to compile a **full report**, structure it logically (e.g., Introduction, Body, Conclusion), use Markdown formatting effectively, and incorporate information/citations from the history as instructed. Adhere to any specified length or style guidelines.
4.  **Final Response:** Your output should be **only** the requested written text. Do not add extra conversational phrases unless necessary for context. Do not include planning directives or attempt to call tools (unless a specific writing/editing tool was provided and instructed for use). If you cannot fulfill the request due to missing information in the history, state that clearly.
"""


    def __init__(
        self,
        name: str = "reporter_expert",
        model: LanguageModelLike = None, # 应传入适合长文本生成的模型
        checkpointer: Optional[Checkpointer] = None,
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = 16000, # 报告生成可能需要处理长上下文
        debug: bool = False,
        prompt_template: str = FINAL_REPORT_SYSTEM_PROMPT_TEMPLATE, # 使用最终报告模板
        **kwargs # 接收其他 BaseAgent 参数
    ):
        # 1. 定义 Agent 描述 (给 Supervisor 看)
        description = "Synthesizes information from the complete conversation history and task results into a final, comprehensive, well-structured, and potentially cited Markdown research report, following specific instructions."

        # 2. 定义工具列表 (Reporter 通常不需要工具)
        agent_tools = []

        # 3. 存储基础 Prompt 模板 (将在节点逻辑中使用)
        # 注意：我们将模板本身（或其引用）存储起来，而不是格式化后的 prompt
        self.report_prompt_template = prompt_template

        # 4. 调用父类 __init__
        super().__init__(
            name=name,
            model=model, # 传入用于报告生成的 LLM
            tools=agent_tools,
            prompt=None, # BaseAgent 的 prompt 字段不直接用于此 Agent 的核心逻辑
            description=description,
            checkpointer=checkpointer,
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            # **kwargs 传递 debug 等
            **kwargs
        )
        print(f"ReporterAgent '{self.name}' initialized.")


    async def _generate_report_node_logic(self, state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
        """报告生成节点的核心逻辑"""
        # 注意：这里的 state 已经是经过 BaseAgent._preprocess_state 处理后的状态
        print(f"--- Entering Node: {self.name}._generate_report_node_logic ---")

        messages: List[BaseMessage] = state.get("messages", [])
        # 理论上，所有需要的信息都应该在 messages 历史中，
        # 特别是 Supervisor 委派时的最后一条指令消息。

        if not messages:
             error_msg = "Error: No messages found in state for report generation."
             print(error_msg)
             return {"messages": [AIMessage(content=f"# Report Generation Failed\n\n{error_msg}", name=self.name)]}

        # --- 格式化 System Prompt (包含日期) ---
        try:
            current_date_str = datetime.now().strftime("%a, %b %d, %Y")
            system_prompt = self.report_prompt_template.format(current_date=current_date_str)
        except Exception as e:
            print(f"Error formatting report system prompt: {e}")
            system_prompt = "You are a report writing assistant. Synthesize the provided messages into a final report." # Fallback

        # --- 准备 LLM 输入 ---
        # 输入是 System Prompt + 完整的、经过预处理（截断）的消息历史
        # BaseAgent 的 _preprocess_state 已经处理了截断
        llm_input_messages = [SystemMessage(content=system_prompt)] + messages

        # --- 调用 LLM 生成报告 ---
        final_report_markdown = ""
        llm_error = None
        try:
            print(f"--- Calling LLM for Final Report Generation ({self.name}) ---")
            # 使用 self.model (初始化时传入的 LLM 实例)
            response = await self.model.ainvoke(llm_input_messages, config=config)
            final_report_markdown = response.content
            print(f"--- Report Generation LLM Call Successful ({self.name}). Length: {len(final_report_markdown)} chars ---")
        except Exception as e:
             print(f"!!! Error during Report Generation LLM call ({self.name}): {e}")
             llm_error = f"Report generation failed due to LLM error: {e}"
             final_report_markdown = f"# Report Generation Failed\n\nError: {str(e)}"
             # 可以在这里打印更详细的 traceback
             # import traceback
             # traceback.print_exc()

        # --- 返回包含报告或错误的状态更新 ---
        # Reporter 的最终输出就是报告本身，放入 messages 中，替换掉历史？
        # 不，应该追加，让调用者（Supervisor 或 main）能看到完整历史和最终报告
        # 使用 AIMessage 返回报告
        return {
            "messages": [AIMessage(content=final_report_markdown, name=self.name)],
            "error": state.get("error") or llm_error # 保留或记录错误
        }

    def build(self) -> Optional[StateGraph]:
        """构建 Reporter Agent 的简单工作流： Start -> GenerateReport -> End """
        if self._workflow: return self._workflow

        print(f"Building internal graph for ReporterAgent '{self.name}'")
        # Reporter 通常使用 BasicAgentState，因为它不直接操作 Plan
        # 但为了兼容 Supervisor 可能传递 PlanningAgentState，这里可以暂时用 Any
        # 或者定义一个 ReporterState
        workflow = StateGraph(Dict[str, Any]) # 使用通用字典状态，因为它只关心 messages

        # 添加报告生成节点，确保它能访问 self.model
        # functools.partial 不能直接用于异步实例方法，需要包装
        async def node_wrapper(state, config):
             return await self._generate_report_node_logic(state, config)

        workflow.add_node("generate_report", node_wrapper) # type: ignore
        workflow.add_edge(START, "generate_report")
        workflow.add_edge("generate_report", END)

        self._workflow = workflow
        return workflow

    # compile 方法继承自 BaseAgent
    # 它会调用上面的 build() 获取 StateGraph 定义，然后编译它，
    # 并创建包含预处理步骤 (_preprocess_state) 的最终 _executable_agent

    # invoke, ainvoke, get_agent (get_executable_agent), reset 继承自 BaseAgent