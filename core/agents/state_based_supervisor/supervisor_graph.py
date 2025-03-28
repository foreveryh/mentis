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
    # ... (实现保持不变) ...
    if not isinstance(model, BaseChatModel): return False
    if hasattr(model, "model_name") and model.model_name in MODELS_NO_PARALLEL_TOOL_CALLS: return False
    if not hasattr(model, "bind_tools"): return False
    if "parallel_tool_calls" not in inspect.signature(model.bind_tools).parameters: return False
    return True

# 定义 _make_call_agent
def _make_call_agent(
    agent_graph: Pregel, # 接收编译后的 Pregel 图
    output_mode: OutputMode,
    add_handoff_back_messages: bool,
    supervisor_name: str,
) -> RunnableCallable: # 返回 RunnableCallable
    """创建一个调用子 Agent 并处理其输出的 RunnableCallable"""
    if output_mode not in ["full_history", "last_message"]: # 修正检查
        raise ValueError(f"Invalid output mode: {output_mode}")

    async def acall_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        """异步调用子 Agent"""
        print(f"🟡 [Async invoke] Handoff to agent '{agent_graph.name}'")
        # 子 agent 接收的状态可能需要清理，只包含 messages (或其他必需字段)
        sub_agent_input = {"messages": state.get("messages", [])}
        # 传递必要的 config, 特别是 thread_id
        output = await agent_graph.ainvoke(sub_agent_input, config=config)
        print(f"✅ [Async invoke] Agent '{agent_graph.name}' completed.")

        # --- 处理输出 ---
        # 获取子 Agent 的最终消息列表
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        if not sub_agent_messages:
             return {"messages": []} # 如果子 agent 没有返回消息

        # 根据 output_mode 决定返回哪些消息
        returned_messages: List[BaseMessage] = []
        if output_mode == "full_history":
            returned_messages = sub_agent_messages
        elif output_mode == "last_message":
            # 需要找到最后一个 AIMessage 作为子 Agent 的最终回复
            last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
            returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:] # Fallback to absolute last

        # 添加 handoff back 消息 (如果启用)
        if add_handoff_back_messages:
             # 创建 handoff back 消息对
             # 注意：这里需要子 Agent 的最终回复内容填充到 AIMessage 中
             final_sub_agent_response = returned_messages[-1] if returned_messages else AIMessage(content="No response generated.", name=agent_graph.name)
             
             # 创建 handoff 工具调用结构 (用于 AIMessage)
             tool_call_id = str(uuid.uuid4())
             simulated_tool_name = f"transfer_back_to_{_normalize_agent_name(supervisor_name)}"
             tool_calls = [ToolCall(name=simulated_tool_name, args={}, id=tool_call_id)]

             # 构建包含 tool_calls 的 AIMessage (使用子 Agent 的实际内容)
             handoff_ai_msg = AIMessage(
                 content=final_sub_agent_response.content, # 使用子 Agent 的内容
                 tool_calls=tool_calls,
                 name=agent_graph.name, # 标记来源 Agent
             )
             
             # 创建对应的 ToolMessage
             handoff_tool_msg = ToolMessage(
                 content=f"Successfully transferred back to {supervisor_name} from {agent_graph.name}.",
                 name=simulated_tool_name,
                 tool_call_id=tool_call_id,
             )
             # 将这对消息添加到要返回的消息列表 *之前*？还是之后？
             # 通常是 AI 发起 handoff, 然后 ToolMessage 确认。
             # 这里是子 Agent 返回，Supervisor 接收。
             # 所以应该是子 Agent 的最后回复 AIMessage + handoff_back ToolMessage
             # 或者直接将 handoff_back messages 添加到 Supervisor 的历史记录中
             
             # 修正: _make_call_agent 的作用是将子 agent 的输出包装好返回给 supervisor
             # 返回的消息应该是子 agent 的实际输出 + 表示 handoff back 的消息对
             # 让我们遵循 handoff.py 的 create_handoff_back_messages 逻辑
             _ai_msg_placeholder, handoff_tool_msg = create_handoff_back_messages(agent_graph.name, supervisor_name)
             
             # 使用子 agent 的最后一个 AI message 作为 handoff 发起者
             last_ai_message_from_sub = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
             if last_ai_message_from_sub:
                 # 附加 tool call 到子 agent 的最后一条消息上 (或者创建一个新的)
                 if not last_ai_message_from_sub.tool_calls:
                      last_ai_message_from_sub.tool_calls = tool_calls # 修改似乎不太好，创建新的
                 handoff_ai_msg = AIMessage(
                     content=last_ai_message_from_sub.content, 
                     tool_calls=tool_calls, 
                     name=agent_graph.name
                 )
                 # 返回子 agent 的历史（根据 output_mode）+ handoff AIMessage + handoff ToolMessage
                 # 如果 last_message 模式，只返回最后一条 AI (带 handoff) + ToolMessage
                 if output_mode == "last_message":
                     returned_messages = [handoff_ai_msg, handoff_tool_msg]
                 else: # full_history
                      # 在完整历史后附加 handoff 对
                      returned_messages = sub_agent_messages + [handoff_ai_msg, handoff_tool_msg] # 这样对吗？
                      # 或者更标准的做法是，只返回子 agent 的消息，然后在 supervisor 端添加 handoff_back?
                      # 让我们遵循 LangGraph 示例，只返回子 agent 的消息
                      # Supervisor 在接收到子 agent 的回复后，可以自行添加确认信息
                      # 因此，create_handoff_back_messages 可能不需要在这里使用
                      pass # Let's just return sub-agent messages based on output_mode

             else: # 如果子 agent 没有返回 AI message? 异常情况
                 print(f"Warning: Sub-agent {agent_graph.name} did not return an AIMessage.")
                 # 仍然根据 output_mode 返回消息
                 if output_mode == "last_message":
                     returned_messages = sub_agent_messages[-1:] if sub_agent_messages else []
                 else:
                     returned_messages = sub_agent_messages
        
        # 不在此处添加 handoff_back_messages，让 Supervisor 自行处理接收逻辑
        
        # 返回包含处理后消息的状态字典
        # 关键：只更新 messages 字段，其他状态由 Supervisor 管理
        return {"messages": returned_messages}

    # 同步版本 (简化，可以调用异步版本或单独实现)
    def call_agent(state: Dict, config: Optional[RunnableConfig] = None) -> Dict:
        # For simplicity, you might run the async version in a loop if needed
        # Or implement the synchronous invocation logic here
        # This example focuses on the async path common in LangGraph
        # return asyncio.run(acall_agent(state, config)) # Not ideal in library code
        print(f"🟡 [Sync invoke] Handoff to agent '{agent_graph.name}'")
        sub_agent_input = {"messages": state.get("messages", [])}
        try:
            # Assumes agent_graph has a synchronous invoke
            output = agent_graph.invoke(sub_agent_input, config=config)
        except NotImplementedError:
             print(f"Warning: Synchronous invoke not implemented for {agent_graph.name}. Skipping sync call.")
             return {"messages": []} # Or raise error

        print(f"✅ [Sync invoke] Agent '{agent_graph.name}' completed.")
        # Process output similarly to async version
        sub_agent_messages: List[BaseMessage] = output.get("messages", [])
        if not sub_agent_messages: return {"messages": []}
        
        returned_messages: List[BaseMessage] = []
        if output_mode == "last_message":
             last_ai_message = next((m for m in reversed(sub_agent_messages) if isinstance(m, AIMessage)), None)
             returned_messages = [last_ai_message] if last_ai_message else sub_agent_messages[-1:]
        else: # full_history
             returned_messages = sub_agent_messages
             
        return {"messages": returned_messages}


    return RunnableCallable(call_agent, acall_agent, name=f"Call_{agent_graph.name}")

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
    for agent in sub_agents:
        if not isinstance(agent, BaseAgent):
            raise TypeError(f"Agent {agent} is not an instance of BaseAgent.")
        if not agent.name or agent.name == "LangGraph":
            raise ValueError("Sub-agents must have unique, valid names.")
        if agent.name in agent_graphs:
            raise ValueError(f"Duplicate agent name found: {agent.name}")
        
        agent_names.append(agent.name)
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
        agent_names=agent_names
    )
    builder.add_node(supervisor_name, supervisor_logic_partial) # type: ignore
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

    # 8. 添加从 Supervisor 出发的条件边进行路由
    def route_from_supervisor(state: PlanningAgentState) -> Union[str, List[str]]:
        """根据 Supervisor 的最新消息和 Plan 状态决定路由。"""
        messages = state.get('messages', [])
        plan = state.get('plan')
        last_message = messages[-1] if messages else None

        if isinstance(last_message, AIMessage):
            # 优先检查 Handoff Tool 调用
            if last_message.tool_calls:
                tool_call = last_message.tool_calls[0]
                agent_name_match = re.match(r"transfer_to_(\w+)", tool_call["name"])
                if agent_name_match:
                    target_agent = agent_name_match.group(1)
                    if target_agent in agent_names:
                        print(f"Routing: Supervisor -> {target_agent}")
                        return target_agent # 路由到目标 Agent
                    else:
                        print(f"Warning: Routing failed. Target agent '{target_agent}' unknown. Looping supervisor.")
                        return supervisor_name # Agent 不存在，让 Supervisor 重试

            # 如果没有 Handoff，检查 Plan 状态是否完成
            if plan and plan.get("status") == "completed":
                 print("Routing: Plan completed -> END")
                 return END # 计划已完成

            # 如果没有 Handoff 且计划未完成，通常是 Supervisor 更新了计划或仍在思考
            # 让它再运行一次以决定下一步 (委派或结束)
            print("Routing: Looping back to supervisor for next step decision.")
            return supervisor_name

        else: # 最后不是 AI 消息 (例如 ToolMessage 或 HumanMessage?) -> 让 Supervisor 处理
             print("Routing: Last message not AIMessage, looping supervisor.")
             return supervisor_name

    builder.add_conditional_edges(supervisor_name, route_from_supervisor)

    # 9. 编译图
    # Checkpointer 等应在编译时传入
    # compiled_graph = builder.compile(checkpointer=...)
    # 返回 StateGraph 实例，让调用者编译
    return builder