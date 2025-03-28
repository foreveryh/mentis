from typing import Any, Callable, Dict, List, Optional, Type, Union, Literal, Sequence

from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph
from langgraph.graph.graph import CompiledGraph
from langgraph.types import Checkpointer
from langgraph.store.base import BaseStore
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import (
    AgentState,
    StateSchemaType,
    StructuredResponseSchema,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph.utils.runnable import RunnableCallable
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
            checkpointer=checkpointer,
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            model_name=model_name
        )
        
        # Initialize ReactAgent specific attributes
        self.response_format = response_format
        self.state_schema = state_schema
        self.config_schema = config_schema
        self.store = store
        self.interrupt_before = interrupt_before
        self.interrupt_after = interrupt_after
        self.debug = debug
        self.version = version
        self._agent:Optional[CompiledGraph] = None
    
    def compile(self) -> CompiledGraph:
        """Build the ReAct agent workflow.
        
        Returns:
            The built CompiledGraph
        """
        # 如果_app已经存在，直接返回，避免重复构建
        if self._agent is not None:
            return self._agent
            
        _react_agent = create_react_agent(
            model=self.model,
            tools=self.tools,
            prompt=self.prompt,
            response_format=self.response_format,
            state_schema=self.state_schema,
            config_schema=self.config_schema,
            checkpointer=self.checkpointer,
            store=self.store,
            interrupt_before=self.interrupt_before,
            interrupt_after=self.interrupt_after,
            debug=self.debug,
            version=self.version,
            name=self.name,
        )
        print(f"[[DEBUG]] {self.name}.compile() was called.")
        self._agent = CreateReactAgentWrapper(_react_agent, 
                                              name=self.name,
                                              before_invoke=self.invoke,
                                              before_ainvoke=self.ainvoke)
        return self._agent