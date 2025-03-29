# reason_graph/supervisor_graph.py
import inspect
import re
import functools
import uuid
from typing import Any, Callable, List, Optional, Type, Union, Dict, Literal, Sequence

from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage,ToolCall
from langchain_core.runnables import RunnableConfig

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.chat_agent_executor import (
    AgentState, # Keep for type hint compatibility if needed
    Prompt,
    StateSchemaType,
    StructuredResponseSchema,
)
from langgraph.pregel import Pregel
from langgraph.utils.runnable import RunnableCallable

# 内部导入
from core.agents.base.base_agent import BaseAgent
from .handoff import create_handoff_tool, create_handoff_back_messages, _normalize_agent_name
from .state_schema import PlanningAgentState # 使用包含 plan 的状态
from .supervisor_node import supervisor_node_logic # 导入新的节点逻辑
from .agent_name import AgentNameMode, with_agent_name

# 定义 OutputMode, MODELS_NO_PARALLEL_TOOL_CALLS, _supports_disable_parallel_tool_calls
OutputMode = Literal["full_history", "last_message"]
MODELS_NO_PARALLEL_TOOL_CALLS = {"o3-mini"} # 示例，可能需要更新

def _supports_disable_parallel_tool_calls(model: LanguageModelLike) -> bool:
    if not isinstance(model, BaseChatModel): return False
    if hasattr(model, "model_name") and model.model_name in MODELS_NO_PARALLEL_TOOL_CALLS: return False
    if not hasattr(model, "bind_tools"): return False
    if "parallel_tool_calls" not in inspect.signature(model.bind_tools).parameters: return False
    return True

# 定义 _make_call_agent
def _make_call_agent(
    agent_graph: Pregel, # 明确类型为 Pregel
    output_mode: OutputMode,
    add_handoff_back_messages: bool, # 参数现在明确为布尔值
    supervisor_name: str,
) -> RunnableCallable:
    """
    创建一个调用子 Agent 并处理其输出的 RunnableCallable。
    包含同步 (invoke) 和异步 (ainvoke) 实现。
    """
    if output_mode not in ["full_history", "last_message"]:
        raise ValueError(f"Invalid output mode: {output_mode}")

    # --- 异步实现 ---
    async def acall_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        """异步调用子 Agent"""
        agent_name = getattr(agent_graph, 'name', 'sub_agent') # 获取子 agent 图的名字
        print(f"🟡 [Async invoke] Handoff to agent '{agent_name}'")
        # 准备输入：通常子 Agent 只需要消息历史
        sub_agent_input = {"messages": state.get("messages", [])}
        
        try:
             # 调用子 Agent 图的 ainvoke
             output = await agent_graph.ainvoke(sub_agent_input, config=config)
             print(f"✅ [Async invoke] Agent '{agent_name}' completed.")
        except Exception as e:
             print(f"!!! Error during sub-agent {agent_name} ainvoke: {e}")
             # 返回错误信息或空消息列表
             error_content = f"Error executing agent '{agent_name}': {type(e).__name__}"
             # 可以考虑返回一个 ToolMessage 表示错误，但这需要 tool_call_id
             # 更简单的方式是返回空列表或特定错误消息
             # return {"messages": [SystemMessage(content=error_content)]} # 或返回空
             return {"messages": []}


        # --- 处理输出 ---
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        if not sub_agent_messages: return {"messages": []}

        returned_messages: List[BaseMessage] = []
        if output_mode == "last_message":
            last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
            returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else: # full_history
            returned_messages = sub_agent_messages

        # **重要**: 不在此处添加 handoff_back_messages。
        # Supervisor 在收到返回后，应该知道是哪个 agent 返回的，可以自行处理后续逻辑。

        # 只返回处理后的消息列表
        return {"messages": returned_messages}

    # --- 同步实现 ---
    def call_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        """同步调用子 Agent"""
        agent_name = getattr(agent_graph, 'name', 'sub_agent')
        print(f"🟡 [Sync invoke] Handoff to agent '{agent_name}'")
        sub_agent_input = {"messages": state.get("messages", [])}

        try:
            # 调用子 Agent 图的 invoke
            output = agent_graph.invoke(sub_agent_input, config=config)
            print(f"✅ [Sync invoke] Agent '{agent_name}' completed.")
        except NotImplementedError:
             # 如果子 Agent 图本身不支持同步 invoke (不太可能对于 Pregel)
             print(f"Error: Synchronous invoke not supported by agent '{agent_name}'.")
             return {"messages": []}
        except Exception as e:
            print(f"!!! Error during sub-agent {agent_name} invoke: {e}")
            return {"messages": []} # 返回空列表

        # --- 处理输出 (与异步版本逻辑相同) ---
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        if not sub_agent_messages: return {"messages": []}

        returned_messages: List[BaseMessage] = []
        if output_mode == "last_message":
             last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
             returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else: # full_history
             returned_messages = sub_agent_messages

        return {"messages": returned_messages}

    # --- 创建并返回 RunnableCallable ---
    # 同时提供同步 (func) 和异步 (afunc) 实现
    return RunnableCallable(func=call_agent, afunc=acall_agent, name=f"Call_{getattr(agent_graph, 'name', 'sub_agent')}")

# --- 重构后的 create_supervisor ---
def create_supervisor(
    model: LanguageModelLike, # Supervisor 的 LLM
    sub_agents: List[BaseAgent], # 子 Agent 列表 (BaseAgent 实例)
    state_schema: Type[PlanningAgentState] = PlanningAgentState, # 必须是 PlanningAgentState
    config_schema: Type[Any] | None = None,
    tools: list[BaseTool | Callable] | None = None, # Supervisor 可能有的其他工具 (除了 Handoff 和 Planning)
    prompt_template: Optional[str] = None, # Supervisor 的核心指令模板 (现在从 prompt.py 加载)
    output_mode: OutputMode = "last_message",
    add_handoff_back_messages: bool = False, # 通常设为 False，让 Supervisor 处理返回逻辑
    supervisor_name: str = "supervisor",
    include_agent_name: AgentNameMode | None = "inline", # 推荐使用 inline
) -> CompiledGraph: # 返回编译后的图
    """
    创建 Supervisor 图 (重构版)。
    Supervisor 节点使用手动逻辑处理规划状态更新和路由。
    """
    # 1. 提取子 Agent 名称和编译后的图实例 (Pregel)
    agent_graphs: Dict[str, Pregel] = {}
    agent_names: List[str] = []
    agent_description_map: Dict[str, str] = {}
    for agent in sub_agents:
        if not isinstance(agent, BaseAgent):
            raise TypeError(f"Agent {agent} is not an instance of BaseAgent.")
        if not agent.name or agent.name == "LangGraph":
            raise ValueError("Sub-agents must have unique, valid names.")
        if agent.name in agent_graphs:
            raise ValueError(f"Duplicate agent name found: {agent.name}")
        
        agent_names.append(agent.name)
        agent_description_map[agent.name] = getattr(agent, 'description', 'No description provided.') 
        try:
            # 调用 get_agent 来获取 (或编译) 子 Agent 的图
            compiled_graph = agent.get_agent()
            if not isinstance(compiled_graph, Pregel):
                 raise TypeError(f"Agent '{agent.name}'.get_agent() did not return a Pregel instance.")
            agent_graphs[agent.name] = compiled_graph
        except Exception as e:
             print(f"Error compiling or getting agent '{agent.name}': {e}")
             raise e # 重新抛出错误

    # 2. 创建 Handoff 工具
    handoff_tools = [create_handoff_tool(agent_name=name) for name in agent_names]
    all_supervisor_tools = (tools or []) + handoff_tools

    # 3. 绑定工具到 Supervisor 模型
    # 注意：Supervisor 现在不直接使用 PlanningTool 了
    if _supports_disable_parallel_tool_calls(model):
        bound_supervisor_model = model.bind_tools(all_supervisor_tools, parallel_tool_calls=False)
    else:
        bound_supervisor_model = model.bind_tools(all_supervisor_tools)

    # 4. (可选) 添加 Agent 名称处理
    if include_agent_name:
        bound_supervisor_model = with_agent_name(bound_supervisor_model, include_agent_name)

    # 5. 构建 StateGraph
    builder = StateGraph(state_schema, config_schema=config_schema)

    # 6. 添加 Supervisor 节点 (使用手动逻辑)
    # 将需要传递给节点逻辑的参数固定
    supervisor_logic_partial = functools.partial(
        supervisor_node_logic,
        model=bound_supervisor_model,
        supervisor_name=supervisor_name,
        agent_description_map=agent_description_map,
    )
    builder.add_node(supervisor_name, supervisor_logic_partial)
    builder.add_edge(START, supervisor_name)

    # 7. 添加子 Agent 节点和返回边
    for name, compiled_graph in agent_graphs.items():
        builder.add_node(
            name,
            _make_call_agent(
                compiled_graph,
                output_mode,
                add_handoff_back_messages, # 通常为 False
                supervisor_name,
            ),
        )
        # 子 Agent 完成后总是返回给 Supervisor
        builder.add_edge(name, supervisor_name)
    
    # --- 添加 Handoff Tool 执行节点 ---
    handoff_executor_node = ToolNode(handoff_tools, name="HandoffExecutor")
    builder.add_node("handoff_executor", handoff_executor_node)
    
    # 8. 添加从 Supervisor 出发的条件边进行路由
    def route_from_supervisor(state: PlanningAgentState) -> Union[str, List[str]]:
        """根据 Supervisor 的最新消息决定路由 (修正版)。"""
        messages = state.get('messages', [])
        plan = state.get('plan')
        last_message = messages[-1] if messages else None

        if not isinstance(last_message, AIMessage):
            return supervisor_name # 异常，返回 Supervisor

        # 1. 检查是否有 Tool 调用 (应该是 Handoff 工具)
        if last_message.tool_calls:
            # 路由到 Handoff 执行节点
            print("Routing: Supervisor -> HandoffExecutor")
            return "handoff_executor" 
            
        # 2. 如果没有 Tool 调用，检查 Plan 是否完成
        if plan and plan.get("status") == "completed":
             print("Routing: Plan completed -> END")
             return END

        # 3. 如果没有 Tool 调用，Plan 未完成，检查是否有 Plan 更新指令刚被处理
        #    (这需要 supervisor_node_logic 返回的信息，或者比较 plan 状态)
        #    简单起见：如果没有工具调用且计划未完成，都认为是最终答案或需要 S V 再思考
        #    修改：如果 supervisor_node_logic 更新了 plan，它应该继续 loop 回 supervisor
        #    如果 supervisor_node_logic 没更新 plan 且没调用 tool，则 END
        #    这个逻辑最好放在 supervisor_node_logic 返回值或 route_from_supervisor 中判断
        #    我们假设如果 LLM 回复里有 PLAN_UPDATE，则需要再思考；否则是最终答案

        content = last_message.content
        if isinstance(content, str) and "PLAN_UPDATE:" in content.upper():
            print("Routing: Plan directive detected in last message, looping supervisor.")
            return supervisor_name # 让 Supervisor 基于新计划状态再决策

        # 4. 否则，认为是最终直接回复
        print("Routing: No tool call, no plan update directive, plan not completed. Assuming final answer -> END.")
        return END

    builder.add_conditional_edges(supervisor_name, route_from_supervisor)

    return builder # 返回 StateGraph 实例，让 SupervisorAgent.compile 处理