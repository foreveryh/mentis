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
from langgraph.pregel import Pregel

# 内部导入
try:
    from core.agents.base.base_agent import BaseAgent
    from .handoff import create_handoff_tool, _normalize_agent_name # 确保导入 _normalize_agent_name
    from .state_schema import PlanningAgentState, Plan # 导入 PlanningAgentState 和 Plan
    from .supervisor_node import supervisor_node_logic # 导入异步节点逻辑
    from .planner_node import planner_node_logic, planner_node_logic_sync # <--- 导入 Planner 逻辑
    from .evaluate_result_node import evaluate_result_node_logic, evaluate_result_node_logic_sync # <--- 导入 Evaluator 逻辑
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
     async def planner_node_logic(*args, **kwargs): return {} # <--- 添加 planner_node_logic
     def planner_node_logic_sync(*args, **kwargs): return {} # <--- 添加 planner_node_logic_sync
     async def evaluate_result_node_logic(*args, **kwargs): return {} # 添加 evaluate_result_node_logic  
     def evaluate_result_node_logic_sync(*args, **kwargs): return {} # 添加 evaluate_result_node_logic_sync
     def with_agent_name(model, mode): return model


# 定义 OutputMode, MODELS_NO_PARALLEL_TOOL_CALLS, _supports_disable_parallel_tool_calls (保持不变)
OutputMode = Literal["full_history", "last_message"]
MODELS_NO_PARALLEL_TOOL_CALLS = {"o3-mini"}
def _supports_disable_parallel_tool_calls(model: LanguageModelLike) -> bool:
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
    if output_mode not in ["full_history", "last_message"]: raise ValueError(...)

    async def acall_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        agent_name = getattr(agent_graph, 'name', 'sub_agent')
        print(f"🟡 [Async invoke] Handoff to agent '{agent_name}'")
        sub_agent_input = {"messages": state.get("messages", [])}
        output: Dict[str, Any] = {}
        agent_error: Optional[str] = None

        try:
             output = await agent_graph.ainvoke(sub_agent_input, config=config)
             print(f"✅ [Async invoke] Agent '{agent_name}' completed.")
        except Exception as e:
             print(f"!!! Error during sub-agent {agent_name} ainvoke: {e}"); traceback.print_exc()
             agent_error = f"Error executing agent '{agent_name}': {type(e).__name__}"

        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        returned_messages: List[BaseMessage] = []
        if not sub_agent_messages and not agent_error:
             returned_messages = [AIMessage(content="(No output received from agent)", name=agent_name)]
        elif output_mode == "last_message":
             last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
             returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else:
             returned_messages = sub_agent_messages
             
        last_content = agent_error
        if not last_content and returned_messages:
             last_content = str(returned_messages[-1].content) if hasattr(returned_messages[-1], 'content') else "(No textual content)"

        return {
            "messages": returned_messages,
            "last_agent_result": {
                 "agent_name": agent_name,
                 "content": last_content or "(Agent execution finished without specific output or error)"
            }
        }

    def call_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        agent_name = getattr(agent_graph, 'name', 'sub_agent')
        print(f"🟡 [Sync invoke] Handoff to agent '{agent_name}'")
        sub_agent_input = {"messages": state.get("messages", [])}
        output: Dict[str, Any] = {}
        agent_error: Optional[str] = None

        try: output = agent_graph.invoke(sub_agent_input, config=config); print(f"✅ [Sync invoke] Agent '{agent_name}' completed.")
        except NotImplementedError: agent_error = f"Error: Sync invoke not supported by agent '{agent_name}'."; print(agent_error)
        except Exception as e: agent_error = f"Error during sub-agent {agent_name} invoke: {e}"; print(f"!!! {agent_error}")
        
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        returned_messages: List[BaseMessage] = []
        if not sub_agent_messages and not agent_error: returned_messages = [AIMessage(content="(No output received)", name=agent_name)]
        elif output_mode == "last_message":
             last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
             returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else: returned_messages = sub_agent_messages
        
        last_content = agent_error
        if not last_content and returned_messages: last_content = str(returned_messages[-1].content) if hasattr(returned_messages[-1], 'content') else "(No content)"

        return {
            "messages": returned_messages,
            "last_agent_result": {
                 "agent_name": agent_name,
                 "content": last_content or "(Agent sync execution finished)"
            }
        }

    return RunnableCallable(func=call_agent, afunc=acall_agent, name=f"Call_{getattr(agent_graph, 'name', 'sub_agent')}")


def supervisor_node_logic_sync(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any,
    supervisor_name: str,
    agent_description_map: Dict[str, str]
) -> Dict[str, Any]:
    print(f"--- Entering Supervisor Node (Sync Wrapper) ---")
    try:
        return anyio.run(
            supervisor_node_logic, state, config, model, supervisor_name, agent_description_map
        )
    except Exception as e:
        print(f"Error running supervisor_node_logic synchronously using anyio: {e}")
        import traceback
        traceback.print_exc()
        return {"error": f"Sync execution wrapper failed: {e}", "messages": state.get("messages",[])}


def create_supervisor(
    model: LanguageModelLike,
    sub_agents: List[BaseAgent],
    state_schema: Type[PlanningAgentState] = PlanningAgentState,
    config_schema: Type[Any] | None = None,
    tools: list[BaseTool | Callable] | None = None,
    output_mode: OutputMode = "last_message",
    add_handoff_back_messages: bool = False,
    supervisor_name: str = "supervisor",
    planner_node_name: str = "planner",
    evaluator_node_name: str = "evaluate_result",
    handoff_executor_name: str = "handoff_executor",
    include_agent_name: AgentNameMode | None = "inline",
) -> StateGraph:
    agent_graphs: Dict[str, Pregel] = {}
    agent_names: List[str] = []
    agent_description_map: Dict[str, str] = {}
    # --- 1. 提取 Agent 信息  ---
    for agent in sub_agents:
        if not isinstance(agent, BaseAgent): raise TypeError(...)
        if not agent.name or agent.name == "LangGraph": raise ValueError(...)
        if agent.name in agent_graphs: raise ValueError(...)
        agent_names.append(agent.name)
        agent_description_map[agent.name] = getattr(agent, 'description', '...')
        try:
            compiled_graph = agent.get_agent()
            if not isinstance(compiled_graph, Pregel): 
                 core_graph = getattr(compiled_graph, 'last', None)
                 if isinstance(core_graph, Pregel):
                      compiled_graph = core_graph
                 else:
                      raise TypeError(f"Could not retrieve Pregel instance from agent '{agent.name}'.get_agent()")
            agent_graphs[agent.name] = compiled_graph
        except Exception as e: raise e

     # --- 2. 创建 Handoff 工具 ---
    handoff_tools = [create_handoff_tool(agent_name=name) for name in agent_names]
    supervisor_callable_tools = (tools or []) + handoff_tools
    print(f"Supervisor '{supervisor_name}' bound with tools: {[t.name for t in supervisor_callable_tools]}")

    # --- 3. 绑定工具到 Supervisor 模型 ---
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
    
    # --- 5. 添加 Planner 节点 (使用同步/异步包装) ---
    planner_logic_partial_async = functools.partial(
        planner_node_logic,
        model=model,
        agent_description_map=agent_description_map,
    )
    planner_logic_partial_sync = functools.partial(
        planner_node_logic_sync,
        model=model,
        agent_description_map=agent_description_map,
    )
    planner_runnable = RunnableCallable(
        func=planner_logic_partial_sync,
        afunc=planner_logic_partial_async,
        name=planner_node_name
    )
    builder.add_node(planner_node_name, planner_runnable)

    # --- 6. 添加 Supervisor 节点 (使用同步/异步包装) ---
    supervisor_logic_partial_async = functools.partial(
        supervisor_node_logic,
        model=bound_supervisor_model,
        supervisor_name=supervisor_name,
        agent_description_map=agent_description_map,
    )
    supervisor_logic_partial_sync = functools.partial(
        supervisor_node_logic_sync,
        model=bound_supervisor_model,
        supervisor_name=supervisor_name,
        agent_description_map=agent_description_map,
    )
    supervisor_runnable = RunnableCallable(
        func=supervisor_logic_partial_sync,
        afunc=supervisor_logic_partial_async,
        name=supervisor_name
    )
    builder.add_node(supervisor_name, supervisor_runnable)

    # --- 7. 添加子 Agent 节点 ---
    for name, compiled_graph in agent_graphs.items():
        builder.add_node(name, _make_call_agent(compiled_graph, output_mode, add_handoff_back_messages, supervisor_name))
        builder.add_edge(name, evaluator_node_name)

    # --- 8. 添加 Handoff Tool 执行节点 ---
    handoff_executor_node = ToolNode(handoff_tools, name=handoff_executor_name)
    builder.add_node(handoff_executor_name, handoff_executor_node)
    
    # --- 9. 添加 Evaluate Result 节点 ---
    evaluator_runnable = RunnableCallable(func=evaluate_result_node_logic_sync, afunc=evaluate_result_node_logic, name=evaluator_node_name)
    # Evaluator 不需要 model 或 agent descriptions 作为直接参数
    builder.add_node(evaluator_node_name, evaluator_runnable) # type: ignore
    # --- 10. 设置图的入口和边 ---
    builder.set_entry_point(planner_node_name)
    builder.add_edge(planner_node_name, supervisor_name)

    def route_from_supervisor(state: PlanningAgentState) -> str:
        messages = state.get('messages', [])
        plan = state.get('plan')
        last_message = messages[-1] if messages else None

        if not isinstance(last_message, AIMessage):
            print("Routing: Last message not AIMessage, looping supervisor.")
            return supervisor_name

        if last_message.tool_calls:
            tool_call = last_message.tool_calls[0]
            agent_name_match = re.match(r"transfer_to_(\w+)", tool_call["name"])
            if agent_name_match and agent_name_match.group(1) in agent_names: 
                 extracted_name = agent_name_match.group(1)
                 print(f"DEBUG route_from_supervisor: Tool Call Name = {repr(tool_call['name'])}") 
                 print(f"DEBUG route_from_supervisor: Extracted Target Name = {repr(extracted_name)}") 
                 print(f"DEBUG route_from_supervisor: Available Agent Names = {repr(agent_names)}") 
                 print(f"Routing: Supervisor -> HandoffExecutor (for {extracted_name})")
                 return handoff_executor_name
            else:
                 print(f"DEBUG route_from_supervisor: Membership check failed! ('{extracted_name}' in {repr(agent_names)}) is False.")
                 print(f"Warning: Supervisor called unknown/invalid tool: {tool_call['name']}. Looping supervisor.")
                 return supervisor_name

        if plan and plan.get("status") == "completed":
             print("Routing: Plan completed -> END")
             return END

        print(f"Routing: No tool call and plan not completed (status: {plan.get('status') if plan else 'None'}). Looping supervisor.")
        return supervisor_name

    builder.add_conditional_edges(
        supervisor_name,
        route_from_supervisor,
        {
            handoff_executor_name: handoff_executor_name,
            supervisor_name: supervisor_name,
            END: END,
        }
    )
    
    # Handoff Executor 完成后, LangGraph 处理 Command(goto=...) 直接路由到子 Agent
    # 不需要从 Handoff Executor 出发的显式边

    # --- 关键修改: 子 Agent 完成后 -> Evaluator ---
    for name in agent_names:
        builder.add_edge(name, evaluator_node_name) # <--- 修改: 指向 Evaluator

    # --- 新增: Evaluator 完成后 -> Supervisor ---
    builder.add_edge(evaluator_node_name, supervisor_name) # <--- 新增: Evaluator 指回 Supervisor

    print("Supervisor graph definition created with Planner and Evaluator nodes.")
    return builder # 返回 StateGraph 定义