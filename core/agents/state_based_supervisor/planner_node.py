import re
import json
import time
import copy
import ast
import traceback
import anyio # <--- 导入 anyio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

# 内部导入
try:
    from .state_schema import PlanningAgentState, Plan
    from .planning_handler import PlanningStateHandler
    from .prompt import PLANNER_SYSTEM_PROMPT_TEMPLATE
except ImportError as e:
    print(f"Error importing modules in planner_node.py: {e}")
    class PlanningAgentState(Dict): pass; 
    class Plan(Dict): pass; 
    class PlanningStateHandler: pass
    PLANNER_SYSTEM_PROMPT_TEMPLATE = "Fallback Planner Prompt: Error loading template. Args: {agent_descriptions}"

# --- Planner 节点核心逻辑 (异步) ---
async def planner_node_logic(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any, # Planner 使用的 LLM
    agent_description_map: Dict[str, str] # 需要 Agent 描述来分配任务
) -> Dict[str, Any]:
    """Planner 节点逻辑：分析请求，生成初始计划"""
    print(f"--- Entering Planner Node ---")
    messages: List[BaseMessage] = state.get('messages', [])
    # Planner 通常在 plan 为空时运行
    plan: Optional[Plan] = state.get('plan')
    if plan:
         print("Planner Node: Plan already exists. Skipping plan creation.")
         # 如果计划已存在，Planner 不应再执行，直接返回当前状态？
         # 或者返回一个空更新，让图流向 Supervisor？
         # 返回空更新更安全，让 Supervisor 继续
         return {} # 返回空字典，状态不变

    if not messages:
         print("Planner Node: No messages found to create a plan from.")
         return {"error": "Planner received no messages."}

    # --- 1. 准备 Planner Prompt ---
    # Planner 只需要 Agent 描述，不需要 plan_json 或 current_date?
    # 可以让它知道日期
    desc_list = [f"- {name}: {desc}" for name, desc in agent_description_map.items()]
    agent_descriptions_str = "\n".join(desc_list)
    current_date_str = datetime.now().strftime("%a, %b %d, %Y") # Planner 也可能需要日期

    system_prompt_text = "Error: Planner prompt template could not be loaded/formatted."
    try:
        # 加载 Planner 的模板
        from .prompt import PLANNER_SYSTEM_PROMPT_TEMPLATE
        system_prompt_text = PLANNER_SYSTEM_PROMPT_TEMPLATE.format(
            agent_descriptions=agent_descriptions_str,
            # 如果 Planner Prompt 需要日期：
            current_date=current_date_str
        )
    except ImportError: print("ERROR: Could not import PLANNER_SYSTEM_PROMPT_TEMPLATE")
    except KeyError as e: print(f"ERROR: Missing key in planner prompt formatting: {e}")
    except Exception as e: print(f"ERROR: Unexpected error loading/formatting planner prompt: {e}")

    # Planner 的输入只需要 System Prompt 和用户的初始请求（通常是第一条）
    # 或者传递最后几条消息？为了简单，先只用第一条 HumanMessage
    initial_user_request = next((m for m in messages if isinstance(m, HumanMessage)), None)
    if not initial_user_request:
         print("Planner Node: No HumanMessage found in initial state.")
         return {"error": "Planner did not find initial user request."}

    llm_input_messages = [SystemMessage(content=system_prompt_text), initial_user_request]

    # --- 2. 调用 Planner LLM ---
    print("--- Calling Planner LLM ---")
    response: Optional[AIMessage] = None
    llm_error_msg: Optional[str] = None
    try:
        response = await model.ainvoke(llm_input_messages, config=config)
        if not isinstance(response, AIMessage): raise TypeError("Planner LLM returned non-AIMessage.")
        # Planner 的回复主要是指令，可以不设置 name
        print(f"Planner LLM Raw Response Content: {response.content[:300]}...")
        # Planner 不应该调用工具
        if response.tool_calls: print("Warning: Planner LLM unexpectedly generated tool calls!")
        messages_to_add: List[BaseMessage] = [response] # 可以选择是否将 Planner 的思考过程加入 history
    except Exception as e:
        print(f"!!! Error invoking Planner LLM: {e}"); traceback.print_exc()
        llm_error_msg = f"Planner LLM invocation failed: {e}"
        messages_to_add = []
        response = None

    # --- 3. 处理 Planner LLM 回复 (解析 CREATE_PLAN) ---
    new_plan: Optional[Plan] = None
    plan_updated: bool = False # 标记计划是否在本节点成功创建
    directive_error_msg: Optional[str] = None

    if response and isinstance(response.content, str):
        try:
            plan_match = re.search(r"PLAN_UPDATE:\s*CREATE_PLAN\s*(\{.*?\})\s*$", response.content, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            if plan_match:
                args_json_str = plan_match.group(1)
                print(f"Planner directive found: CREATE_PLAN with args: {args_json_str[:100]}...")
                try:
                     args = json.loads(args_json_str)
                     if not isinstance(args, dict): raise ValueError("Args JSON not a dict.")
                     
                     title=args.get("title", "Plan"); desc=args.get("description",""); tasks=args.get("tasks",[])
                     if isinstance(tasks, list) and all(isinstance(t, dict) and 'description' in t for t in tasks):
                          for task_data in tasks: task_data['status'] = 'pending' # 强制状态
                          new_plan = PlanningStateHandler.create_plan(title, desc)
                          new_plan = PlanningStateHandler.add_tasks(new_plan, tasks); plan_updated = True
                          print("DEBUG: Plan successfully created by Planner node.")
                     else: raise ValueError("Invalid 'tasks' format (must be list of dicts with 'description').")

                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                     err_msg = f"Error processing CREATE_PLAN directive: {type(e).__name__} - {e}"
                     print(err_msg); traceback.print_exc(); directive_error_msg = err_msg
                except Exception as e:
                     err_msg = f"Unexpected error processing CREATE_PLAN: {type(e).__name__} - {e}"
                     print(err_msg); traceback.print_exc(); directive_error_msg = err_msg
            else:
                 directive_error_msg = "Planner LLM did not output a valid PLAN_UPDATE: CREATE_PLAN directive."
                 print(f"Warning: {directive_error_msg}")
                 # 即使没有指令，也可能需要返回 Planner 的回复消息
                 # 但如果没有 plan，流程可能无法继续，所以记录错误

        except Exception as outer_e:
             directive_error_msg = f"Error searching for PLAN_UPDATE directive: {outer_e}"
             print(f"ERROR: {directive_error_msg}"); traceback.print_exc()

    # --- 4. 准备返回的状态更新 ---
    updates: Dict[str, Any] = {"messages": messages_to_add} # 添加 Planner 的回复消息
    if plan_updated and new_plan:
        updates["plan"] = new_plan # 返回新创建的 Plan
    
    final_error = llm_error_msg or directive_error_msg
    if final_error: # 记录 Planner 步骤中遇到的第一个错误
        updates["error"] = final_error

    print(f"--- Exiting Planner Node. Plan created: {plan_updated} ---")
    return updates


# --- Planner 节点的同步包装器 (使用 anyio) ---
def planner_node_logic_sync(
    state: PlanningAgentState,
    config: Optional[RunnableConfig],
    model: Any,
    agent_description_map: Dict[str, str]
) -> Dict[str, Any]:
    """planner_node_logic 的同步包装器"""
    print(f"--- Entering Planner Node (Sync Wrapper) ---")
    try:
        # 使用 anyio 在同步函数中运行异步函数
        return anyio.run( # type: ignore
            planner_node_logic, state, config, model, agent_description_map
        )
    except Exception as e:
        print(f"Error running planner_node_logic synchronously: {e}")
        traceback.print_exc()
        return {"error": f"Planner sync execution failed: {e}", "messages": state.get("messages",[])}