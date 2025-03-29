# reason_graph/supervisor_node.py
import re
import json
from typing import Dict, Any, List, Optional, Union
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
# 内部导入
from .state_schema import PlanningAgentState, TaskStatus, Plan
from .planning_handler import PlanningStateHandler
from .agent_name import with_agent_name # 假设这个函数在 agent_name.py
# 假设 llm 实例和 handoff_tools 在调用时可用 (通过闭包或参数传递)

async def supervisor_node_logic(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any, # 传入绑定了 Handoff 工具的 Supervisor LLM 模型
    supervisor_name: str,
    agent_description_map: Dict[str, str] 
) -> Dict[str, Any]:
    """Supervisor 节点的核心逻辑 (手动实现)"""
    print(f"--- Entering Supervisor Node ({supervisor_name}) ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan') # 获取当前计划状态

    # 1. 准备发送给 Supervisor LLM 的消息
    #    可能需要包含计划状态的文本表示
    plan_json_str = json.dumps(plan, indent=2) if plan else "null"
    
    # 构建 agent descriptions 字符串
    desc_list = [f"- {name}: {desc}" for name, desc in agent_description_map.items()]
    desc_list.append(f"- {supervisor_name}: Coordinates tasks and manages the plan based on agent descriptions and plan status.") # 添加 Supervisor 自身描述
    agent_descriptions_str = "\n".join(desc_list)

    #    从 prompt.py 导入模板并格式化
    from .prompt import SUPERVISOR_PLANNING_PROMPT_TEMPLATE
    from datetime import datetime
    current_date_str = datetime.now().strftime("%a, %b %d, %Y")
    system_prompt_text = SUPERVISOR_PLANNING_PROMPT_TEMPLATE.format(
        current_date=current_date_str,
        plan_json=plan_json_str,
        agent_descriptions=agent_descriptions_str
    )

    #    组合消息列表 (包含 System Prompt 和历史消息)
    #    注意: 这里的 messages 应该已经被截断过
    #    如果 SupervisorAgent 继承 BaseAgent, 调用它时应该已经注入/截断
    #    但如果手动调用节点，需要确保消息是处理过的
    #    我们假设 state['messages'] 是截断后的历史
    llm_input_messages = [SystemMessage(content=system_prompt_text)] + messages

    # 2. 调用 Supervisor LLM
    print("--- Calling Supervisor LLM ---")
    response: AIMessage = await model.ainvoke(llm_input_messages, config=config)
    # 确保 LLM 的回复有名字 (如果模型不自动添加)
    if not response.name:
         response.name = supervisor_name
    print(f"Supervisor LLM Raw Response: {response.content[:200]}...")

    # 3. 初始化返回状态和路由决策
    plan_updated: bool = False
    # 使用 deepcopy 来安全地修改 plan，避免影响原始 state 字典中的 plan
    import copy
    updated_plan: Optional[Plan] = copy.deepcopy(plan) if plan else None
    error_message: Optional[str] = None
    messages_to_add: List[BaseMessage] = [response] # 只包含 Supervisor 的 AIMessage


    # --- 检查是否有 Plan 更新指令 (如果没有 Tool 调用) ---
    if not response.tool_calls:
        content = response.content
        plan_match = re.search(r"PLAN_UPDATE:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if plan_match:
            plan_directive = plan_match.group(1).strip()
            print(f"Supervisor issued plan directive: {plan_directive}")
            try:
                # ... (解析并执行规划指令，更新 updated_plan 的逻辑保持不变) ...
                # ... (例如: command = directive_parts[0].upper()) ...
                # ... (if command == "UPDATE_TASK": ...) ...
                # ... (if command == "FINISH_PLAN": updated_plan = PlanningStateHandler.finish_plan(...)) ...

                # 如果解析和执行成功，标记 plan_updated
                # (确保解析指令的代码块在成功时设置 plan_updated = True)
                # Example (inside the parsing logic):
                # if command == "UPDATE_TASK":
                #     # ... update logic ...
                #     plan_updated = True 
                # elif command == "FINISH_PLAN":
                #     # ... finish logic ...
                #      plan_updated = True
                 pass # Placeholder for actual parsing and plan_updated=True logic
                 # Simulating update for example
                 if updated_plan: plan_updated = True # Assume update happened if directive found

            except Exception as e:
                error_message = f"Error processing plan directive '{plan_directive}': {e}"
                print(error_message)
        # else:
            # 如果没有 Tool 调用，也没有 Plan 更新指令，则认为是最终回复
            # 不需要特殊处理，路由函数会处理这种情况

    # --- 准备返回的状态更新 ---
    updates: Dict[str, Any] = {"messages": messages_to_add} # 只返回 AIMessage
    if plan_updated and updated_plan:
        updates["plan"] = updated_plan # 如果计划更新了，则包含新计划
    if error_message:
        updates["error"] = error_message 

    print(f"--- Exiting Supervisor Node. Plan updated this step: {plan_updated} ---")
    # **不再手动添加 ToolMessage**
    return updates 