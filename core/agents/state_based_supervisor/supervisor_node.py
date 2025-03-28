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
    agent_names: List[str] # 可用的子 Agent 名称列表
) -> Dict[str, Any]:
    """Supervisor 节点的核心逻辑 (手动实现)"""
    print(f"--- Entering Supervisor Node ({supervisor_name}) ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan') # 获取当前计划状态

    # 1. 准备发送给 Supervisor LLM 的消息
    #    可能需要包含计划状态的文本表示
    plan_json_str = json.dumps(plan, indent=2) if plan else "null"
    #    构建 agent capabilities 描述
    #    TODO: 更动态地生成 agent_capabilities 描述
    agent_capabilities = "\n".join([f"- {name}: Specializes in..." for name in agent_names]) + "\n- supervisor: Coordinates tasks and manages the plan."

    #    从 prompt.py 导入模板并格式化
    from .prompt import SUPERVISOR_PLANNING_PROMPT_TEMPLATE
    system_prompt_text = SUPERVISOR_PLANNING_PROMPT_TEMPLATE.format(
        plan_json=plan_json_str,
        agent_capabilities=agent_capabilities
    )

    #    组合消息列表 (包含 System Prompt 和历史消息)
    #    注意: 这里的 messages 应该已经被 BaseAgent 的 _inject_context 处理过了?
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
    next_node: str = END # 默认结束
    plan_updated: bool = False
    # 使用 deepcopy 来安全地修改 plan，避免影响原始 state 字典中的 plan
    import copy
    updated_plan: Optional[Plan] = copy.deepcopy(plan) if plan else None
    error_message: Optional[str] = None

    # 4. 解析 LLM 回复：检查 Handoff Tool 调用
    if response.tool_calls:
        # 假设只处理第一个有效的 handoff tool 调用
        handoff_called = False
        for tool_call in response.tool_calls:
            agent_name_match = re.match(r"transfer_to_(\w+)", tool_call["name"])
            if agent_name_match:
                target_agent = agent_name_match.group(1)
                if target_agent in agent_names: # 确保是已知的 Agent
                    next_node = target_agent
                    print(f"Supervisor decided to handoff to: {next_node}")
                    handoff_called = True
                    break # 只处理第一个有效的 handoff
                else:
                    print(f"Warning: Supervisor tried to handoff to unknown agent: {target_agent}")
        if not handoff_called:
             print("Warning: Supervisor called non-handoff tool or unknown handoff target. Looping back.")
             next_node = supervisor_name # 让 Supervisor 再试一次或给出最终答案

    # 5. 如果没有 Handoff，解析 LLM 回复：检查 PLAN_UPDATE 指令
    if next_node != END and next_node not in agent_names: # 仅在未决定 Handoff 时处理 Plan
        content = response.content
        plan_match = re.search(r"PLAN_UPDATE:\s*(.*)", content, re.IGNORECASE | re.DOTALL) # Use DOTALL
        if plan_match:
            plan_directive = plan_match.group(1).strip()
            print(f"Supervisor issued plan directive: {plan_directive}")
            try:
                # --- 解析并执行规划指令 ---
                directive_parts = plan_directive.split(maxsplit=1)
                command = directive_parts[0].upper()
                args_str = directive_parts[1] if len(directive_parts) > 1 else ""

                # 解析参数 (需要更健壮的解析器, e.g., for lists/dicts)
                def parse_args(arg_string: str) -> Dict[str, Any]:
                    args = {}
                    # Basic parsing for key='value' pairs, handles simple strings
                    for match in re.finditer(r"(\w+)\s*=\s*'(.*?)'", arg_string):
                        key, value = match.groups()
                        args[key.lower()] = value # Store keys as lowercase
                    # TODO: Add parsing for tasks=[{...}] list format more robustly
                    if 'tasks' in arg_string:
                         # Very basic list parsing - assumes simple structure, likely needs improvement
                         tasks_match = re.search(r"tasks=\s*(\[.*?\])", arg_string, re.DOTALL)
                         if tasks_match:
                              try:
                                   # Warning: eval is potentially unsafe if LLM output isn't trusted
                                   # Consider using json.loads or ast.literal_eval after cleaning
                                   tasks_list_str = tasks_match.group(1).replace("'", '"') # JSON needs double quotes
                                   args['tasks'] = json.loads(tasks_list_str)
                              except Exception as parse_err:
                                   print(f"Warning: Failed to parse 'tasks' list: {parse_err}. Directive: {arg_string}")
                                   args['tasks'] = []
                    return args

                args = parse_args(args_str)

                if command == "CREATE_PLAN":
                    if updated_plan:
                        print("Warning: Plan already exists. Ignoring CREATE_PLAN directive.")
                    else:
                        title = args.get("title", "Untitled Plan")
                        description = args.get("description", "")
                        tasks_data = args.get("tasks", [])
                        if isinstance(tasks_data, list):
                             updated_plan = PlanningStateHandler.create_plan(title, description)
                             updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks_data) # Add tasks during creation
                             plan_updated = True
                        else:
                            raise ValueError("Invalid 'tasks' format for CREATE_PLAN.")

                elif command == "ADD_TASKS":
                    if not updated_plan: raise ValueError("Cannot add tasks, no plan exists.")
                    tasks_data = args.get("tasks", [])
                    if isinstance(tasks_data, list):
                        updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks_data)
                        plan_updated = True
                    else:
                        raise ValueError("Invalid 'tasks' format for ADD_TASKS.")

                elif command == "UPDATE_TASK":
                    if not updated_plan: raise ValueError("Cannot update task, no plan exists.")
                    by_id = args.get("by_id")
                    if not by_id: raise ValueError("UPDATE_TASK requires 'by_id'.")
                    
                    # --- 加入对齐/验证逻辑 ---
                    new_status = args.get("status")
                    evaluation_text = args.get("evaluation")
                    notes_text = args.get("notes")

                    # Step 1: Update notes and evaluation first
                    updated_plan = PlanningStateHandler.update_task(
                        updated_plan, by_id=by_id,
                        new_evaluation=evaluation_text, new_notes=notes_text
                    )
                    plan_updated = True # Notes/Eval updated

                    # Step 2: If LLM suggested 'completed', perform validation
                    validated_status = new_status
                    if new_status == "completed":
                        print(f"Supervisor node validating task completion for {by_id}...")
                        # --- 在这里加入你的验证逻辑 ---
                        # 示例: 检查 evaluation 文本是否包含成功关键词
                        evaluation_passed = False
                        if evaluation_text:
                            success_keywords = ["successful", "completed", "passed", "met requirements", "looks good"]
                            if any(kw in evaluation_text.lower() for kw in success_keywords):
                                evaluation_passed = True
                                print(f"Validation for task {by_id} PASSED based on evaluation text.")
                            else:
                                print(f"Validation for task {by_id} FAILED based on evaluation text.")
                        else:
                             print(f"Validation for task {by_id} SKIPPED (no evaluation provided). Assuming not completed.")

                        if not evaluation_passed:
                            # 如果验证失败，不设为 completed，可以设为 revision_needed 或保持原状
                            validated_status = "pending_review" # 或者 "revision_needed"
                            print(f"Task {by_id} status NOT set to 'completed' due to failed validation. Set to '{validated_status}'.")
                        else:
                             validated_status = "completed" # 验证通过

                    # Step 3: Update status (either original suggested or validated status)
                    if validated_status:
                         updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=by_id, new_status=validated_status)
                    # --------------------------

                elif command == "SET_CURRENT": # 可能不需要，因为可以按顺序或依赖来
                    if not updated_plan: raise ValueError("Cannot set current task, no plan exists.")
                    task_id = args.get("task_id")
                    if not task_id: raise ValueError("SET_CURRENT requires 'task_id'.")
                    updated_plan = PlanningStateHandler.set_current_task(updated_plan, task_id)
                    plan_updated = True

                elif command == "FINISH_PLAN":
                    if not updated_plan: raise ValueError("Cannot finish plan, no plan exists.")
                    updated_plan = PlanningStateHandler.finish_plan(updated_plan)
                    plan_updated = True
                    next_node = END # 计划完成后结束
                else:
                    raise ValueError(f"Unknown PLAN_UPDATE command: {command}")

                # 如果计划更新了，通常需要 Supervisor 重新评估下一步
                if plan_updated and next_node != END:
                     next_node = supervisor_name
                     print(f"Plan updated. Routing back to supervisor.")

            except Exception as e:
                error_message = f"Error processing plan directive '{plan_directive}': {e}"
                print(error_message)
                # 发生错误时也返回给 Supervisor 处理
                next_node = supervisor_name
        
        # 6. 如果既没有 Handoff，也没有 Plan 更新，则认为是最终回复
        if next_node != END and next_node not in agent_names and not plan_updated:
            print("Supervisor provided final answer or requires clarification. Routing to END.")
            next_node = END

    # --- 准备返回的状态更新 ---
    updates: Dict[str, Any] = {"messages": [response]} # 总是添加 Supervisor 的回复
    if plan_updated and updated_plan:
        updates["plan"] = updated_plan # 如果计划更新了，则包含新计划
    if error_message:
        updates["error"] = error_message # 如果处理指令出错，记录错误

    print(f"--- Exiting Supervisor Node. Routing decision: '{next_node}'. Plan updated: {plan_updated} ---")

    # --- 返回状态更新和路由决策 ---
    # LangGraph 条件边需要依据状态做判断，我们直接更新状态，让条件边读取
    # 或者，如果节点直接返回路由，需要用特殊 key 如 "__next__" 但这不常用
    # 这里我们只更新状态，路由逻辑放在 route_from_supervisor 条件边函数中
    # return updates # 只返回状态更新

    # 为了让 route_from_supervisor 能工作，它需要读取 messages[-1]
    # 所以 updates 字典必须包含 'messages'
    # route_from_supervisor 会根据 AIMessage 的 tool_calls 或 content 判断
    
    # 修正：节点应该返回要更新的状态字段
    return updates