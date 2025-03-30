import json
from typing import List, Dict, Any, Optional, Union, Callable, Sequence, TypeVar, cast
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from langgraph.types import Checkpointer
from langgraph.graph.graph import CompiledGraph
from langgraph.graph.state import CompiledStateGraph
import logging
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    print("Warning: Tiktoken not installed. Using naive token estimation.")

logger = logging.getLogger(__name__)
DEFAULT_MODEL_NAME = "gpt-4o-mini"

StateSchema = TypeVar("StateSchema", bound=Union[dict, Any])

class BaseAgent:
    def __init__(
        self,
        name: str,
        model: Union[BaseChatModel, LanguageModelLike],
        tools: Optional[List[Union[BaseTool, Callable]]] = None,
        prompt: Optional[Union[str, SystemMessage, Callable]] = None,
        checkpointer: Optional[Checkpointer] = None,
        max_context_messages: Optional[int] = None,  # Limit number of recent messages
        max_context_tokens: Optional[int] = None,    # Limit total estimated tokens
        model_name: Optional[str] = "gpt-4o-mini", # Optional, used for future token estimation improvements
        description: str = "No description provided."
        
    ):
        if max_context_messages and max_context_tokens:
            raise ValueError("Only one of max_context_messages or max_context_tokens should be set.")
        if name is None or name == "LangGraph":
             raise ValueError("Agent name must be specified.")

        self.name = name
        self.model = model
        self.tools = tools or []
        self.base_prompt = prompt
        self.checkpointer = checkpointer
        self.max_context_messages = max_context_messages
        self.max_context_tokens = max_context_tokens
        self.model_name = model_name or getattr(model, "model_name", DEFAULT_MODEL_NAME)
        self.description = description
        
        self._workflow: Optional[StateGraph] = None
        self._compiled_agent: Optional[CompiledGraph] = None # Stores the final compiled graph

        self._tokenizer = None
        if TIKTOKEN_AVAILABLE:
            try: self._tokenizer = tiktoken.encoding_for_model(self.model_name)
            except KeyError:
                try:
                     self._tokenizer = tiktoken.get_encoding("cl100k_base")
                     # print(f"Warning: Tiktoken encoding for model '{self.model_name}' not found. Using 'cl100k_base'.")
                except Exception as e: print(f"Error getting tiktoken encoding 'cl100k_base': {e}.")
            except Exception as e: print(f"Error initializing tiktoken for model '{self.model_name}': {e}.")


    def _estimate_tokens(self, message: BaseMessage) -> int:
        content_to_encode = ""
        if isinstance(message, (HumanMessage, SystemMessage, AIMessage)):
            if isinstance(message.content, str): content_to_encode = message.content
            elif isinstance(message.content, list):
                 for block in message.content:
                     if isinstance(block, dict) and block.get("type") == "text": content_to_encode += block.get("text", "") + "\n"
        elif isinstance(message, ToolMessage):
             content_to_encode = message.content if isinstance(message.content, str) else json.dumps(message.content)
        else: content_to_encode = str(message)
        if self._tokenizer:
            try: return len(self._tokenizer.encode(content_to_encode, disallowed_special=()))
            except Exception: pass
        return len(content_to_encode) // 2

   
    def _truncate_by_tokens(self, messages: Sequence[BaseMessage]) -> List[BaseMessage]:
        if not self.max_context_tokens: return list(messages)
        truncated_messages: List[BaseMessage] = []
        total_tokens = 0
        preserved_system_message: Optional[SystemMessage] = None
        # Check if the first message is a SystemMessage, preserve it if so
        # Note: This assumes only ONE leading SystemMessage should be preserved.
        if messages and isinstance(messages[0], SystemMessage):
            preserved_system_message = messages[0]
            messages_to_truncate = messages[1:]
            try: 
                system_tokens = self._estimate_tokens(preserved_system_message)
                # Only count if it doesn't exceed limit by itself
                if system_tokens <= self.max_context_tokens:
                     total_tokens += system_tokens
                else:
                     print(f"Warning: System message alone ({system_tokens} tokens) exceeds token limit ({self.max_context_tokens}). It might be truncated if context grows.")
                     # Don't add to total_tokens yet, let truncation logic handle it.
                     preserved_system_message = None # Don't preserve if it's too big initially

            except Exception: pass # Ignore errors estimating system message
        else:
            messages_to_truncate = messages

        # Iterate backwards from the most recent message
        for msg in reversed(messages_to_truncate):
            try:
                msg_tokens = self._estimate_tokens(msg)
                # Check if adding this message exceeds the limit
                if total_tokens + msg_tokens <= self.max_context_tokens:
                    truncated_messages.append(msg)
                    total_tokens += msg_tokens
                else:
                    print(f"Context Token Limit ({self.max_context_tokens}) reached. Truncating older messages.")
                    break # Limit reached
            except Exception as e:
                print(f"Warning: Failed to estimate tokens for message, skipping: {e}")
                continue

        # Re-add the system message at the beginning if it was preserved
        final_list = list(reversed(truncated_messages))
        if preserved_system_message:
             try: system_tokens = self._estimate_tokens(preserved_system_message)
             except Exception: system_tokens = 0
             # Ensure adding system message doesn't push over limit *again* (edge case)
             if total_tokens - (msg_tokens if 'msg_tokens' in locals() and total_tokens + msg_tokens > self.max_context_tokens else 0) + system_tokens <= self.max_context_tokens:
                 final_list.insert(0, preserved_system_message)
             elif not final_list: # If only system message fits
                 return [preserved_system_message]
             # Else: System message doesn't fit with the truncated history, omit it.

        return final_list


    def _truncate_messages(self, messages: Sequence[BaseMessage]) -> List[BaseMessage]:
        """根据配置（优先 token 数，其次消息数）截断消息历史。"""
        if self.max_context_tokens is not None:
            return self._truncate_by_tokens(messages)
        elif self.max_context_messages is not None:
            if messages and isinstance(messages[0], SystemMessage):
                # Keep system message + last N-1 messages
                keep_count = self.max_context_messages - 1
                return [messages[0]] + list(messages[-keep_count:]) if keep_count > 0 and len(messages) > 1 else [messages[0]]
            else:
                return list(messages[-self.max_context_messages:])
        return list(messages)

    def _get_state_value(self, state: StateSchema, key: str, default: Any = None) -> Any:
         return state.get(key, default) if isinstance(state, dict) else getattr(state, key, default)
    
    def _format_tools_for_prompt(self, tools: List[Union[BaseTool, Callable]]) -> str:
        """Formats the tool list for inclusion in the prompt."""
        if not tools:
            return "No tools available for use."
        # 使用 getattr 安全地访问 name 和 description
        return "\n".join([
            f"- **{getattr(t, 'name', 'Unnamed Tool')}**: {getattr(t, 'description', 'No description available.')}"
            for t in tools
        ])
        
    # --- build/compile/get_agent ---
    def build(self) -> Optional[StateGraph]:
        """构建 Agent 的 LangGraph 工作流图定义。子类应实现。"""
        raise NotImplementedError("Subclasses must implement build() or override compile() directly.")

    def compile(self) -> CompiledGraph:
        """编译 Agent 工作流。"""
        if self._compiled_agent is not None:
            return self._compiled_agent

        # 尝试调用 build() 来获取 StateGraph
        workflow = self.build()

        if workflow is None or not isinstance(workflow, StateGraph):
             # 如果 build() 不返回 StateGraph (例如 ReactAgent),
             # 子类的 compile() 需要被覆盖以处理编译
             raise ValueError(
                 f"Agent '{self.name}': build() did not return a valid StateGraph, "
                 "and compile() was not overridden to handle direct compilation."
             )

        print(f"Compiling graph for agent: {self.name}")
        try:
            # 编译 StateGraph 并存储结果
            self._compiled_agent = workflow.compile(
                 checkpointer=self.checkpointer,
                 debug=getattr(self, 'debug', False) # 传递 debug 标志
            )
            print(f"Graph compiled successfully for agent: {self.name}")
            return self._compiled_agent
        except Exception as e:
             print(f"!!! Error compiling graph for agent {self.name}: {e}")
             import traceback
             traceback.print_exc()
             raise e

    def get_agent(self) -> CompiledGraph:
         """获取编译后的核心图实例，如果未编译则先编译。"""
         if self._compiled_agent is None:
              print(f"Agent '{self.name}' not compiled yet. Compiling now.")
              self.compile()
         if self._compiled_agent is None:
              raise RuntimeError(f"Failed to get compiled agent for '{self.name}'.")
         return self._compiled_agent
        
    # --- invoke/ainvoke: 标准入口点，调用编译后的图 ---
    def invoke(self, state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        """同步调用编译后的 Agent 图。"""
        try:
            compiled_agent = self.get_agent() # 获取 (或编译) 图
            print(f"--- Invoking Agent: {self.name} ---")
            # 直接调用编译后的图，预处理由图内部的 prompt callable 处理 (如果使用 ReactAgent)
            # 或由 Supervisor 节点逻辑处理 (如果使用自定义 Supervisor)
            result = compiled_agent.invoke(state, config=config)
            print(f"--- Agent Invocation Complete: {self.name} ---")
            return cast(Dict[str, Any], result) # 假设返回字典
        except Exception as e:
            print(f"!!! Error during {self.name} agent invocation: {e}")
            import traceback
            traceback.print_exc()
            # 返回带错误标记的状态 (可能是输入状态)
            state["error"] = f"Agent invocation failed: {e}"
            return state

    async def ainvoke(self, state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        """异步调用编译后的 Agent 图。"""
        try:
            compiled_agent = self.get_agent() # 获取 (或编译) 图
            print(f"--- Invoking Agent Async: {self.name} ---")
            # 直接调用编译后的图
            result = await compiled_agent.ainvoke(state, config=config)
            print(f"--- Agent Invocation Complete Async: {self.name} ---")
            return cast(Dict[str, Any], result) # 假设返回字典
        except Exception as e:
            print(f"!!! Error during {self.name} agent async invocation: {e}")
            import traceback
            traceback.print_exc()
            state["error"] = f"Agent async invocation failed: {e}"
            return state

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Run the supervisor workflow synchronously.

        Args:
            state: The input state for the workflow

        Returns:
            The output state from the workflow
        """
        return self.invoke(state)
    
    async def arun(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Run the supervisor workflow asynchronously.
        Args:
            state: The input state for the workflow
        Returns:
            The output state from the workflow
        """
        return await self.ainvoke(state)

    def reset(self):
        """重置编译状态，强制下次重新编译。"""
        print(f"Resetting compiled graph for agent '{self.name}'. Will recompile on next use.")
        self._compiled_agent = None
        self._workflow = None

    def add_tools(self, tools: List[Union[BaseTool, Callable]]) -> None:
        """添加工具到 Agent 的工具列表。"""
        print(f"Warning: Adding tools to {self.name} post-initialization. Agent needs recompilation.")
        self.tools.extend(tools)
        self.reset()
