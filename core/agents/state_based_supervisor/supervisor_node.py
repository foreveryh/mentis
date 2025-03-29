# reason_graph/supervisor_node.py
import re
import json
import time # 确保导入 time
import copy # 确保导入 copy
import ast  # 用于安全解析 list/dict
from typing import Dict, Any, List, Optional, Union
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
# 内部导入
from .state_schema import PlanningAgentState, TaskStatus, Plan
from .planning_handler import PlanningStateHandler
# from .agent_name import with_agent_name # 可能不需要

async def supervisor_node_logic(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any, 
    supervisor_name: str,
    agent_description_map: Dict[str, str] # 接收描述映射
) -> Dict[str, Any]:
    """Supervisor 节点的核心逻辑 (修正 plan_updated 标志)"""
    print(f"--- Entering Supervisor Node ({supervisor_name}) ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan') 

    # --- 准备 Prompt ---
    plan_json_str = json.dumps(plan, indent=2, ensure_ascii=False) if plan else "null"
    desc_list = [f"- {name}: {desc}" for name, desc in agent_description_map.items()]
    desc_list.append(f"- {supervisor_name}: Coordinates tasks...")
    agent_descriptions_str = "\n".join(desc_list)

    from .prompt import SUPERVISOR_PLANNING_PROMPT_TEMPLATE
    try:
        system_prompt_text = SUPERVISOR_PLANNING_PROMPT_TEMPLATE.format(
            plan_json=plan_json_str,
            agent_descriptions=agent_descriptions_str
        )
    except Exception as e:
        print(f"Error formatting supervisor prompt: {e}")
        system_prompt_text = "Error formatting prompt." # Fallback

    llm_input_messages = [SystemMessage(content=system_prompt_text)] + messages

    # --- 调用 LLM ---
    print("--- Calling Supervisor LLM ---")
    try:
        response: AIMessage = await model.ainvoke(llm_input_messages, config=config)
        if not response.name: response.name = supervisor_name
        print(f"--- Supervisor LLM Response Object ---") # 保留 Debug 打印
        print(f"Type: {type(response)}")
        print(f"Content: {response.content[:500]}...") 
        print(f"Tool Calls: {response.tool_calls}")     
        print(f"------------------------------------")
    except Exception as e:
        print(f"!!! Error invoking Supervisor LLM: {e}")
        return {"error": f"Supervisor LLM invocation failed: {e}", "messages": messages} # 返回包含原始消息的错误

    # --- 处理回复 ---
    plan_updated: bool = False # <--- 初始化为 False
    updated_plan: Optional[Plan] = copy.deepcopy(plan) if plan else None
    error_message: Optional[str] = None
    messages_to_add: List[BaseMessage] = [response]

    # 只有在没有工具调用时才检查 PLAN_UPDATE
    if not response.tool_calls:
        content = response.content
        plan_match = re.search(r"PLAN_UPDATE:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if plan_match:
            plan_directive = plan_match.group(1).strip()
            print(f"Supervisor issued plan directive: {plan_directive}")
            try:
                directive_parts = plan_directive.split(maxsplit=1)
                command = directive_parts[0].upper()
                args_str = directive_parts[1] if len(directive_parts) > 1 else ""

                # 解析参数 (使用更安全的 literal_eval)
                def parse_args(arg_string: str) -> Dict[str, Any]:
                    args = {}
                    # 匹配 key='value' 或 key="value"
                    for match in re.finditer(r"(\w+)\s*=\s*['\"](.*?)['\"]", arg_string):
                        key, value = match.groups(); args[key.lower()] = value
                    # 匹配 tasks=[...] 
                    if 'tasks' in arg_string:
                         tasks_match = re.search(r"tasks=\s*(\[.*?\])", arg_string, re.DOTALL)
                         if tasks_match:
                              try:
                                   # 使用 ast.literal_eval 更安全
                                   tasks_list_str = tasks_match.group(1)
                                   parsed_tasks = ast.literal_eval(tasks_list_str)
                                   if isinstance(parsed_tasks, list):
                                       args['tasks'] = parsed_tasks
                                   else:
                                       print("Warning: Parsed 'tasks' is not a list.")
                                       args['tasks'] = []
                              except (ValueError, SyntaxError) as parse_err:
                                   print(f"Warning: Failed to parse 'tasks' list safely: {parse_err}. Directive: {arg_string}")
                                   args['tasks'] = []
                    return args

                args = parse_args(args_str)

                if command == "CREATE_PLAN":
                     if updated_plan: print("Warning: Plan exists, ignoring CREATE_PLAN.")
                     else:
                          title = args.get("title", "Plan"); desc = args.get("description", "")
                          tasks = args.get("tasks", [])
                          if isinstance(tasks, list):
                               updated_plan = PlanningStateHandler.create_plan(title, desc)
                               updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks)
                               plan_updated = True # <--- 设置标志
                          else: raise ValueError("Invalid 'tasks' format for CREATE_PLAN.")

                elif command == "ADD_TASKS":
                     if not updated_plan: raise ValueError("No plan exists.")
                     tasks = args.get("tasks", [])
                     if isinstance(tasks, list):
                          updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks)
                          plan_updated = True # <--- 设置标志
                     else: raise ValueError("Invalid 'tasks' format for ADD_TASKS.")

                elif command == "UPDATE_TASK":
                     if not updated_plan: raise ValueError("No plan exists.")
                     by_id = args.get("by_id")
                     if not by_id: raise ValueError("UPDATE_TASK requires 'by_id'.")
                     new_status = args.get("status"); eval_text = args.get("evaluation"); notes_text = args.get("notes")
                     # 更新备注/评估
                     updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=by_id, new_evaluation=eval_text, new_notes=notes_text)
                     # 验证状态 (保持之前的逻辑)
                     validated_status = new_status
                     if new_status == "completed":
                          evaluation_passed = False
                          if eval_text and any(kw in eval_text.lower() for kw in ["successful", "completed", "passed", "met requirements", "looks good"]): evaluation_passed = True
                          if not evaluation_passed: validated_status = "pending_review"
                          else: print(f"Task {by_id} validation PASSED.")
                     # 更新最终状态
                     if validated_status:
                          updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=by_id, new_status=validated_status)
                     plan_updated = True # <--- 设置标志 (只要尝试更新就标记)

                elif command == "SET_CURRENT":
                     if not updated_plan: raise ValueError("No plan exists.")
                     task_id = args.get("task_id");
                     if not task_id: raise ValueError("SET_CURRENT requires 'task_id'.")
                     updated_plan = PlanningStateHandler.set_current_task(updated_plan, task_id)
                     plan_updated = True # <--- 设置标志
                     
                elif command == "FINISH_PLAN":
                     if not updated_plan: raise ValueError("No plan exists.")
                     updated_plan = PlanningStateHandler.finish_plan(updated_plan)
                     plan_updated = True # <--- 设置标志
                else:
                    raise ValueError(f"Unknown PLAN_UPDATE command: {command}")

            except Exception as e:
                error_message = f"Error processing plan directive '{plan_directive}': {e}"
                print(error_message)
                # 解析或执行指令出错时，不认为计划被成功更新了
                plan_updated = False # <--- 确保出错时为 False
                updated_plan = plan # 恢复到原始 plan

    # --- 准备返回的状态更新 ---
    updates: Dict[str, Any] = {"messages": messages_to_add}
    if plan_updated and updated_plan: # 只有成功更新才添加 plan
        updates["plan"] = updated_plan
    if error_message:
        updates["error"] = error_message

    print(f"--- Exiting Supervisor Node. Plan updated this step: {plan_updated} ---") # 现在这个日志更准确了
    return updates