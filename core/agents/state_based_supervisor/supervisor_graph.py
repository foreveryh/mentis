# reason_graph/supervisor_graph.py
import inspect
import re
import functools
import uuid
import asyncio # <--- 导入 asyncio
import anyio   # <--- 导入 anyio (需要 pip install anyio)
from typing import Any, Callable, List, Optional, Type, Union, Dict, Literal, Sequence, cast # <--- 导入 cast

from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage, ToolCall, SystemMessage # <--- 导入 SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.utils.runnable import RunnableCallable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
# from langgraph.prebuilt.chat_agent_executor import AgentState, Prompt, StateSchemaType, StructuredResponseSchema # 可能不再需要
from langgraph.pregel import Pregel

# 内部导入
try:
    from core.agents.base.base_agent import BaseAgent
    from .handoff import create_handoff_tool, _normalize_agent_name # 确保导入 _normalize_agent_name
    from .state_schema import PlanningAgentState, Plan # 导入 PlanningAgentState 和 Plan
    from .supervisor_node import supervisor_node_logic # 导入异步节点逻辑
    from .agent_name import AgentNameMode, with_agent_name
except ImportError as e:
     print(f"Error importing modules in supervisor_graph.py: {e}")
     # Add Dummy classes for type hints if needed
     class BaseAgent: pass
     class PlanningAgentState(Dict): pass
     class Plan(Dict): pass
     class Pregel: pass
     AgentNameMode = Literal["inline"]
     def create_handoff_tool(*args, **kwargs): return None # type: ignore
     def _normalize_agent_name(s: str) -> str: return s
     async def supervisor_node_logic(*args, **kwargs): return {}
     def with_agent_name(model, mode): return model


# 定义 OutputMode, MODELS_NO_PARALLEL_TOOL_CALLS, _supports_disable_parallel_tool_calls (保持不变)
OutputMode = Literal["full_history", "last_message"]
MODELS_NO_PARALLEL_TOOL_CALLS = {"o3-mini"}
def _supports_disable_parallel_tool_calls(model: LanguageModelLike) -> bool:
    # ... (实现保持不变) ...
    if not isinstance(model, BaseChatModel): return False
    if hasattr(model, "model_name") and model.model_name in MODELS_NO_PARALLEL_TOOL_CALLS: return False
    if not hasattr(model, "bind_tools"): return False
    if "parallel_tool_calls" not in inspect.signature(model.bind_tools).parameters: return False
    return True


# _make_call_agent (保持不变 - 已支持同步/异步)
def _make_call_agent(
    agent_graph: Pregel, 
    output_mode: OutputMode,
    add_handoff_back_messages: bool, 
    supervisor_name: str,
) -> RunnableCallable:
    # ... (之前的包含 call_agent 和 acall_agent 的版本保持不变) ...
    async def acall_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        agent_name = getattr(agent_graph, 'name', 'sub_agent')
        print(f"🟡 [Async invoke] Handoff to agent '{agent_name}'")
        sub_agent_input = {"messages": state.get("messages", [])}
        try: output = await agent_graph.ainvoke(sub_agent_input, config=config); print(f"✅ [Async invoke] Agent '{agent_name}' completed.")
        except Exception as e: print(f"!!! Error during sub-agent {agent_name} ainvoke: {e}"); return {"messages": []}
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        if not sub_agent_messages: return {"messages": []}
        returned_messages: List[BaseMessage] = []
        if output_mode == "last_message":
            last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
            returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else: returned_messages = sub_agent_messages
        return {"messages": returned_messages}
    def call_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        agent_name = getattr(agent_graph, 'name', 'sub_agent')
        print(f"🟡 [Sync invoke] Handoff to agent '{agent_name}'")
        sub_agent_input = {"messages": state.get("messages", [])}
        try: output = agent_graph.invoke(sub_agent_input, config=config); print(f"✅ [Sync invoke] Agent '{agent_name}' completed.")
        except NotImplementedError: print(f"Error: Sync invoke not supported by agent '{agent_name}'."); return {"messages": []}
        except Exception as e: print(f"!!! Error during sub-agent {agent_name} invoke: {e}"); return {"messages": []}
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        if not sub_agent_messages: return {"messages": []}
        returned_messages: List[BaseMessage] = []
        if output_mode == "last_message":
             last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
             returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else: returned_messages = sub_agent_messages
        return {"messages": returned_messages}
    return RunnableCallable(func=call_agent, afunc=acall_agent, name=f"Call_{getattr(agent_graph, 'name', 'sub_agent')}")


# --- 新增：supervisor_node_logic 的同步包装器 ---
def supervisor_node_logic_sync(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any,
    supervisor_name: str,
    agent_description_map: Dict[str, str]
) -> Dict[str, Any]:
    """supervisor_node_logic 的同步包装器，使用 anyio"""
    print(f"--- Entering Supervisor Node (Sync Wrapper) ---")
    try:
        # 使用 anyio 在同步函数中运行异步函数
        # 这适用于从非异步上下文调用 .invoke() 的情况
        return anyio.run( # type: ignore
            supervisor_node_logic, state, config, model, supervisor_name, agent_description_map
        )
    except Exception as e:
        print(f"Error running supervisor_node_logic synchronously using anyio: {e}")
        import traceback
        traceback.print_exc()
        # 返回错误状态
        return {"error": f"Sync execution wrapper failed: {e}", "messages": state.get("messages",[])}


# --- 最终版 create_supervisor ---
def create_supervisor(
    model: LanguageModelLike,
    sub_agents: List[BaseAgent],
    state_schema: Type[PlanningAgentState] = PlanningAgentState,
    config_schema: Type[Any] | None = None,
    tools: list[BaseTool | Callable] | None = None,
    output_mode: OutputMode = "last_message",
    add_handoff_back_messages: bool = False,
    supervisor_name: str = "supervisor",
    include_agent_name: AgentNameMode | None = "inline",
) -> StateGraph: # 返回 StateGraph 定义，让调用者编译
    """
    创建 Supervisor 图 (最终版)。
    Supervisor 节点使用手动逻辑，并提供同步/异步支持。
    使用 ToolNode 处理 Handoff。
    """
    # --- 1. 提取 Agent 名称、描述、编译图 (保持不变) ---
    agent_graphs: Dict[str, Pregel] = {}
    agent_names: List[str] = [] # 改回 List 可能更方便 (虽然 set 也可以)
    agent_description_map: Dict[str, str] = {}
    for agent in sub_agents:
        if not isinstance(agent, BaseAgent): raise TypeError(...)
        if not agent.name or agent.name == "LangGraph": raise ValueError(...)
        if agent.name in agent_graphs: raise ValueError(...)
        agent_names.append(agent.name)
        agent_description_map[agent.name] = getattr(agent, 'description', '...')
        try:
            compiled_graph = agent.get_agent() # 应该返回最终 Runnable
            # 之前假设是 Pregel，但 BaseAgent.get_agent 现在返回 Runnable (Sequence)
            # _make_call_agent 需要 Pregel...
            # 修正: _make_call_agent 应该接收 BaseAgent 实例，并在内部 get_agent()
            # 或者 BaseAgent.get_agent() 返回编译后的 Pregel 图 (而不是 Sequence)
            # 回到让 BaseAgent.get_agent 返回 self._compiled_agent
            # BaseAgent.compile 创建 self._executable_agent = prep | self._compiled_agent
            # 让 get_agent 返回 _compiled_agent
            
            # **修正 BaseAgent.get_agent 返回类型**
            # 在 BaseAgent 中:
            # def get_agent(self) -> CompiledGraph:
            #      if self._compiled_core_agent is None: self.compile() # Compile should create it
            #      if self._compiled_core_agent is None: raise RuntimeError(...)
            #      return self._compiled_core_agent
            
            # 假设 get_agent() 返回 CompiledGraph / Pregel
            if not isinstance(compiled_graph, Pregel): 
                 # 尝试从可执行 runnable 中获取核心 Pregel 图
                 core_graph = getattr(compiled_graph, 'last', None) # Sequence 的最后一个元素
                 if isinstance(core_graph, Pregel):
                      compiled_graph = core_graph
                 else:
                      raise TypeError(f"Could not retrieve Pregel instance from agent '{agent.name}'.get_agent()")

            agent_graphs[agent.name] = compiled_graph # 存 Pregel
        except Exception as e: raise e

    # --- 2. 创建 Handoff 工具 (保持不变) ---
    handoff_tools = [create_handoff_tool(agent_name=name) for name in agent_names]
    supervisor_callable_tools = (tools or []) + handoff_tools
    print(f"Supervisor '{supervisor_name}' bound with tools: {[t.name for t in supervisor_callable_tools]}")

    # --- 3. 绑定工具到 Supervisor 模型 (保持不变) ---
    bound_supervisor_model: LanguageModelLike
    if not supervisor_callable_tools:
         print(f"Warning: Supervisor '{supervisor_name}' has no tools bound.")
         bound_supervisor_model = model
    elif _supports_disable_parallel_tool_calls(model):
        bound_supervisor_model = model.bind_tools(supervisor_callable_tools, parallel_tool_calls=False)
    else:
        bound_supervisor_model = model.bind_tools(supervisor_callable_tools)
    if include_agent_name:
        bound_supervisor_model = with_agent_name(bound_supervisor_model, include_agent_name)

    # --- 4. 构建 StateGraph ---
    builder = StateGraph(state_schema, config_schema=config_schema)

    # --- 5. 添加 Supervisor 节点 (提供同步/异步包装) ---
    supervisor_logic_partial_async = functools.partial(
        supervisor_node_logic, # 异步核心逻辑
        model=bound_supervisor_model,
        supervisor_name=supervisor_name,
        agent_description_map=agent_description_map,
    )
    supervisor_logic_partial_sync = functools.partial(
        supervisor_node_logic_sync, # 同步包装器
        model=bound_supervisor_model,
        supervisor_name=supervisor_name,
        agent_description_map=agent_description_map,
    )
    # 使用 RunnableCallable 提供 func 和 afunc
    supervisor_runnable = RunnableCallable(
        func=supervisor_logic_partial_sync, # type: ignore
        afunc=supervisor_logic_partial_async, # type: ignore
        name=supervisor_name
    )
    builder.add_node(supervisor_name, supervisor_runnable) # <--- 使用 RunnableCallable
    builder.add_edge(START, supervisor_name)
    # ---

    # --- 6. 添加子 Agent 节点和返回边 (保持不变) ---
    for name, compiled_graph in agent_graphs.items():
        builder.add_node( name, _make_call_agent( compiled_graph, output_mode, add_handoff_back_messages, supervisor_name ) )
        builder.add_edge(name, supervisor_name)

    # --- 7. 添加 Handoff Tool 执行节点 (保持不变) ---
    handoff_executor_node = ToolNode(handoff_tools, name="HandoffExecutor")
    builder.add_node("handoff_executor", handoff_executor_node)

    # --- 8. 添加 Supervisor 的条件路由 (修正版) ---
    def route_from_supervisor(state: PlanningAgentState) -> str:
        """根据 Supervisor 最新消息和 Plan 状态决定路由 (修正版)"""
        messages = state.get('messages', [])
        plan = state.get('plan')
        last_message = messages[-1] if messages else None

        if not isinstance(last_message, AIMessage):
            print("Routing: Last message not AIMessage, looping supervisor.")
            return supervisor_name

        # 1. 检查 Tool 调用 (Handoff)
        if last_message.tool_calls:
            tool_call = last_message.tool_calls[0]
            agent_name_match = re.match(r"transfer_to_(\w+)", tool_call["name"])
            
            # **关键修正**: 直接使用闭包中的 agent_names 列表/集合
            if agent_name_match and agent_name_match.group(1) in agent_names: 
                 extracted_name = agent_name_match.group(1)
                 # 使用 repr() 打印以检查隐藏字符
                 print(f"DEBUG route_from_supervisor: Tool Call Name = {repr(tool_call['name'])}") 
                 print(f"DEBUG route_from_supervisor: Extracted Target Name = {repr(extracted_name)}") 
                 print(f"DEBUG route_from_supervisor: Available Agent Names = {repr(agent_names)}") 
                 print(f"Routing: Supervisor -> HandoffExecutor (for {extracted_name})")
                 return "handoff_executor" # <--- 正确路由到 ToolNode
            else:
                 print(f"DEBUG route_from_supervisor: Membership check failed! ('{extracted_name}' in {repr(agent_names)}) is False.")
                 print(f"Warning: Supervisor called unknown/invalid tool: {tool_call['name']}. Looping supervisor.")
                 return supervisor_name

        # 2. 检查 Plan 是否完成
        if plan and plan.get("status") == "completed":
             print("Routing: Plan completed -> END")
             return END

        # 3. 检查是否有 Plan 更新指令 (表明需要 Supervisor 再次评估)
        content = last_message.content
        if isinstance(content, str) and "PLAN_UPDATE:" in content.upper():
            print("Routing: Plan directive detected, looping supervisor.")
            return supervisor_name

        # 4. 否则，认为是最终直接回复或等待（在此简化流程中都结束）
        print("Routing: No tool call, no plan update, plan not completed. Assuming final answer/end of turn -> END.")
        return END

    # --- 添加条件边，并提供完整的映射 ---
    builder.add_conditional_edges(
        supervisor_name,
        route_from_supervisor,
        {
            "handoff_executor": "handoff_executor", # 路由到 Handoff 工具节点
            supervisor_name: supervisor_name,      # 路由回 Supervisor (用于 Plan 更新后或等待)
            END: END,                              # 路由到结束
            # 注意：不再需要映射 agent_names，因为 Handoff 由 ToolNode+Command 处理
        }
    )
    # ---

    print("Supervisor graph definition created (with sync/async node support & corrected routing).")
    # 返回 StateGraph 定义，让 SupervisorAgent.compile 去编译
    return builder 

# --- 确保 BaseAgent.get_agent 返回 Pregel/CompiledGraph ---
# 需要修改 BaseAgent.compile 返回 self._compiled_core_agent
# 并修改 BaseAgent.get_agent 返回 self._compiled_core_agent
# (或者调整 create_supervisor 获取 compiled_graph 的方式)
# 我们先假设 BaseAgent.get_agent 能正确返回核心 Pregel 图