# reason_graph/planning_handler.py
import uuid
import datetime
from typing import List, Dict, Optional, Any
from .state_schema import TaskStatus, PlanningStatus, Task, Plan # 从 state_schema 导入类型

class PlanningStateHandler:
    """
    使用静态方法管理一个表示项目计划的字典。
    计划现在存储在 LangGraph 的状态中，此类提供操作该字典的函数。
    """

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _gen_id() -> str:
        # 生成更易读的任务 ID (可选)
        # return f"task_{str(uuid.uuid4())[:8]}"
        return str(uuid.uuid4())

    @staticmethod
    def create_plan(title: str, description: str) -> Plan:
        """创建一个新的 Plan 字典"""
        now = PlanningStateHandler._now()
        return Plan(
            title=title,
            description=description,
            status="planning",  # 初始状态为规划中
            tasks=[],
            current_task_id=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

    @staticmethod
    def create_task(description: str,
                    agent: Optional[str] = None,
                    dependencies: Optional[List[str]] = None) -> Task:
        """创建一个新的 Task 字典"""
        now = PlanningStateHandler._now()
        return Task(
            id=PlanningStateHandler._gen_id(),
            description=description.strip(),
            status="pending", # 初始状态为待处理
            agent=agent.strip() if agent else None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            dependencies=dependencies or [],
            notes=None,
            evaluation=None,
            result=None,
        )

    @staticmethod
    def add_tasks(plan: Plan, tasks_data: List[Dict[str, Any]]) -> Plan:
        """向 Plan 字典中添加任务"""
        if not isinstance(plan, dict) or "tasks" not in plan:
             raise ValueError("Invalid plan structure provided.")
        if not isinstance(tasks_data, list):
             raise ValueError("tasks_data must be a list of task dictionaries.")

        for tinfo in tasks_data:
            desc = tinfo.get("description")
            if not desc: continue # 跳过没有描述的任务
            agent = tinfo.get("agent")
            deps = tinfo.get("dependencies")
            task = PlanningStateHandler.create_task(desc, agent, deps)
            plan["tasks"].append(task)

        # 如果添加任务时计划仍在 planning 阶段，可以转为 ready
        if plan.get("status") == "planning":
             plan["status"] = "ready"

        plan["updated_at"] = PlanningStateHandler._now()
        return plan

    @staticmethod
    def update_task(plan: Plan,
                    by_id: Optional[str] = None,
                    new_desc: Optional[str] = None,
                    new_status: Optional[TaskStatus] = None,
                    new_agent: Optional[str] = None,
                    new_notes: Optional[str] = None,
                    new_evaluation: Optional[str] = None,
                    new_result: Optional[Any] = None) -> Plan:
        """更新 Plan 字典中指定 ID 的任务"""
        if not isinstance(plan, dict) or "tasks" not in plan:
             raise ValueError("Invalid plan structure provided.")
        if not by_id:
            raise ValueError("Must provide 'by_id' to update a task.")

        task = next((t for t in plan["tasks"] if t.get("id") == by_id), None)
        if not task:
            raise ValueError(f"No matching task found with ID: {by_id}")

        updated = False
        if new_desc is not None and task.get("description") != new_desc.strip():
            task["description"] = new_desc.strip()
            updated = True
        if new_status is not None and task.get("status") != new_status.strip():
            task["status"] = new_status.strip()
            if new_status.strip() == "completed":
                task["completed_at"] = PlanningStateHandler._now()
            updated = True
        if new_agent is not None and task.get("agent") != new_agent.strip():
            task["agent"] = new_agent.strip()
            updated = True
        if new_notes is not None and task.get("notes") != new_notes.strip():
            task["notes"] = new_notes.strip()
            updated = True
        if new_evaluation is not None and task.get("evaluation") != new_evaluation.strip():
            task["evaluation"] = new_evaluation.strip()
            updated = True
        if new_result is not None: # 直接更新结果（谨慎使用，可能很大）
             task["result"] = new_result
             updated = True

        if updated:
            task["updated_at"] = PlanningStateHandler._now()
            plan["updated_at"] = PlanningStateHandler._now() # 更新整个计划的更新时间

        # 检查并更新整个计划的状态
        plan = PlanningStateHandler.update_plan_status(plan)

        return plan

    @staticmethod
    def update_plan_status(plan: Plan) -> Plan:
         """根据任务状态自动更新计划状态"""
         if not isinstance(plan, dict) or "tasks" not in plan:
              return plan # Return as is if invalid

         tasks = plan["tasks"]
         if not tasks: # 没有任务
              if plan.get("status") not in ["completed", "failed", "error"]:
                   plan["status"] = "ready" # 或 "completed" 如果没有任务就算完成? 设为 ready 似乎更合理
              return plan

         all_completed = all(t.get("status") == "completed" for t in tasks)
         any_failed = any(t.get("status") == "failed" for t in tasks)
         any_in_progress = any(t.get("status") in ["in_progress", "pending_review"] for t in tasks)
         any_pending = any(t.get("status") == "pending" for t in tasks)

         current_status = plan.get("status")
         new_status = current_status

         if any_failed:
             new_status = "failed" # 或 "error"
         elif all_completed:
             new_status = "completed"
             plan["completed_at"] = PlanningStateHandler._now()
         elif any_in_progress:
             new_status = "executing"
         elif any_pending or not any_in_progress: # 如果还有 pending 或所有任务都结束了但不是 completed/failed
              if current_status not in ["completed", "failed", "error"]: # 避免覆盖最终状态
                 new_status = "ready" # 准备好执行或等待新任务

         if new_status != current_status:
              plan["status"] = new_status
              plan["updated_at"] = PlanningStateHandler._now()

         return plan

    @staticmethod
    def set_current_task(plan: Plan, task_id: Optional[str]) -> Plan:
        """设置 Plan 字典中的当前任务 ID"""
        if not isinstance(plan, dict):
             raise ValueError("Invalid plan structure provided.")

        if task_id is None:
             plan["current_task_id"] = None
             plan["updated_at"] = PlanningStateHandler._now()
             return plan

        found = any(t.get("id") == task_id for t in plan.get("tasks", []))
        if not found:
            raise ValueError(f"Task ID '{task_id}' not found in plan.")

        if plan.get("current_task_id") != task_id:
            plan["current_task_id"] = task_id
            plan["updated_at"] = PlanningStateHandler._now()
        return plan

    @staticmethod
    def get_task(plan: Plan, task_id: str) -> Optional[Task]:
         """根据 ID 获取任务字典"""
         if not isinstance(plan, dict) or "tasks" not in plan:
              return None
         return next((t for t in plan["tasks"] if t.get("id") == task_id), None)

    @staticmethod
    def get_next_pending_task(plan: Plan) -> Optional[Task]:
         """获取下一个处于 pending 状态且所有依赖已完成的任务"""
         if not isinstance(plan, dict) or "tasks" not in plan:
              return None

         completed_task_ids = {t["id"] for t in plan["tasks"] if t.get("status") == "completed"}

         for task in plan["tasks"]:
              if task.get("status") == "pending":
                   dependencies = task.get("dependencies", [])
                   if not dependencies or all(dep_id in completed_task_ids for dep_id in dependencies):
                        return task
         return None # 没有找到合适的下一个任务

    @staticmethod
    def finish_plan(plan: Plan) -> Plan:
        """强制将 Plan 标记为完成"""
        if not isinstance(plan, dict):
             raise ValueError("Invalid plan structure provided.")
        if plan.get("status") != "completed":
            plan["status"] = "completed"
            plan["completed_at"] = PlanningStateHandler._now()
            plan["updated_at"] = PlanningStateHandler._now()
        return plan