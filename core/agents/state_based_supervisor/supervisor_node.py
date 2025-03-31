# reason_graph/supervisor_node.py

import re
import json
import time
import copy
import ast 
import traceback
from typing import Dict, Any, List, Optional, Union, cast
from datetime import datetime 
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.messages import ToolCall  # 确保导入
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
        @staticmethod
        def set_current_task(*args, **kwargs): return kwargs.get('plan')
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


# --- Supervisor 节点核心逻辑 (移除结果处理，增加设置 current_task_id) ---
async def supervisor_node_logic(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any,
    supervisor_name: str,
    agent_description_map: Dict[str, str]
) -> Dict[str, Any]:
    """Supervisor 节点核心逻辑 (不再处理 Agent 结果状态更新)"""
    print(f"--- Entering Supervisor Node ({supervisor_name}) ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan')
    current_error = state.get('error'); state['error'] = None
    if current_error: print(f"  Supervisor saw previous error: {current_error}")

    # --- 0. 检查 Plan 是否存在 (不变) ---
    if not plan:
         print("ERROR: Supervisor node requires a plan, but none found in state.")
         return {"error": "Plan is missing.", "messages": []}

    # --- 1. 准备 Prompt (不变) ---
    plan_json_str = json.dumps(plan, indent=2, ensure_ascii=False)
    desc_list = [f"- {name}: {desc}" for name, desc in agent_description_map.items()]
    desc_list.append(f"- {supervisor_name}: Coordinates tasks...")
    agent_descriptions_str = "\n".join(desc_list)
    system_prompt_text = "Error loading/formatting prompt"
    try:
         current_date_str = datetime.now().strftime("%a, %b %d, %Y")
         system_prompt_text = SUPERVISOR_PLANNING_PROMPT_TEMPLATE.format(
             plan_json=plan_json_str, 
             agent_descriptions=agent_descriptions_str, 
             current_date=current_date_str
         )
    except Exception as e: print(f"ERROR loading/formatting prompt: {e}")
    llm_input_messages = [SystemMessage(content=system_prompt_text)] + messages

    # --- 2. 调用 Supervisor LLM (不变) ---
    print("--- Calling Supervisor LLM ---"); response=None; llm_error_msg=None
    try: 
        response = await model.ainvoke(llm_input_messages, config=config)
        if not isinstance(response, AIMessage): raise TypeError(f"LLM returned non-AIMessage: {type(response)}")
        if not response.name: response.name = supervisor_name
        print(f"Supervisor LLM Raw Response Content: {response.content[:300]}...")
        if response.tool_calls: print(f"Supervisor LLM Tool Calls: {response.tool_calls}")
        messages_to_add = [response]
    except Exception as e: 
        print(f"!!! Error invoking Supervisor LLM: {e}"); traceback.print_exc()
        llm_error_msg = f"LLM failed: {e}"; messages_to_add = []; response = None

    # --- 3. 处理 LLM 回复 ---
    plan_updated: bool = False
    updated_plan: Optional[Plan] = copy.deepcopy(plan) # 从当前 plan 开始
    directive_error_msg: Optional[str] = None
    task_id_to_delegate: Optional[str] = None # <-- 存储本轮要委派的任务 ID

    if response and isinstance(response.content, str):
        # --- A. 先解析并执行所有 PLAN_UPDATE 指令 (移除 status='completed/failed' 的处理) ---
        try:
            plan_directives = re.findall(r"PLAN_UPDATE:\s*(\w+)\s*(\{.*?\})\s*$", response.content, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            plan_directives.extend(re.findall(r"PLAN_UPDATE:\s*(FINISH_PLAN)\s*(\{\})\s*$", response.content, re.IGNORECASE | re.DOTALL | re.MULTILINE))

            if plan_directives:
                 print(f"Found {len(plan_directives)} PLAN_UPDATE directive(s).")
                 for command, args_json_str in plan_directives:
                      command = command.upper(); args_json_str = args_json_str if args_json_str else "{}"
                      print(f"Processing directive: {command} with args JSON: {args_json_str[:100]}...")
                      try:
                           args = json.loads(args_json_str) # 使用 JSON 解析
                           if not isinstance(args, dict): raise ValueError("Args not dict.")

                           # --- 执行规划指令 ---
                           if command == "ADD_TASKS":
                                if not updated_plan: raise ValueError("No plan."); tasks=args.get("tasks",[])
                                if isinstance(tasks, list): 
                                    # 确保新任务状态是 pending
                                    for task_data in tasks: task_data['status'] = 'pending'
                                    updated_plan = PlanningStateHandler.add_tasks(updated_plan, tasks); plan_updated = True
                                else: raise ValueError("Invalid 'tasks'.")

                           elif command == "UPDATE_TASK":
                                if not updated_plan: raise ValueError("No plan.")
                                by_id=args.get("by_id")
                                if not by_id or not isinstance(by_id, str): raise ValueError("Requires string 'by_id'.")
                                by_id = by_id.strip()
                                task_exists = PlanningStateHandler.get_task(updated_plan, by_id)
                                if not task_exists: raise ValueError(f"Task ID '{by_id}' not found!")
                                
                                # 只处理状态为 'in_progress' 或 其他非终结状态的更新，以及 notes/evaluation
                                new_status=args.get("status"); notes_text=args.get("notes"); eval_text=args.get("evaluation") # 保留 evaluation 用于记录 LLM 的想法
                                update_kwargs = {}
                                # **不再**设置 "completed", "failed", "pending_review"
                                if new_status and new_status == "in_progress": 
                                     update_kwargs['new_status'] = "in_progress"
                                     task_id_to_delegate = by_id # 记录这个 ID，将在 Handoff 前设置
                                # 总是可以更新 notes 和 evaluation (如果 LLM 提供了)
                                if notes_text is not None: update_kwargs['new_notes'] = notes_text
                                if eval_text is not None: update_kwargs['new_evaluation'] = eval_text 

                                if update_kwargs: # 只有当确实需要更新时才调用
                                     print(f"Updating task {by_id} with: {update_kwargs}")
                                     updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=by_id, **update_kwargs); plan_updated = True

                           elif command == "FINISH_PLAN":
                                if not updated_plan: raise ValueError("No plan.")
                                updated_plan = PlanningStateHandler.finish_plan(updated_plan); plan_updated = True
                           
                           else: print(f"Warning: Unknown PLAN_UPDATE command '{command}' ignored by Supervisor.")

                      except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                           err_msg = f"Error processing plan directive '{command} {args_json_str}': {type(e).__name__} - {e}"
                           print(err_msg); traceback.print_exc()
                           if not directive_error_msg: directive_error_msg = err_msg # 只记录第一个错误
                      except Exception as e:
                           err_msg = f"Unexpected error processing directive '{command} {args_json_str}': {type(e).__name__} - {e}"
                           print(err_msg); traceback.print_exc()
                           if not directive_error_msg: directive_error_msg = err_msg
                 
                 # --- 重新计算 Plan 状态 ---
                 if plan_updated and updated_plan:
                      updated_plan = PlanningStateHandler.update_plan_status(updated_plan)
                      print(f"Plan status after updates by Supervisor: {updated_plan.get('status')}")

        except Exception as outer_e:
             err_msg = f"Error occurred while searching for PLAN_UPDATE directives: {outer_e}"
             print(err_msg); traceback.print_exc()
             if not directive_error_msg: directive_error_msg = err_msg

    # --- B. 检查 Tool Calls 并设置 Current Task ID ---
    handoff_tool_call: Optional[Dict] = None # 显式初始化
    if response and response.tool_calls:
        for tool_call in response.tool_calls:
             agent_name_match = re.match(r"transfer_to_(\w+)", tool_call["name"])
             # **使用 agent_description_map.keys() 来检查**
             if agent_name_match and agent_name_match.group(1) in agent_description_map.keys():
                  handoff_tool_call = cast(Dict, tool_call) # 找到第一个有效的就用它
                  break

    # 如果决定 Handoff，尝试设置 plan 中的 current_task_id
    if handoff_tool_call and updated_plan:
         # **关键**: 尝试从 Tool Call 的 args 中获取 task_id (Prompt 要求 LLM 必须提供)
         tool_args = handoff_tool_call.get("args", {})
         task_id_from_tool = tool_args.get("task_id") if isinstance(tool_args, dict) else None
         
         # 如果 Tool args 中没有，再使用之前记录的 task_id_to_delegate (标记为 in_progress 的)
         effective_task_id = task_id_from_tool or task_id_to_delegate 

         if effective_task_id:
             print(f"Setting current_task_id in plan to: {effective_task_id}")
             try:
                 # 验证 ID 存在
                 if PlanningStateHandler.get_task(updated_plan, effective_task_id):
                      updated_plan = PlanningStateHandler.set_current_task(updated_plan, effective_task_id)
                      # plan_updated 标志可能已经被 Plan Directive 设置，这里不需要重复设置
                 else:
                      print(f"Warning: Task ID '{effective_task_id}' provided for delegation not found. Cannot set current_task_id.")
                      # 记录错误，阻止 Handoff? 或者让路由回到 Supervisor?
                      directive_error_msg = directive_error_msg or f"Invalid Task ID '{effective_task_id}' for delegation."
             except Exception as e:
                   err_msg = f"Error setting current_task_id to '{effective_task_id}': {e}"
                   print(f"ERROR: {err_msg}")
                   if not directive_error_msg: directive_error_msg = err_msg

    # --- 4. 准备最终返回的状态更新字典 ---
    updates: Dict[str, Any] = {"messages": messages_to_add}
    if updated_plan is not None: updates["plan"] = updated_plan
    elif plan is not None: updates["plan"] = plan
    
    final_error = llm_error_msg or directive_error_msg
    if final_error: updates["error"] = final_error
    elif state.get("error"): updates["error"] = None # 清除旧错误

    print(f"--- Exiting Supervisor Node. Plan updated this step: {plan_updated} ---")
    return updates