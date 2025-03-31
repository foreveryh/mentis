# reason_graph/evaluate_result_node.py

import json
import time
import copy
import traceback
import anyio # 用于同步包装器
from typing import Dict, Any, List, Optional, Union
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

# 内部导入 (确保路径正确)
try:
    from .state_schema import PlanningAgentState, TaskStatus, Plan, Task 
    from .planning_handler import PlanningStateHandler
except ImportError as e:
    print(f"Error importing modules in evaluate_result_node.py: {e}")
    # Fallbacks for type hints
    class PlanningAgentState(Dict): pass
    class Plan(Dict): pass
    class Task(Dict): pass
    TaskStatus = str 
    class PlanningStateHandler: 
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
    评估子 Agent 返回结果并更新计划状态的节点逻辑 (异步)。
    """
    print(f"--- Entering Evaluate Result Node ---")
    messages: List[BaseMessage] = state.get('messages', [])
    plan: Optional[Plan] = state.get('plan')
    last_message = messages[-1] if messages else None
    error_message: Optional[str] = None
    plan_updated: bool = False
    # 从当前状态创建 plan 的副本进行修改
    updated_plan: Optional[Plan] = copy.deepcopy(plan) if plan else None 

    if not updated_plan:
        print("Evaluate Result Node: No plan found in state. Skipping.")
        # 如果没有 plan，直接返回，不修改状态
        return {} 

    # 1. 确定刚刚执行的任务 ID (从 plan 的 current_task_id 获取)
    current_task_id = updated_plan.get("current_task_id")
    if not current_task_id:
        print("Warning: Evaluate Result Node - No current_task_id found in plan.")
        # 查找唯一一个 'in_progress' 的任务作为后备
        in_progress_tasks = [t for t in updated_plan.get('tasks', []) if t.get('status') == 'in_progress']
        if len(in_progress_tasks) == 1:
            current_task_id = in_progress_tasks[0].get('id')
            print(f"  Fallback: Found single in_progress task: {current_task_id}")
        else:
            error_message = "Evaluation failed: Cannot determine which task finished."
            print(f"ERROR: {error_message}")
            # 返回错误和未修改的 Plan (以防万一)
            return {"plan": plan, "error": error_message, "messages": []} 

    # 2. 获取子 Agent 的回复内容
    agent_result_content: Optional[str] = None
    agent_name: Optional[str] = None
    if isinstance(last_message, AIMessage): 
        agent_result_content = str(last_message.content) if last_message.content else ""
        agent_name = last_message.name or "SubAgent" # 获取 Agent 名称
        print(f"  Evaluating result from: {agent_name} for task ID: {current_task_id}")
    else:
        agent_result_content = f"Error: Expected AIMessage result, got {type(last_message).__name__}."
        agent_name = "System/Error"
        print(f"Warning: Evaluate Result Node - Last message not AIMessage. Assuming task failed for {current_task_id}.")


    # 3. 简单的评估逻辑 (判断成功/失败)
    new_status: TaskStatus = "completed" # 默认为完成 (字符串)
    evaluation_notes = f"Result received from {agent_name}."

    failure_keywords = ["error", "fail", "unable to", "cannot", "exception", "错误", "失败", "无法"]
    if not agent_result_content or \
       any(kw in agent_result_content.lower() for kw in failure_keywords):
        new_status = "failed" # 使用字符串
        evaluation_notes = f"Task likely failed based on result from {agent_name}: {agent_result_content[:150]}..."
        print(f"  Task {current_task_id} evaluated as FAILED.")
    else:
        print(f"  Task {current_task_id} evaluated as COMPLETED.")
        # new_status 保持为 "completed"

    # 4. 使用 PlanningStateHandler 更新 Plan 状态
    try:
        # 准备更新参数
        update_kwargs = {
            "new_status": new_status, 
            "new_evaluation": evaluation_notes,
            # 存储结果摘要到 notes 字段
            "new_notes": agent_result_content[:1000] + "..." if agent_result_content and len(agent_result_content) > 1000 else agent_result_content 
        }
        print(f"  Updating task {current_task_id} with: {{'status': '{new_status}', ...}}")
        
        # 确保 updated_plan 是有效的
        if updated_plan and PlanningStateHandler.get_task(updated_plan, current_task_id):
             updated_plan = PlanningStateHandler.update_task(updated_plan, by_id=current_task_id, **update_kwargs)
             # 清除 current_task_id - 表示此任务处理完毕
             updated_plan = PlanningStateHandler.set_current_task(updated_plan, None) 
             # 重新计算计划整体状态 (例如，检查是否所有任务都 completed)
             updated_plan = PlanningStateHandler.update_plan_status(updated_plan)
             print(f"  Plan status after evaluation update: {updated_plan.get('status')}")
             plan_updated = True
        else:
             raise ValueError(f"Task ID '{current_task_id}' not found or plan is invalid before update.")

    except ValueError as ve: 
        error_message = f"Error updating plan in Evaluate Result Node: {ve}"
        print(f"ERROR: {error_message}")
        traceback.print_exc()
    except Exception as e:
        error_message = f"Unexpected error updating plan in Evaluate Result Node: {e}"
        print(f"ERROR: {error_message}"); traceback.print_exc()

    # 5. 准备返回字典
    updates: Dict[str, Any] = {}
    # **总是**返回 plan 状态
    if updated_plan is not None: 
        updates["plan"] = updated_plan 
    elif plan is not None: 
         updates["plan"] = plan # 如果更新出错，返回原始 plan

    # 记录本节点处理中遇到的错误
    if error_message: 
        updates["error"] = error_message 
    elif state.get("error"): # 如果没有新错误，清除之前的错误
         updates["error"] = None 

    # 清除 last_agent_result (如果存在的话，虽然现在不需要了)
    # if "last_agent_result" in state: updates["last_agent_result"] = None 

    # Evaluator 节点通常不添加消息到 history，只更新 plan 和 error
    updates["messages"] = [] # 返回空列表表示不添加新消息

    print(f"--- Exiting Evaluate Result Node. Plan updated: {plan_updated} ---")
    return updates

# --- 同步包装器 ---
def evaluate_result_node_logic_sync(state: PlanningAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """evaluate_result_node_logic 的同步包装器"""
    print(f"--- Entering Evaluate Result Node (Sync Wrapper) ---")
    try:
        # 确保 anyio 已导入
        import anyio 
        return anyio.run(evaluate_result_node_logic, state, config) # type: ignore
    except Exception as e:
        print(f"Error running evaluate_result_node_logic synchronously: {e}")
        traceback.print_exc()
        # 返回包含错误的状态
        return {"error": f"Evaluate Result sync execution failed: {e}", "plan": state.get("plan"), "messages": []}