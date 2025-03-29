import asyncio
import json
import os
import re
import time 
from datetime import datetime 
from typing import Literal, List, Dict, Any, Optional, cast

# --- LangChain / LangGraph ---
try:
    # 使用 langchain_openai (或你选择的模型提供商)
    from langchain_openai import ChatOpenAI 
except ImportError:
     ChatOpenAI = None 
     print("Warning: langchain_openai not installed.")

# 核心消息类型
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage 
# LangChain 工具相关
from langchain_core.tools import tool, BaseTool 

# --- OpenAI 错误处理 ---
try:
    from openai import RateLimitError
except ImportError:
    class RateLimitError(Exception): pass

# --- 内部模块导入 (请确保路径正确) ---
try:
    # 假设这些是你当前的路径
    from core.agents.sb_supervisor_agent import SupervisorAgent 
    from core.agents.supervisor.state_schema import PlanningAgentState
    from core.agents.base.react_agent import ReactAgent # 导入 ReactAgent
    # 导入 StreamUpdate (如果需要在最终状态中检查它，但这里主要关注消息)
    # from core.agents.supervisor.schemas import StreamUpdate 

except ImportError as e:
    print(f"Error importing agent components: {e}")
    print("Please ensure paths like 'core.agents.sb_supervisor_agent' are correct.")

import traceback

# --- 定义 Web Search 工具 ---
# 使用 @tool 装饰器明确这是一个工具
@tool
def web_search(query: str) -> str:
    """Search the web for current information about a given query. Use this for recent events, data, or facts."""
    print(f"--- TOOL CALLED: web_search(query='{query}') ---") # 添加日志确认工具被调用
    # Mocked data - 实际使用时会调用 Tavily 或其他搜索引擎
    if "apple" in query.lower() and "headcount" in query.lower() and "2024" in query:
        return (
            "According to recent (mocked) reports for 2024, Apple's headcount is approximately 164,000 employees globally."
        )
    elif "joke" in query.lower():
         # 这个工具不适合讲笑话
         return "I am a web search tool, I cannot tell jokes."
    else:
        return f"Mock search results for query: '{query}'. Found relevant information on various websites."

# --- 主执行逻辑 ---
async def main():
     # --- 初始化 LLM (确保 API Key 在环境中) ---
     try:
        model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o") 
        print(f"Using LLM: {model_name}")
        if not ChatOpenAI: raise ImportError("ChatOpenAI not available.")
        # 使用温度稍高的模型可能有助于 ReAct 思考和调用工具
        model = ChatOpenAI(model=model_name, temperature=0.2) 
     except Exception as e:
         print(f"Failed to initialize ChatOpenAI model: {e}")
         return

     # --- 实例化 Agents ---
     try:
        # research_agent 现在有了一个明确定义的 web_search 工具
        research_agent = ReactAgent(
             name="research_expert", 
             tools=[web_search], # <--- 传入工具列表
             model=model,
             # 添加明确的 Prompt 引导工具使用
             prompt=(
                 "You are a research expert. Use available tools to find information. "
                 "You have access to 'web_search'. Use it for questions about current data, facts, or events."
             ),
             max_context_tokens=8000 
         ) 
         
        all_agents = [research_agent]

        # --- 实例化 Supervisor ---
        supervisor = SupervisorAgent(
             agents=all_agents,
             model=model, # Supervisor 使用相同的模型
             state_schema=PlanningAgentState, 
             include_agent_name="inline" 
             # checkpointer=... 
         )
     except Exception as e:
         print(f"Failed to initialize agents or supervisor: {e}")
         traceback.print_exc()
         return

     # --- 准备初始请求 ---
     # 用户请求包含两个意图：讲笑话 + 查信息
     user_request = (
                "Hi! I'd like to start with a short joke to lighten the mood, "
                "then please check Apple's headcount in 2024. Summarize both."
            )
     print(f"Initial Request: '{user_request}'")

     # --- 准备初始状态 ---
     initial_graph_state: PlanningAgentState = {
         "messages": [HumanMessage(content=user_request)], # 使用 HumanMessage
         "plan": None,
         "error": None
     }

     # --- 执行 Supervisor (使用 ainvoke) ---
     final_state: Optional[Dict[str, Any]] = None
     error_occurred: Optional[Exception] = None
     config = {"recursion_limit": 100} 

     try:
         print("\n--- Invoking Supervisor Agent (ainvoke) ---")
         final_state = await supervisor.ainvoke(initial_graph_state, config=config)
         print("\n--- Supervisor Agent Invocation Complete ---")

     # --- 错误处理 ---
     except RateLimitError as e: error_occurred = e; print(f"\n!!! OpenAI Quota Error: {e}")
     except Exception as e: error_occurred = e; print(f"\n!!! Error during graph execution: {e}"); traceback.print_exc()

     # --- 处理并打印最终结果 ---
     if error_occurred: print("\n--- Graph Execution INTERRUPTED or FAILED ---")
     else: print("\n--- Graph Execution Finished ---")

     if not final_state:
         print("Error: No final state available.")
         return

     print("\n--- FINAL STATE ---")
     # 打印错误（如果在状态中记录了）
     if final_state.get("error"): print(f"\nERROR RECORDED IN STATE: {final_state['error']}")
     # 打印计划
     final_plan = final_state.get('plan')
     if final_plan: print("\nFinal Plan State:", json.dumps(final_plan, indent=2, default=str))
     else: print("\nFinal Plan State: Not available.")
     # 打印消息历史
     final_messages = final_state.get("messages", [])
     if final_messages:
         print("\nFinal Message History (Last 10):")
         for m in final_messages[-10:]:
             try:
                 if hasattr(m, 'pretty_print'): m.pretty_print()
                 else: print(json.dumps(m, indent=2, default=str))
                 print("-" * 10)
             except Exception as print_err: print(f"Error printing final message: {print_err}")
     else: print("\nFinal Message History: Empty.")

     print("\n--- END OF TEST ---")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
    except Exception as e:
         print(f"\nAn unexpected top-level error occurred: {e}")
         traceback.print_exc()