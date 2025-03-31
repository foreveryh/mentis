# reason_graph/supervisor_node.py

import re
import json
import time
import copy
import ast 
import traceback
from typing import Dict, Any, List, Optional, Union
from datetime import datetime 
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

# 内部导入 (确保路径正确)
try:
    from .state_schema import PlanningAgentState, TaskStatus, Plan
    from .planning_handler import PlanningStateHandler
    from .prompt import SUPERVISOR_PLANNING_PROMPT_TEMPLATE
except ImportError as e:
    print(f"Error importing modules in supervisor_node.py: {e}")
    # Fallbacks
    class PlanningAgentState(Dict): pass
    class Plan(Dict): pass
    class PlanningStateHandler: 
        @staticmethod
        def update_task(*args, **kwargs): return kwargs.get('plan')
        @staticmethod
        def create_plan(*args, **kwargs): return {}
        @staticmethod
        def add_tasks(*args, **kwargs): return kwargs.get('plan')
        @staticmethod
        def finish_plan(*args, **kwargs): return kwargs.get('plan')
        @staticmethod
        def get_task(*args, **kwargs): return None
        @staticmethod
        def update_plan_status(*args, **kwargs): return kwargs.get('plan')
    SUPERVISOR_PLANNING_PROMPT_TEMPLATE = "Fallback Prompt: Error loading template."


# --- 参数解析函数 (使用 JSON / ast.literal_eval) ---
def parse_directive_args(directive_str: str) -> Dict[str, Any]:
    """从指令字符串中解析 JSON 参数"""
    args = {}
    # 查找第一个 '{' 到最后一个 '}' 之间的内容作为 JSON 字符串
    json_match = re.search(r"(\{.*?\})\s*$", directive_str.split(maxsplit=1)[1] if len(directive_str.split(maxsplit=1)) > 1 else "", re.DOTALL)
    if json_match:
        args_json_str = json_match.group(1)
        try:
            args = json.loads(args_json_str)
            if not isinstance(args, dict): raise ValueError("Args JSON not a dict.")
            print(f"DEBUG: Parsed args via JSON: {args}")
            return args
        except json.JSONDecodeError as json_err:
            print(f"Warning: JSON parsing failed ({json_err}), trying ast.literal_eval...")
            try:
                 args = ast.literal_eval(args_json_str)
                 if not isinstance(args, dict): raise ValueError("ast.literal_eval didn't return dict.")
                 print(f"DEBUG: Parsed args via ast.literal_eval: {args}")
                 return args
            except Exception as ast_err:
                 raise ValueError(f"Failed to parse args: {ast_err}. Raw: '{args_json_str}'") from ast_err
    elif directive_str.strip().upper().endswith("{}"): # 处理 FINISH_PLAN {} 的情况
         return {} # 返回空字典
    else:
         # 如果找不到有效的 JSON 参数，但指令需要参数，则抛出错误或返回空字典
         print(f"Warning: Could not find valid JSON arguments in directive: '{directive_str}'. Returning empty args.")
         return {}


# --- Supervisor 节点核心逻辑 (最终完整版) ---
async def supervisor_node_logic(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any,
    supervisor_name: str,
    agent_description_map: Dict[str, str]
) -> Dict[str, Any]:
    """Supervisor 节点的核心逻辑 (最终完整版)"""
    print(f"--- Entering Supervisor Node ({supervisor_name}) ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan')
    current_error = state.get('error')
    if current_error: 
        print(f"  Supervisor saw previous error: {current_error}")
        state['error'] = None # 清除旧错误

    # --- 1. 准备 Prompt ---
    plan_json_str = json.dumps(plan, indent=2, ensure_ascii=False) if plan else "null"
    desc_list = [f"- {name}: {desc}" for name, desc in agent_description_map.items()]
    desc_list.append(f"- {supervisor_name}: Coordinates tasks...")
    agent_descriptions_str = "\n".join(desc_list)

    system_prompt_text = "Error: Prompt template could not be loaded/formatted."
    try:
        from .prompt import SUPERVISOR_PLANNING_PROMPT_TEMPLATE
        current_date_str = datetime.now().strftime("%a, %b %d, %Y")
        system_prompt_text = SUPERVISOR_PLANNING_PROMPT_TEMPLATE.format(
            plan_json=plan_json_str,
            agent_descriptions=agent_descriptions_str,
            current_date=current_date_str # <--- 已修正
        )
    except Exception as e: print(f"ERROR loading/formatting prompt: {e}")

    llm_input_messages = [SystemMessage(content=system_prompt_text)] + messages

    # --- 2. 调用 Supervisor LLM ---
    print("--- Calling Supervisor LLM ---")
    response: Optional[AIMessage] = None
    llm_error_msg: Optional[str] = None
    try:
        response = await model.ainvoke(llm_input_messages, config=config)
        if not isinstance(response, AIMessage): raise TypeError(f"LLM returned non-AIMessage: {type(response)}")
        if not response.name: response.name = supervisor_name
        print(f"Supervisor LLM Raw Response Content: {response.content[:300]}...")
        if response.tool_calls: print(f"Supervisor LLM Tool Calls: {response.tool_calls}")
        messages_to_add: List[BaseMessage] = [response]
    except Exception as e:
        print(f"!!! Error invoking Supervisor LLM: {e}"); traceback.print_exc()
        llm_error_msg = f"Supervisor LLM invocation failed: {e}"
        messages_to_add = [] 
        response = None

    # --- 3. 处理 LLM 回复 (如果成功) ---
    plan_updated: bool = False
    updated_plan: Optional[Plan] = copy.deepcopy(plan) if plan else None
    # 只记录本轮处理中遇到的第一个错误
    directive_error_msg: Optional[str] = None 

    if response and isinstance(response.content, str):
        try:
            # 查找并处理所有 PLAN_UPDATE 指令
            # 使用更简单的 Regex 提取指令和后面的 JSON 参数部分
            plan_directives_match = re.finditer(r"PLAN_UPDATE:\s*(\w+)\s*(\{.*?\})\s*$", response.content, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            directives_processed_count = 0

            for match in plan_directives_match:
                 directives_processed_count += 1
                 command = match.group(1).upper()
                 args_json_str = match.group(2) if len(match.groups()) > 1 else "{}"
                 print(f"Processing directive: {command} with args JSON: {args_json_str[:100]}...")

                 try:
                      args = json.loads(args_json_str)
                      if not isinstance(args, dict): raise ValueError("Args JSON not a dict.")
                      print(f"DEBUG: Parsed args via JSON: {args}")

                      # --- 执行规划指令 ---
                      if command == "CREATE_PLAN":
                           if updated_plan: print("Warning: Plan exists, ignoring CREATE_PLAN.")
                           else:
                                title=args.get("title", "Plan"); desc=args.get("description",""); tasks=args.get("tasks",[])
                                if isinstance(tasks, list) and all(isinstance(t, dict) and 'description' in t for t in tasks):
                                     for task_data in tasks: task_data['status'] = 'pending'
                                     updated_plan = PlanningStateHandler.create_plan(title, desc)
                                     updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks); plan_updated = True
                                else: raise ValueError("Invalid 'tasks' format (must be list of dicts with 'description').")

                      elif command == "ADD_TASKS": # <--- 处理 ADD_TASKS
                           if not updated_plan: raise ValueError("Cannot add tasks, no plan exists.")
                           tasks=args.get("tasks",[])
                           if isinstance(tasks, list) and all(isinstance(t, dict) and 'description' in t for t in tasks):
                                # 确保新任务状态是 pending
                                for task_data in tasks: task_data['status'] = 'pending'
                                updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks); plan_updated = True
                           else: raise ValueError("Invalid 'tasks' format for ADD_TASKS.")

                      elif command == "UPDATE_TASK":
                           if not updated_plan: raise ValueError("No plan to update.")
                           by_id=args.get("by_id")
                           if not by_id or not isinstance(by_id, str): raise ValueError("UPDATE_TASK requires string 'by_id'.")
                           by_id = by_id.strip()
                           task_exists = PlanningStateHandler.get_task(updated_plan, by_id)
                           if not task_exists: raise ValueError(f"Task ID '{by_id}' not found!")
                           
                           # ... (更新 Task 逻辑不变, 包括验证) ...
                           new_status=args.get("status"); eval_text=args.get("evaluation"); notes_text=args.get("notes")
                           validated_status = new_status; update_kwargs = {}
                           if eval_text is not None: update_kwargs['new_evaluation'] = eval_text
                           if notes_text is not None: update_kwargs['new_notes'] = notes_text
                           if new_status == "completed":
                                evaluation_passed = False
                                if eval_text and any(kw in eval_text.lower() for kw in ["successful", "completed", "passed", "met", "ok", "完成", "成功"]): evaluation_passed = True
                                if not evaluation_passed: validated_status = "pending_review"; print(f"Task {by_id} validation failed -> '{validated_status}'.")
                                else: print(f"Task {by_id} validation PASSED.")
                           if validated_status is not None: update_kwargs['new_status'] = validated_status
                           if update_kwargs:
                                print(f"Updating task {by_id} with: {update_kwargs}")
                                updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=by_id, **update_kwargs); plan_updated = True

                      elif command == "FINISH_PLAN": # <--- 处理 FINISH_PLAN
                           if not updated_plan: raise ValueError("No plan to finish.")
                           updated_plan = PlanningStateHandler.finish_plan(updated_plan); plan_updated = True

                      else: print(f"Warning: Unknown PLAN_UPDATE command '{command}'.")

                 except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                      err_msg = f"Error processing plan directive '{command} {args_json_str}': {type(e).__name__} - {e}"
                      print(err_msg); traceback.print_exc()
                      if not directive_error_msg: directive_error_msg = err_msg # 只记录第一个错误
                 except Exception as e:
                      err_msg = f"Unexpected error processing directive '{command} {args_json_str}': {type(e).__name__} - {e}"
                      print(err_msg); traceback.print_exc()
                      if not directive_error_msg: directive_error_msg = err_msg

            # 如果处理了指令并且计划有更新，重新计算计划状态
            if plan_updated and updated_plan:
                 updated_plan = PlanningStateHandler.update_plan_status(updated_plan)
                 print(f"Plan status after updates: {updated_plan.get('status')}")
        
        except Exception as outer_e: # 捕获查找指令过程中的错误
             err_msg = f"Error occurred while searching for PLAN_UPDATE directives: {outer_e}"
             print(err_msg); traceback.print_exc()
             if not directive_error_msg: directive_error_msg = err_msg

    # --- 4. 准备最终返回的状态更新字典 ---
    updates: Dict[str, Any] = {"messages": messages_to_add}
    
    # 总是包含 plan 字段（如果它存在于当前状态或已被更新）
    if updated_plan is not None: updates["plan"] = updated_plan
    elif plan is not None: updates["plan"] = plan

    # 记录本轮遇到的错误（优先记录 LLM 错误，其次是指令处理错误）
    final_error_to_record = llm_error_msg or directive_error_msg
    if final_error_to_record:
        updates["error"] = final_error_to_record
    elif state.get("error"): # 如果没有新错误，清除旧错误
         updates["error"] = None

    print(f"--- Exiting Supervisor Node. Plan updated this step: {plan_updated} ---")
    return updates