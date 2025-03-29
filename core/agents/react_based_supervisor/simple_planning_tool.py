import json
from typing import Dict, List, Optional
from langchain_core.tools import BaseTool
from core.agents.supervisor.planning_handler import PlanningStateHandler

class SimplePlanningTool(BaseTool):
    """
    A tool that manages a single project plan in memory.
    It supports creating, viewing, adding tasks, updating tasks, setting the current task,
    and finishing the plan. All operations return a JSON string.
    """
    name: str = "planning"
    description: str = ("Manage a project plan with actions to create, view, add tasks, update tasks, "
                        "set current task, and finish the plan. All data is stored in JSON.")

    def __init__(self):
        super().__init__()
        self._plan: Optional[Dict] = None

    def _run(self, action: str, **kwargs) -> str:
        try:
            if action == "create_plan":
                return self._handle_create_plan(**kwargs)
            elif action == "view_plan":
                return self._handle_view_plan()
            elif action == "add_tasks":
                return self._handle_add_tasks(**kwargs)
            elif action == "update_task":
                return self._handle_update_task(**kwargs)
            elif action == "set_current_task":
                return self._handle_set_current_task(**kwargs)
            elif action == "finish_plan":
                return self._handle_finish_plan()
            else:
                return self._json_error(f"Unknown action: {action}")
        except Exception as e:
            return self._json_error(str(e))

    async def _arun(self, action: str, **kwargs) -> str:
        return self._run(action, **kwargs)

    def _handle_create_plan(self, **kwargs) -> str:
        title = kwargs.get("title", "Untitled Plan")
        description = kwargs.get("description", "")
        tasks_data = kwargs.get("tasks", [])
        new_plan = PlanningStateHandler.create_plan(title, description)
        PlanningStateHandler.add_tasks(new_plan, tasks_data)
        self._plan = new_plan
        return self._json_ok(self._plan)

    def _handle_view_plan(self) -> str:
        if not self._plan:
            self._plan = PlanningStateHandler.create_plan("Untitled", "")
        return self._json_ok(self._plan)

    def _handle_add_tasks(self, **kwargs) -> str:
        if not self._plan:
            self._plan = PlanningStateHandler.create_plan("Untitled", "")
        tasks_data = kwargs.get("tasks", [])
        PlanningStateHandler.add_tasks(self._plan, tasks_data)
        return self._json_ok(self._plan)

    def _handle_update_task(self, **kwargs) -> str:
        if not self._plan:
            raise ValueError("No plan exists. Please create a plan first.")
        # Use 'by_id' instead of 'task_id'
        by_id = kwargs.get("by_id")
        new_desc = kwargs.get("description")
        new_status = kwargs.get("status")
        new_agent = kwargs.get("agent")
        new_notes = kwargs.get("notes")
        new_evaluation = kwargs.get("evaluation")
        updated = PlanningStateHandler.update_task(
            self._plan,
            by_id=by_id,
            new_desc=new_desc,
            new_status=new_status,
            new_agent=new_agent,
            new_notes=new_notes,
            new_evaluation=new_evaluation
        )
        self._plan = updated
        return self._json_ok(self._plan)

    def _handle_set_current_task(self, **kwargs) -> str:
        if not self._plan:
            raise ValueError("No plan available to set current task.")
        tid = kwargs.get("task_id")
        if not tid:
            raise ValueError("Must provide 'task_id' for set_current_task.")
        PlanningStateHandler.set_current_task(self._plan, tid)
        return self._json_ok(self._plan)

    def _handle_finish_plan(self) -> str:
        if not self._plan:
            raise ValueError("No plan exists to finish.")
        finished_plan = PlanningStateHandler.finish_plan(self._plan)
        self._plan = finished_plan
        return self._json_ok(finished_plan)

    def _json_ok(self, plan_data: Dict) -> str:
        return json.dumps({"ok": True, "plan": plan_data}, ensure_ascii=False, indent=2)

    def _json_error(self, message: str) -> str:
        return json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2)