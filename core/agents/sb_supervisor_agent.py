# reason_graph/supervisor_agent.py
from typing import  Callable, List, Optional, Union, cast, Literal
from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph
from langgraph.types import Checkpointer

# 内部导入
from core.agents.base.base_agent import BaseAgent
from core.agents.state_based_supervisor.state_schema import PlanningAgentState, StateSchemaType # 导入 PlanningAgentState
# 导入重构后的 create_supervisor 函数
from core.agents.state_based_supervisor.supervisor_graph import create_supervisor
from core.agents.state_based_supervisor.agent_name import AgentNameMode

import logging
logger = logging.getLogger(__name__)

class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent 类 (最终版)
    负责协调子 Agent 并管理规划 (使用状态驱动方法)。
    invoke/ainvoke 继承自 BaseAgent，负责完整流程。
    """

    def __init__(
        self,
        agents: List[BaseAgent], # 子 Agent 实例列表
        model: LanguageModelLike, # Supervisor 使用的 LLM
        tools: Optional[List[Union[BaseTool, Callable]]] = None, # Supervisor 特有工具
        state_schema: StateSchemaType = PlanningAgentState,
        supervisor_name: str = "supervisor",
        checkpointer: Optional[Checkpointer] = None,
        output_mode: str = "last_message",
        # enable_planning: bool = True, # 不再需要，强制使用 Planning
        include_agent_name: Optional[str] = "inline",
        # BaseAgent 参数
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = None,
        model_name: Optional[str] = None,
    ):
        """初始化 Supervisor Agent"""
        if state_schema != PlanningAgentState:
             print("Warning: SupervisorAgent forces state_schema to PlanningAgentState.")
             state_schema = PlanningAgentState

        self.sub_agents = agents
        self.output_mode = output_mode
        self.include_agent_name = cast(Optional[AgentNameMode], include_agent_name)

        # 初始化 BaseAgent 父类
        super().__init__(
            name=supervisor_name,
            model=model,
            tools=tools or [],
            checkpointer=checkpointer,
            prompt=None, # 核心 Prompt 在 supervisor_node_logic 中处理
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            model_name=model_name,
        )
        # _workflow_definition 和 _executable_agent 由 BaseAgent 管理

    def build(self) -> Optional[StateGraph]:
        """构建 Supervisor 的 LangGraph 工作流图定义。"""
        # 调用重构后的 create_supervisor 函数来获取 StateGraph 定义
        # 这个 StateGraph 包含了手写的 supervisor_node_logic
        if self._workflow: return self._workflow
        
        print(f"Building supervisor graph definition for '{self.name}'...")
        try:
            graph_definition = create_supervisor(
                model=self.model,
                sub_agents=self.sub_agents,
                state_schema=PlanningAgentState, # 强制使用
                tools=self.tools,
                output_mode=cast(Literal["full_history", "last_message"], self.output_mode),
                supervisor_name=self.name,
                include_agent_name=self.include_agent_name,
            )
            self._workflow = graph_definition # 存储图定义
            print(f"Supervisor graph definition built for '{self.name}'.")
            return self._workflow
        except Exception as e:
            print(f"!!! Error building supervisor graph definition '{self.name}': {e}")
            import traceback
            traceback.print_exc()
            self._workflow = None
            raise e

    # compile 方法继承自 BaseAgent
    # 它会调用上面的 build() 获取 StateGraph 定义，然后编译它，
    # 并创建包含预处理步骤的最终 _executable_agent

    # invoke, ainvoke, get_agent, reset 继承自 BaseAgent