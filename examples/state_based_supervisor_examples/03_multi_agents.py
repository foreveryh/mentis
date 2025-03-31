# main.py (Multi-Agent Test with State-Based Supervisor)

import asyncio
import json
import os
import re
import time
import traceback # 导入 traceback
from datetime import datetime
from typing import Dict, Any, Optional, List, Literal, cast

# --- LangChain / LangGraph / OpenAI Imports ---
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage



# --- Agent 和工具导入 (确保路径正确) ---
try:
    from core.agents.sb_supervisor_agent import SupervisorAgent # 替换为你的 SupervisorAgent 类路径
    from core.agents.state_based_supervisor.state_schema import PlanningAgentState
    from core.agents.base.react_agent import ReactAgent # 导入 ReactAgent 基类

    # 导入所有重构后的子 Agent 类
    from core.agents.sub_agents.research_agent import ResearchAgent # 假设路径
    from core.agents.sub_agents.coder_agent import CoderAgent       # 假设路径
    from core.agents.sub_agents.reporter_agent import ReporterAgent   # 假设路径
    from core.agents.sub_agents.designer_agent import DesignerAgent   # 假设路径
    from core.agents.sub_agents.data_analyst_agent import DataAnalystAgent # 假设路径

    # 导入工具注册表函数和枚举
    from core.tools.registry import get_tools_by_category, ToolCategory, register_tool # 导入 register_tool
    from core.llm.llm_manager import LLMManager # LLM 管理器
    # 导入特定工具实例或类 (如果 Registry 没有预注册所有工具)
    from langchain_community.tools.tavily_search import TavilySearchResults # 示例
    # from core.tools.e2b_tool import E2BCodeInterpreterTool # 示例
    # from core.tools.replicate_flux_tool import ReplicateFluxImageTool # 示例

    # --- 确保工具已注册 ---
    # 运行 registry 初始化 (通常在 core/tools/__init__.py 中完成)
    try:
        import core.tools # 尝试导入以触发 __init__.py 中的注册
        print("Tool registry potentially initialized.")
    except ImportError:
        print("Warning: Could not import 'core.tools' to initialize registry.")
    except Exception as reg_err:
         print(f"Error during tool registry initialization: {reg_err}")
         
    # (可选) 在这里可以检查或手动注册缺失的核心工具
    # Example: Check and register Tavily if not present
    if not any(getattr(t, 'name', '') == 'tavily_search_results_json' for t in get_tools_by_category(ToolCategory.SEARCH)):
        try:
            print("Attempting to register TavilySearchResults...")
            tavily_tool = TavilySearchResults(max_results=3)
            register_tool(tavily_tool, ToolCategory.SEARCH)
        except Exception as e:
            print(f"Warning: Failed to register TavilySearchResults manually: {e}")
            
    # ... 检查并注册其他必要的工具 ...


except ImportError as e:
    print(f"Error importing agent/tool components: {e}")
    print("Please ensure all agent/tool class paths and registry setup are correct.")
    exit(1)


# --- 助手函数 ---
def slugify(text: str) -> str:
    """Converts text to a safe filename part."""
    # ... (保持不变) ...
    if not text: return "no_topic"
    text = text.lower(); text = re.sub(r'\s+', '_', text)
    text = re.sub(r'[^\w\-]+', '', text); text = text.strip('_')
    return text[:100] if text else "sanitized_topic"

# --- 主研究/测试函数 ---
async def run_supervisor_test(supervisor_agent: SupervisorAgent, initial_state: Dict[str, Any]):
    """Executes the supervisor graph using ainvoke and prints the final state."""

    print("\n--- Starting Supervisor Graph Execution ---")
    initial_query = initial_state.get("messages", [{}])[0].content if initial_state.get("messages") and hasattr(initial_state.get("messages")[0], 'content') else "N/A"
    print(f"Initial Query: '{initial_query}'")
    print("-" * 30)

    config = {"recursion_limit": 100} # 保持较高的递归限制

    final_state: Optional[Dict[str, Any]] = None
    error_occurred: Optional[Exception] = None

    try:
        print("--- Invoking Supervisor Agent (ainvoke) ---")
        # 直接调用 ainvoke 获取最终状态
        final_state = await supervisor_agent.ainvoke(initial_state, config=config)
        print("--- Supervisor Agent Invocation Complete ---")

    # --- 错误处理 ---
    except Exception as e: error_occurred = e; print(f"\n!!! Error during graph execution: {e}"); traceback.print_exc()


    # --- 处理最终状态 ---
    if error_occurred: print("\n--- Graph Execution INTERRUPTED or FAILED ---")
    else: print("\n--- Graph Execution Finished ---")

    if not final_state:
         print("Error: No final state available (Execution might have failed early).")
         # 尝试从 checkpointer 获取最后状态 (如果配置了)
         # ... (checkpoint retrieval logic - optional) ...
         return None

    print("\n--- FINAL STATE ---")
    # 打印错误 (如果在状态中记录了)
    if final_state.get("error"): print(f"\nERROR RECORDED IN STATE: {final_state['error']}")

    # 打印计划
    final_plan = final_state.get('plan')
    if final_plan and isinstance(final_plan, dict):
        print("\nFinal Plan State:")
        print(json.dumps(final_plan, indent=2, default=str))
    else: print("\nFinal Plan State: Not available or not generated.")

    # 打印最终消息历史
    final_messages = final_state.get("messages", [])
    if final_messages and isinstance(final_messages, list):
         print("\nFinal Message History (Last 10):")
         for m in final_messages[-10:]:
              try:
                   if hasattr(m, 'pretty_print'): m.pretty_print()
                   else: print(json.dumps(m, indent=2, default=str)) # Fallback
                   print("-" * 10)
              except Exception as print_err: print(f"Error printing final message: {print_err}")
    else: print("\nFinal Message History: Empty.")

    # --- 保存最终报告 (如果 Reporter Agent 被调用且成功) ---
    # 检查最后一条消息是否来自 Reporter
    final_report_content = None
    if final_messages and isinstance(final_messages[-1], AIMessage) and final_messages[-1].name == "reporter_expert":
         final_report_content = final_messages[-1].content
         print("\n--- Final Report Found from Reporter Agent ---")

    if not error_occurred and final_report_content and isinstance(final_report_content, str) and "Failed" not in final_report_content:
        print("\n--- Saving Final Output to Markdown ---")
        try:
            markdown_content = final_report_content
            # 获取原始请求作为文件名基础
            initial_query_text = final_state.get('messages', [{}])[0].content if final_state.get('messages') and hasattr(final_state.get('messages')[0], 'content') else 'unknown_request'
            topic_slug = slugify(initial_query_text)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"multi_agent_report_{topic_slug}_{timestamp}.md"

            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, "Output")
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f: f.write(markdown_content)
            print(f"Successfully saved output to: {filepath}")
        except Exception as e: print(f"Error saving output to Markdown: {e}")
    elif error_occurred: print("\nFinal Report: Not saved due to execution error.")
    else: print("\nFinal Report: Not generated or not found.")

    print("\n--- END OF TEST ---")
    return final_state


# --- Main Execution Block ---
async def main():
    # --- 1. 初始化 LLM 管理器 ---
    try:
        model_manager = LLMManager()
        print("Registered Models:", json.dumps(model_manager.list_models(), indent=2))
    except Exception as e:
        print(f"Failed to initialize LLMManager: {e}")
        return

    # --- 2. 实例化所有 Agents ---
    try:
        # 获取模型实例
        # 确保 'deepseek_v3' 和 'gpt-4o' 是你 LLMManager 中有效的 ID
        deepseek_model = model_manager.get_model("deepseek_v3")
        gpt4o_model = model_manager.get_model("openai_gpt4o") # 多模态模型

        # 实例化 ResearchAgent
        research_agent = ResearchAgent(
            model=deepseek_model,
        )

        # 实例化 CoderAgent
        coder_agent = CoderAgent(
            model=deepseek_model,
        )

        # 实例化 ReporterAgent
        reporter_agent = ReporterAgent(
            model=deepseek_model
        )

        # 实例化 DesignerAgent
        designer_agent = DesignerAgent(
            model=gpt4o_model,
        )

        # 实例化 DataAnalystAgent
        data_analyst_agent = DataAnalystAgent(
            model=deepseek_model,
        )

        # --- 3. 组合 Agent 列表 ---
        all_agents = [
            research_agent,
            coder_agent,
            reporter_agent,
            designer_agent,
            data_analyst_agent,
        ]

        # --- 4. 实例化 Supervisor ---
        supervisor = SupervisorAgent(
             agents=all_agents,
             model=deepseek_model, # Supervisor 自身使用的模型
             # model = gpt4o_model,
             state_schema=PlanningAgentState,
             include_agent_name="inline"
             # checkpointer=... # 可选: 添加 Checkpointer 实现持久化
        )

    except Exception as e:
         print(f"Failed to initialize agents or supervisor: {e}")
         traceback.print_exc()
         return

    # --- 5. 获取用户输入 ---
    topic = input("Please enter the initial request for the supervisor: ")
    if not topic:
         print("No request entered. Using default topic.")
         topic = """我需要获取法国巴黎当前的实时气温。请按以下步骤操作：
1. 首先，帮我调研一个可以免费获取巴黎当前天气数据的 API (例如 Open-Meteo, WeatherAPI.com 或其他类似的)，重点是找到获取当前气温的 API 端点(endpoint URL)以及如何构造请求（如果可能，选择不需要 API key 的）。
2. 然后，编写一个 Python 脚本，使用 'requests' 库来调用上一步找到的 API 端点，并从中提取出巴黎当前的温度（摄氏度）。
3. 使用你的代码执行工具来运行这个 Python 脚本。
4. 最后，告诉我你找到的当前巴黎温度是多少。"""

    # --- 6. 准备初始状态 ---
    initial_graph_state: PlanningAgentState = {
         "messages": [HumanMessage(content=topic)], 
         "plan": None,
         "error": None
    }

    # --- 7. 运行测试 ---
    await run_supervisor_test(supervisor, initial_graph_state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
    except Exception as e:
         print(f"\nAn unexpected top-level error occurred: {e}")
         traceback.print_exc()