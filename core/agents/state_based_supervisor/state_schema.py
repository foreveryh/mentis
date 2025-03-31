# reason_graph/state_schema.py
import operator
from typing import Dict, List, Optional, Any, Literal, TypedDict, Sequence, Annotated, Union
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.managed import IsLastStep, RemainingSteps

# 定义计划状态类型
PlanningStatus = Literal["not_started", "planning", "ready", "executing", "completed", "failed", "error"]

# 定义任务状态类型
TaskStatus = Literal["pending", "ready", "in_progress", "completed", "failed", "skipped", "pending_review", "revision_needed"]

# 定义任务项
class Task(TypedDict, total=False):
    """任务项定义

    表示计划中的一个任务项，包含任务描述、状态、分配的代理等信息
    """
    id: str  # 任务唯一标识符
    description: str  # 任务描述
    status: TaskStatus  # 任务状态
    agent: Optional[str]  # 分配的代理名称 (建议的执行者)
    created_at: str  # 创建时间 (ISO 格式)
    updated_at: str  # 更新时间 (ISO 格式)
    completed_at: Optional[str]  # 完成时间 (ISO 格式)
    dependencies: Optional[List[str]]  # 依赖的任务ID列表
    notes: Optional[str]  # 关于任务执行情况的备注 (可由 Agent 或 Supervisor 更新)
    evaluation: Optional[str] # 对任务完成情况的评估 (可由 Supervisor LLM 或 Evaluator Agent 更新)
    result: Optional[Any] # (可选) 存储任务的直接输出结果摘要

# 定义计划
class Plan(TypedDict, total=False):
    """计划定义

    表示一个完整的计划，包含计划状态、任务列表等信息
    """
    status: PlanningStatus  # 计划状态
    tasks: List[Task]  # 任务列表
    current_task_id: Optional[str]  # 当前 Supervisor 关注或正在处理的任务ID
    created_at: str  # 创建时间 (ISO 格式)
    updated_at: str  # 更新时间 (ISO 格式)
    completed_at: Optional[str]  # 完成时间 (ISO 格式)
    title: Optional[str]  # 计划标题
    description: Optional[str]  # 计划描述 (通常是用户原始请求)

# 扩展基础 AgentState 以支持计划功能
class PlanningAgentState(TypedDict):
    """支持计划功能的、用于 Supervisor 图的状态定义"""
    messages: Annotated[Sequence[BaseMessage], add_messages] # 消息历史
    plan: Optional[Plan] = None # 存储计划对象
    # last_agent_result: Optional[Dict[str, Any]] = None # 存储刚结束的子 Agent 的 {name: ..., content: ...}
    is_last_step: IsLastStep # LangGraph 内部状态
    remaining_steps: RemainingSteps # LangGraph 内部状态, 用于防止无限循环
    error: Optional[str] = None # 用于记录执行中发生的错误信息
    # 可以根据需要添加其他全局共享的状态字段
    # 例如: shared_context: Optional[Dict] = None

# 可以为子 Agent 定义一个稍微不同的状态（如果它们不需要 plan）
class BasicAgentState(TypedDict):
    """基础 Agent 状态，仅包含消息历史"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
    error: Optional[str] = None

# 方便类型提示
StateSchemaType = Union[Dict[str, Any], PlanningAgentState, BasicAgentState]