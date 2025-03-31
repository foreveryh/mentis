# reason_graph/evaluate_result_node.py

import json
import time
import copy
import traceback
import anyio 
from typing import Dict, Any, List, Optional, Union
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

# 内部导入 (确保路径正确)
try:
    from .state_schema import PlanningAgentState, TaskStatus, Plan, Task
    from .planning_handler import PlanningStateHandler
except ImportError as e:
    print(f"Error importing modules in evaluate_result_node.py: {e}")
    # Fallbacks
    class PlanningAgentState(Dict): pass; 
    class Plan(Dict): pass; 
    class Task(Dict): pass
    TaskStatus = str 
    class PlanningStateHandler: # Dummy
        @staticmethod 
        def update_task(plan, by_id, **kwargs): return plan
        @staticmethod
        def set_current_task(plan, task_id): return plan
        @staticmethod
        def get_task(plan, task_id): return None
        @staticmethod
        def update_plan_status(plan): return plan


async def evaluate_result_node_logic(state: PlanningAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """
    评估子 Agent 返回结果并更新计划状态的节点逻辑 (异步, 优化评估逻辑)。
    """
    print(f"--- Entering Evaluate Result Node ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan')
    last_message = messages[-1] if messages else None
    error_message: Optional[str] = None
    plan_updated: bool = False
    updated_plan: Optional[Plan] = copy.deepcopy(plan) if plan else None 

    if not updated_plan:
        print("Evaluate Result Node: No plan found in state. Skipping.")
        return {} 

    current_task_id = updated_plan.get("current_task_id")
    if not current_task_id:
        # Fallback logic for finding current task (不变)
        print("Warning: Evaluate Result Node - No current_task_id found in plan...")
        in_progress_tasks = [t for t in updated_plan.get('tasks', []) if t.get('status') == 'in_progress']
        if len(in_progress_tasks) == 1: current_task_id = in_progress_tasks[0].get('id'); print(f"  Fallback: Found task {current_task_id}")
        else: error_message = "Evaluation failed: Cannot determine finished task."; print(f"ERROR: {error_message}"); return {"plan": updated_plan, "error": error_message, "messages": []}

    agent_result_content: Optional[str] = None
    agent_name: Optional[str] = None
    if isinstance(last_message, AIMessage): 
        agent_result_content = str(last_message.content) if last_message.content is not None else "" # Ensure string
        agent_name = last_message.name or "SubAgent"
        print(f"  Evaluating result from: {agent_name} for task ID: {current_task_id}")
    else:
        agent_result_content = f"Error: Expected AIMessage result, got {type(last_message).__name__}."
        agent_name = "System/Error"
        print(f"Warning: Last message not AIMessage. Assuming task failed for {current_task_id}.")


    # --- 优化的评估逻辑 ---
    new_status: TaskStatus = "completed" # 默认成功
    evaluation_notes = f"Result received from {agent_name}."
    
    # 1. 检查是否为空内容 (或只有空白符)
    if agent_result_content is None or not agent_result_content.strip():
        new_status = "failed"
        evaluation_notes = f"Task failed: Agent {agent_name} returned empty content."
        print(f"  Task {current_task_id} evaluated as FAILED (Empty Result).")
    # 2. 检查是否以明确的错误标识开头 (需要工具配合)
    #    假设工具出错时会在返回字符串前加上 "Error: " 或 "Execution Failed: "
    elif agent_result_content.strip().startswith(("Error:", "Execution Failed:", "Tool Error:")):
        new_status = "failed"
        evaluation_notes = f"Task failed: Agent {agent_name} reported an error: {agent_result_content[:150]}..."
        print(f"  Task {current_task_id} evaluated as FAILED (Explicit Error Signal).")
    # 3. (可选) 添加其他特定检查，例如检查是否只是"我不明白"之类的回复
    elif len(agent_result_content) < 50 and any(kw in agent_result_content.lower() for kw in ["don't know", "cannot fulfill", "无法回答", "不明白"]):
         new_status = "failed" # 或 "pending_review" ? 暂时设为 failed
         evaluation_notes = f"Task likely failed: Agent {agent_name} indicated inability to fulfill request."
         print(f"  Task {current_task_id} evaluated as FAILED (Agent Indicated Inability).")
    else:
        # 如果以上都不是，则认为是成功
        new_status = "completed"
        print(f"  Task {current_task_id} evaluated as COMPLETED.")
    # --- 评估逻辑结束 ---


    # --- 更新 Plan 状态 (逻辑不变) ---
    try:
        update_kwargs = {
            "new_status": new_status, 
            "new_evaluation": evaluation_notes,
            "new_notes": agent_result_content[:1000] + "..." if agent_result_content and len(agent_result_content) > 1000 else agent_result_content 
        }
        print(f"  Updating task {current_task_id} with: {{'status': '{new_status}', ...}}")
        
        if updated_plan and PlanningStateHandler.get_task(updated_plan, current_task_id):
             updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=current_task_id, **update_kwargs)
             updated_plan = PlanningStateHandler.set_current_task(updated_plan, None) 
             updated_plan = PlanningStateHandler.update_plan_status(updated_plan)
             print(f"  Plan status after evaluation update: {updated_plan.get('status')}")
             plan_updated = True
        else:
             raise ValueError(f"Task ID '{current_task_id}' not found or plan invalid before update.")

    except ValueError as ve: error_message = f"Error updating plan: {ve}"; print(f"ERROR: {error_message}"); traceback.print_exc()
    except Exception as e: error_message = f"Unexpected error updating plan: {e}"; print(f"ERROR: {error_message}"); traceback.print_exc()

    # --- 准备返回字典 (逻辑不变) ---
    updates: Dict[str, Any] = {}
    if updated_plan is not None: updates["plan"] = updated_plan 
    elif plan is not None: updates["plan"] = plan 
    
    # 记录本节点错误，或清除旧错误
    current_state_error = state.get("error") 
    if error_message: updates["error"] = error_message 
    elif current_state_error: updates["error"] = None 

    updates["messages"] = [] # Evaluator 不添加消息

    print(f"--- Exiting Evaluate Result Node. Plan updated: {plan_updated} ---")
    return updates

# --- 同步包装器 (保持不变) ---
def evaluate_result_node_logic_sync(state: PlanningAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """evaluate_result_node_logic 的同步包装器"""
    print(f"--- Entering Evaluate Result Node (Sync Wrapper) ---")
    try:
        import anyio 
        return anyio.run(evaluate_result_node_logic, state, config) # type: ignore
    except Exception as e:
        print(f"Error running evaluate_result_node_logic synchronously: {e}")
        traceback.print_exc()
        return {"error": f"Evaluate Result sync execution failed: {e}", "plan": state.get("plan"), "messages": []}