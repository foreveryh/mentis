from typing import Dict, List, Optional, Any, Literal, TypedDict, Union
from langchain_core.messages import BaseMessage
from langgraph.prebuilt.chat_agent_executor import AgentState

# 定义计划状态类型
PlanningStatus = Literal["not_started", "planning", "executing", "completed", "failed"]

# 定义任务状态类型
TaskStatus = Literal["pending", "in_progress", "completed", "failed"]

# 定义任务项
class Task(TypedDict, total=False):
    """任务项定义
    
    表示计划中的一个任务项，包含任务描述、状态、分配的代理等信息
    """
    id: str  # 任务唯一标识符
    description: str  # 任务描述
    status: TaskStatus  # 任务状态
    agent: Optional[str]  # 分配的代理名称
    created_at: str  # 创建时间
    updated_at: str  # 更新时间
    completed_at: Optional[str]  # 完成时间
    dependencies: Optional[List[str]]  # 依赖的任务ID列表
    notes: Optional[str]  # 任务备注

# 定义计划
class Plan(TypedDict, total=False):
    """计划定义
    
    表示一个完整的计划，包含计划状态、任务列表等信息
    """
    status: PlanningStatus  # 计划状态
    tasks: List[Task]  # 任务列表
    current_task_id: Optional[str]  # 当前执行的任务ID
    created_at: str  # 创建时间
    updated_at: str  # 更新时间
    completed_at: Optional[str]  # 完成时间
    title: Optional[str]  # 计划标题
    description: Optional[str]  # 计划描述

# 扩展AgentState以支持计划功能
class PlanningAgentState(AgentState):
    """支持计划功能的代理状态
    
    扩展了AgentState，添加了plan字段用于存储计划信息
    """
    plan: Optional[Plan] = None