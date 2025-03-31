from typing import Any, Callable, Dict, List, Optional, Type, Union, Literal, Sequence

from langchain_core.language_models import LanguageModelLike, LanguageModelInput
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph
from langgraph.graph.graph import CompiledGraph
from langgraph.types import Checkpointer
from langgraph.store.base import BaseStore
from langchain_core.messages import BaseMessage, SystemMessage # 导入 SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import (
    AgentState,
    StateSchemaType,
    StructuredResponseSchema,
)
from core.agents.base.base_agent import BaseAgent
from core.agents.base.create_react_agent_wrapper import CreateReactAgentWrapper
import logging
logger = logging.getLogger(__name__)

class ReactAgent(BaseAgent):
    """ReAct Agent class for reasoning and acting with tools.
    
    This class provides a high-level interface for creating a ReAct agent workflow
    that can perform multi-step reasoning and tool calling.
    """
    
    def __init__(
        self,
        model: LanguageModelLike,
        tools: Optional[List[Union[BaseTool, Callable]]] = None,
        prompt: Optional[str] = None,
        response_format: Optional[
            Union[StructuredResponseSchema, tuple[str, StructuredResponseSchema]]
        ] = None,
        state_schema: StateSchemaType = AgentState,
        config_schema: Type[Any] = None,
        checkpointer: Optional[Checkpointer] = None,
        store: Optional[BaseStore] = None,
        interrupt_before: Optional[List[str]] = None,
        interrupt_after: Optional[List[str]] = None,
        debug: bool = False,
        version: Literal["v1", "v2"] = "v1",
        name: str = "react_agent",
        description: str = "ReAct agent for reasoning and acting with tools.",
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = None,
        model_name: Optional[str] = "gpt-4o-mini",
    ):
        """Initialize a ReAct agent.
        
        Args:
            model: Language model to use for the agent
            tools: Optional list of tools available to the agent
            prompt: Optional prompt to use for the agent
            response_format: Optional schema for structured output
            state_schema: State schema to use for the agent graph
            config_schema: Optional schema for configuration
            interrupt_before: Optional list of nodes to interrupt before execution
            interrupt_after: Optional list of nodes to interrupt after execution
            debug: Whether to enable debug mode
            version: Version of the ReAct agent ("v1" or "v2")
            name: Name of the agent
            max_context_messages: Optional limit on number of recent messages
            max_context_tokens: Optional limit on total estimated tokens
            model_name: Optional model name for token estimation
        """
        # Call BaseAgent's __init__ to initialize parent class attributes
        super().__init__(
            name=name,
            model=model,
            tools=tools or [],
            prompt=prompt,
            description=description,
            checkpointer=checkpointer,
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            model_name=model_name
        )
        
        # Initialize ReactAgent specific attributes
        self.response_format = response_format
        self.react_state_schema = state_schema
        self.react_config_schema = config_schema
        self.react_store = store
        self.react_interrupt_before = interrupt_before
        self.react_interrupt_after = interrupt_after
        self.react_debug = debug
        self.react_version = version

    def _prepare_llm_input(self, state: Dict[str, Any]) -> LanguageModelInput:
        """
        准备 LLM 输入：截断消息历史并添加基础 System Prompt (如果存在)。
        作为 Callable 传递给 create_react_agent 的 prompt 参数。
        """
        # 1. 从状态获取消息 (BaseAgent 的方法)
        messages = self._get_state_value(state, "messages", [])
        
        # 2. 截断消息 (BaseAgent 的方法)
        # 注意：这里截断的是进入 LLM 前的列表，checkpointer 中的完整历史不受影响
        # --- 添加 Debug 打印 (截断前) ---
        # print(f"\nDEBUG _prepare_llm_input ({self.name}): BEFORE truncation (length {len(messages)}):")
        # for i, msg in enumerate(messages[-5:]): # 只看最后几条
        #     print(f"  Msg {i-5}: Type={type(msg).__name__}, ToolCallID={getattr(msg, 'tool_call_id', 'N/A')}")
        # ---

        truncated_messages = self._truncate_messages(messages)

        # --- 添加 Debug 打印 (截断后) ---
        # print(f"DEBUG _prepare_llm_input ({self.name}): AFTER truncation (length {len(truncated_messages)}):")
        # for i, msg in enumerate(truncated_messages[-5:]): # 只看最后几条
        #     print(f"  Msg {i-5}: Type={type(msg).__name__}, ToolCallID={getattr(msg, 'tool_call_id', 'N/A')}")
        # ---
        
        # 3. 添加基础 System Prompt (如果存在)
        final_messages: List[BaseMessage] = []
        if self.base_prompt:
            if isinstance(self.base_prompt, str):
                final_messages.append(SystemMessage(content=self.base_prompt))
            elif isinstance(self.base_prompt, SystemMessage):
                 final_messages.append(self.base_prompt)
            # 如果 self.base_prompt 是其他 Runnable 或 Callable，需要相应处理
            # 但 create_react_agent 的 prompt 通常是 str 或 SystemMessage
            
        final_messages.extend(truncated_messages)
        
        # print(f"DEBUG [{self.name}]: Preparing LLM input with {len(final_messages)} messages.") # Optional debug log
        # 返回最终的消息列表给 LLM
        return final_messages
    
    def build(self) -> Optional[StateGraph]:
        """对于 ReactAgent，核心图由 create_react_agent 直接创建，无需 build。"""
        print(f"Note: ReactAgent '{self.name}' uses create_react_agent in compile(). Build returns None.")
        self._workflow = None
        return None
    
    def compile(self) -> CompiledGraph:
        """使用 create_react_agent 构建并编译核心 ReAct 工作流，存储在 _compiled_agent。"""
        if self._compiled_agent is not None:
            return self._compiled_agent

        print(f"[[DEBUG]] Compiling core ReAct agent for: {self.name} using create_react_agent")
        try:
            # 使用 create_react_agent 创建编译后的图
            # 将 self._prepare_llm_input 作为 prompt callable 传入
            compiled_agent = create_react_agent(
                model=self.model,
                tools=self.tools,
                prompt=self._prepare_llm_input, # <--- 关键改动：传入准备函数
                state_schema=self.react_state_schema,
                config_schema=self.react_config_schema,
                checkpointer=self.checkpointer,
                store=self.react_store,
                interrupt_before=self.react_interrupt_before,
                interrupt_after=self.react_interrupt_after,
                debug=self.react_debug,
                version=self.react_version,
                name=self.name,
            )
            # 存储编译好的图
            self._compiled_agent = compiled_agent
            print(f"Core ReAct graph compiled successfully for agent: {self.name}")
            return self._compiled_agent
        except Exception as e:
             print(f"!!! Error compiling graph for agent {self.name} using create_react_agent: {e}")
             import traceback
             traceback.print_exc()
             self._compiled_agent = None
             raise e