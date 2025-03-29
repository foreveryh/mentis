# main.py (用于测试 State-Based Supervisor 和 ReactAgent)

import asyncio
import json
import os
from typing import Dict, Any, Optional
from langchain_community.tools import TavilySearchResults
# --- LangChain / LangGraph ---
# 假设模型直接在此初始化或从别处导入
from dotenv import load_dotenv
load_dotenv()  # 自动加载 .env 文件
try:
    from langchain_openai import ChatOpenAI # 或者你使用的其他模型
except ImportError:
     ChatOpenAI = None
     print("Warning: langchain_openai not installed.")

# 核心消息类型
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage

# --- OpenAI 错误处理 ---
try:
    from openai import RateLimitError
except ImportError:
    class RateLimitError(Exception): pass

# --- 内部模块导入 (请确保路径正确) ---
try:
    # 从你提供的 core.agents... 路径导入
    from core.agents.sb_supervisor_agent import SupervisorAgent # 你的 Supervisor 实现
    from core.agents.state_based_supervisor.state_schema import PlanningAgentState # 包含 Plan 的状态
    from core.agents.base.react_agent import ReactAgent # 你的 ReactAgent 实现
    from core.llm.llm_manager import LLMManager # LLM 管理器
    # (如果你的子 Agent 有更具体的类，在这里导入它们)
    # 例如:
    # from core.agents.researcher import ResearchAgent
    # from core.agents.coder import CoderAgent

    # --- 如果没有具体子 Agent 类，使用 ReactAgent 作为示例 ---
    # (确保 ReactAgent 可以被直接实例化用于测试)
    if not issubclass(ReactAgent, object): # 简单检查 ReactAgent 是否有效
         raise ImportError("ReactAgent class not found or invalid.")

except ImportError as e:
    print(f"Error importing agent components: {e}")
    print("Please ensure paths like 'core.agents.sb_supervisor_agent' are correct relative to your execution path.")

import traceback

# --- 主执行函数 (简化版，只关注最终结果) ---
async def run_supervisor_test(supervisor_agent: SupervisorAgent, initial_state: Dict[str, Any]):
    """Executes the supervisor graph using ainvoke and prints the final state."""

    print("--- Starting Supervisor Graph Test ---")
    # 获取初始消息列表，检查是否为空
    messages_list = initial_state.get("messages", [])
    initial_query = "N/A" # 默认值
    if messages_list:
        first_message = messages_list[0]
        # 检查第一个消息是否有 content 属性 (更健壮)
        if hasattr(first_message, 'content'):
            initial_query = first_message.content
        else:
             # 如果第一个元素不是预期的消息对象，记录一下
             print(f"Warning: First item in initial messages is not a standard message object: {type(first_message)}")
             initial_query = str(first_message) # 尝试转换为字符串
    print(f"Initial Query: '{initial_query}'")
    print("-" * 30)

    config = {"recursion_limit": 100} # 使用较高的递归限制
    final_state: Optional[Dict[str, Any]] = None
    error_occurred: Optional[Exception] = None

    try:
        print("--- Invoking Supervisor Agent (ainvoke) ---")
        # 直接调用 ainvoke 获取最终状态
        final_state = await supervisor_agent.ainvoke(initial_state, config=config)
        print("--- Supervisor Agent Invocation Complete ---")

    # --- 错误处理 ---
    except RateLimitError as e:
        error_occurred = e
        print("\n" + "="*40 + "\n!!! OpenAI API Error: Insufficient Quota !!!\n" + "="*40)
        print("Execution stopped. Check OpenAI plan/billing.")
        print(f"Original error: {e}")
    except TypeError as e:
         error_occurred = e
         print("\n" + "="*40 + "\n!!! TypeError During Graph Execution !!!\n" + "="*40)
         print(f"Error details: {e}")
         if "synchronous function provided" in str(e):
              print("Hint: Ensure all graph nodes support async or run the graph synchronously if needed.")
         traceback.print_exc()
    except Exception as e:
         error_occurred = e
         print("\n" + "="*40 + "\n!!! An Unexpected Error Occurred !!!\n" + "="*40)
         print(f"Error type: {type(e).__name__}\nError details: {e}")
         traceback.print_exc()

    # --- Process Final State ---
    if error_occurred: print("\n--- Graph Execution INTERRUPTED or FAILED ---")
    else: print("\n--- Graph Execution Finished ---")

    if not final_state:
         # 如果 ainvoke 返回 None 或在出错前未赋值 (理论上 ainvoke 会抛错或返回字典)
         print("Error: No final state available (Execution might have failed early).")
         # 尝试从 supervisor agent 获取最后状态 (如果 checkpointer 可用且实现了 get_state)
         if hasattr(supervisor_agent, 'checkpointer') and supervisor_agent.checkpointer and hasattr(supervisor_agent.checkpointer, 'get'):
             try:
                 # 需要知道配置中的 thread_id (这里假设是 'test_thread')
                 last_checkpoint = supervisor_agent.checkpointer.get({"configurable": {"thread_id": "test_thread"}})
                 if last_checkpoint:
                      print("Attempting to display last known checkpoint state:")
                      final_state = last_checkpoint.get('channel_values', {})
                 else:
                      print("Could not retrieve last checkpoint state.")
             except Exception as cp_err:
                  print(f"Error retrieving checkpoint state: {cp_err}")

    # 即使出错，也尝试打印 final_state (可能是包含错误信息的状态)
    if final_state and isinstance(final_state, dict):
        print("\n--- FINAL STATE ---")

        # 1. 打印错误信息 (如果存在)
        if final_state.get("error"):
             print(f"\nERROR RECORDED IN STATE: {final_state['error']}")

        # 2. 打印最终消息历史 (尝试 pretty_print)
        final_messages = final_state.get("messages", [])
        if final_messages and isinstance(final_messages, list):
             print("\nFinal Message History (Last ~10):")
             for m in final_messages[-10:]: # 只打印最后一部分
                  try:
                       if hasattr(m, 'pretty_print'):
                            m.pretty_print()
                       else: # Fallback for dict or other types
                            print(json.dumps(m, indent=2, default=str))
                       print("-" * 10)
                  except Exception as print_err:
                       print(f"Error printing final message: {print_err}")
        else:
             print("\nFinal Message History: Not available or empty.")

        # 3. 打印最终计划状态
        final_plan = final_state.get('plan')
        if final_plan and isinstance(final_plan, dict):
            print("\nFinal Plan State:")
            print(json.dumps(final_plan, indent=2, default=str))
        else:
            print("\nFinal Plan State: Not available or not generated.")

    else:
        print("\n--- No Final State Could Be Displayed ---")


    print("\n--- END OF TEST ---")
    return final_state

# --- Main Execution Block ---
async def main():
    # --- 1. 初始化 LLM 管理器 (它会自动注册配置好的模型) ---
    try:
        model_manager = LLMManager()
         # 可以选择打印一下注册了哪些模型
        print("Registered Models:", json.dumps(model_manager.list_models(), indent=2))
        print("Capability Mapping:", model_manager.list_capabilities())
    except Exception as e:
        print(f"Failed to initialize LLMManager: {e}")
        return

     # --- 2. 实例化 Agents (使用 ModelManager 获取模型) ---
    try:
         # 获取默认模型用于基础任务
        grok = model_manager.get_model("xai_grok") # 获取 ID 由 config 或第一个注册的决定
        deepseek_v3 = model_manager.get_model("deepseek_v3") # 获取 DeepSeek 模型
         # 创建Tavily搜索工具
        tavily_search = TavilySearchResults(
            max_results=3,
            include_answer=True,
            include_raw_content=False,
            include_images=False,
            search_depth="advanced"
        )

         # 确保 ReactAgent 使用与 Supervisor 兼容的状态 (例如 BasicAgentState)
         # 或者 Supervisor 能够处理不同类型的子 Agent 状态返回
        researcher_system_prompt = """You are a research expert. Use available tools to find the most up-to-date information to answer the user's query. You have access to a 'tavily_search_results_json' tool."""

        research_agent = ReactAgent(
            name="research_expert", 
            tools=[tavily_search],
            description="Research expert with access to Tavily search.",
            model=deepseek_v3,
            prompt=researcher_system_prompt,
         ) 
         
        all_agents = [research_agent] # 只包含一个子 Agent 用于测试

         # --- 实例化 Supervisor (使用 PlanningAgentState) ---
        supervisor = SupervisorAgent(
             agents=all_agents,
             model=deepseek_v3, # Supervisor 使用的 LLM
             state_schema=PlanningAgentState, # 明确 Supervisor 使用 Planning 状态
             # enable_planning=True, # 不再需要此参数，因为 state_schema 暗示了规划
             include_agent_name="inline" # 推荐
             # checkpointer=... # 添加 Checkpointer 以测试持久化
         )
    except Exception as e:
         print(f"Failed to initialize agents or supervisor: {e}")
         import traceback
         traceback.print_exc()
         return

     # --- 获取用户输入 ---
    topic = input("Please enter the initial request for the supervisor: ")
    if not topic:
         print("No request entered. Exiting.")
         return

     # --- 准备初始状态 (使用 PlanningAgentState) ---
    initial_graph_state: PlanningAgentState = {
         "messages": [HumanMessage(content=topic)], # 确保是 HumanMessage 对象
         "plan": None, # 初始没有计划
         "error": None
     }

     # --- 运行测试 ---
    await run_supervisor_test(supervisor, initial_graph_state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
    except Exception as e:
         print(f"\nAn unexpected top-level error occurred: {e}")
         traceback.print_exc()