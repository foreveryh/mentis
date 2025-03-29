import uuid
import datetime
from typing import List, Dict, Optional

class PlanningStateHandler:
    """
    Manages a project plan.
    A plan is a dict with:
      - title (str)
      - description (str)
      - status (str): "planning", "in_progress", or "completed"
      - tasks (list): each task is a dict with:
           id, description, status, agent, notes, evaluation
      - current_task_id (str or None)
      - created_at (str)
      - updated_at (str)
    """

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().isoformat()

    @staticmethod
    def _gen_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def create_plan(title: str, description: str) -> Dict:
        now = PlanningStateHandler._now()
        return {
            "title": title,
            "description": description,
            "status": "planning",  # initial status
            "tasks": [],
            "current_task_id": None,
            "created_at": now,
            "updated_at": now
        }

    @staticmethod
    def create_task(description: str,
                    status: str = "pending",
                    agent: str = "",
                    notes: str = "",
                    evaluation: str = "") -> Dict:
        return {
            "id": PlanningStateHandler._gen_id(),
            "description": description.strip(),
            "status": status.strip() if status else "pending",
            "agent": agent.strip(),
            "notes": notes.strip(),
            "evaluation": evaluation.strip()
        }

    @staticmethod
    def add_tasks(plan: Dict, tasks_data: List[Dict]) -> Dict:
        for tinfo in tasks_data:
            desc = tinfo.get("description", "Untitled Task")
            status = tinfo.get("status", "pending")
            agent = tinfo.get("agent", "")
            notes = tinfo.get("notes", "")
            eval_ = tinfo.get("evaluation", "")
            task = PlanningStateHandler.create_task(desc, status, agent, notes, eval_)
            plan["tasks"].append(task)
        plan["updated_at"] = PlanningStateHandler._now()
        return plan

    @staticmethod
    def update_task(plan: Dict,
                    by_id: Optional[str] = None,
                    new_desc: Optional[str] = None,
                    new_status: Optional[str] = None,
                    new_agent: Optional[str] = None,
                    new_notes: Optional[str] = None,
                    new_evaluation: Optional[str] = None) -> Dict:
        """
        Update a task identified by by_id.
        """
        if not by_id:
            raise ValueError("Must provide 'by_id' to update a task.")
        task = next((t for t in plan["tasks"] if t["id"] == by_id), None)
        if not task:
            raise ValueError("No matching task found with the given ID.")

        if new_desc is not None:
            task["description"] = new_desc.strip()
        if new_status is not None:
            task["status"] = new_status.strip()
        if new_agent is not None:
            task["agent"] = new_agent.strip()
        if new_notes is not None:
            task["notes"] = new_notes.strip()
        if new_evaluation is not None:
            task["evaluation"] = new_evaluation.strip()

        plan["updated_at"] = PlanningStateHandler._now()

        # Determine overall plan status
        if any(t["status"] == "in_progress" for t in plan["tasks"]):
            plan["status"] = "in_progress"
        if all(t["status"] == "completed" for t in plan["tasks"]) and plan["tasks"]:
            plan["status"] = "completed"

        return plan

    @staticmethod
    def set_current_task(plan: Dict, task_id: str) -> Dict:
        found = any(t["id"] == task_id for t in plan["tasks"])
        if not found:
            raise ValueError("Task ID not found in plan.")
        plan["current_task_id"] = task_id
        plan["updated_at"] = PlanningStateHandler._now()
        return plan

    @staticmethod
    def finish_plan(plan: Dict) -> Dict:
        """
        Forcefully mark the plan as completed.
        """
        plan["status"] = "completed"
        plan["updated_at"] = PlanningStateHandler._now()
        return plan