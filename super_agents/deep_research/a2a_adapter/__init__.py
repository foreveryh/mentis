# super_agents/deep_research/a2a_adapter/__init__.py

# 确保导出关键组件
from super_agents.deep_research.a2a_adapter.deep_research_task_manager import DeepResearchTaskManager
from super_agents.deep_research.a2a_adapter.setup import setup_a2a_server

__all__ = ["DeepResearchTaskManager", "setup_a2a_server"]