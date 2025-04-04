# main.py
import sys
from pathlib import Path
import asyncio
import json
import os # <--- 导入 os 模块
import re
import time # <--- 确保导入 time (虽然 finalize_basic_research 中没用到，但 add_stream_update 可能需要)
from datetime import datetime
from typing import Literal, List, Dict, Any, Set # <--- 确保导入 List

# --- OpenAI 错误处理 ---
try:
    from openai import RateLimitError
except ImportError:
    # 如果用户没有安装 openai 包，定义一个基础异常类以便 except 块能工作
    class RateLimitError(Exception):
        pass

# 1. 获取当前脚本文件的绝对路径对象
#    Path(__file__) 获取当前脚本路径
#    .resolve() 将其转换为绝对路径，并解析任何符号链接
current_script_path = Path(__file__).resolve()
project_root = current_script_path.parent
while not (project_root / '.git').exists() and project_root.parent != project_root:
    project_root = project_root.parent
if not (project_root / '.git').exists():
       # 如果找不到 .git，可能需要用其他标记或给出错误
    raise FileNotFoundError("Could not determine project root based on .git directory.")
#    构建需要添加的路径 (例如 'src' 目录)
#    根据你的实际情况，可能是项目根目录，或者根目录下的 'src', 'lib' 等
path_to_add = project_root / 'super_agent' / 'deep_research'
# 3. 将计算出的路径添加到 sys.path (如果它还不在里面的话)
#    使用 str() 将 Path 对象转换为字符串，因为 sys.path 需要字符串
if str(path_to_add) not in sys.path:
    # insert(0, ...) 表示优先搜索这个路径
    sys.path.insert(0, str(path_to_add))

# (可选) 打印出来确认一下
print(f"Dynamically added to sys.path: {path_to_add}")
# print(sys.path)

# --- LangGraph 和内部模块导入 ---
try:
    from reason_graph.graph import app
    from reason_graph.state import ResearchState
    # 导入需要用到的 Pydantic 模型
    from reason_graph.schemas import StreamUpdate, FinalSynthesisResult, KeyFinding
except ImportError as e:
    print(f"Error importing graph components: {e}")
    print("Please ensure 'reason_graph' package and its modules (graph, state, schemas) exist.")
    exit(1)

# --- 助手函数 ---

def slugify(text: str) -> str:
    """将文本转换为安全的文件名部分 (简化版)."""
    if not text:
        return "no_topic"
    text = text.lower()
    text = re.sub(r'\s+', '_', text) # 空格替换为下划线
    text = re.sub(r'[^\w\-]+', '', text) # 移除所有非字母、数字、下划线、连字符
    text = text.strip('_')
    # 限制文件名长度，避免过长
    return text[:100] if text else "sanitized_topic"

# --- 主研究函数 ---

async def run_research(topic: str, depth: Literal['basic', 'advanced'] = 'basic'):
    """执行研究图并处理输出和错误。"""
    initial_state: ResearchState = {
        "topic": topic,
        "depth": depth,
        "research_plan": None,
        "search_steps_planned": [],
        "analysis_steps_planned": [],
        "current_search_step_index": 0,
        "current_analysis_step_index": 0,
        "current_gap_search_index": 0,
        "search_results": [],
        "gap_analysis": None,
        "additional_queries_planned": [],
        "final_synthesis": None,
        "final_report_markdown": None, # 确保初始状态包含
        "stream_updates": [],
        "completed_steps_count": 0,
        "total_steps": 0,
    }

    print("--- Starting Research Graph ---")
    print(f"Topic: '{topic}'")
    print(f"Depth: '{depth}'")
    print("-" * 30)

    processed_updates_count = 0
    config = {"recursion_limit": 100} # 保持递归限制

    final_state = initial_state.copy() # 初始化 final_state
    error_occurred: Exception | None = None # 用于标记是否有错误发生

    # --- Streaming Execution with Error Handling ---
    try:
        async for current_state in app.astream(
            initial_state,
            config=config,
            stream_mode="values" # 使用 values 模式获取完整状态
        ):
            final_state = current_state # 持续更新 final_state 为最新状态

            # 检查并打印新的 stream_updates
            all_current_updates: List[StreamUpdate] = current_state.get("stream_updates", [])
            new_updates_count = len(all_current_updates) - processed_updates_count

            if new_updates_count > 0:
                newly_added_updates = all_current_updates[processed_updates_count:]
                for update in newly_added_updates:
                    try:
                        # 尝试打印详细信息
                        print(f"--- STREAM UPDATE (ID: {update.data.id} | Status: {update.data.status}) ---")
                        # 使用 model_dump() (Pydantic V2) 而不是 dict()
                        print(json.dumps(update.model_dump(), indent=2, default=str))
                        print("-" * 30)
                    except AttributeError as e:
                        # 处理可能的意外情况，比如列表中混入了非 StreamUpdate 对象
                        print(f"--- Error processing stream update (AttributeError): {e} ---")
                        print(f"Problematic update data: {update}")
                        print("-" * 30)
                    except Exception as e: # 捕获其他可能的打印错误
                        print(f"--- Error printing stream update: {e} ---")
                        print(f"Problematic update data: {update}")
                        print("-" * 30)


                # 更新已处理计数
                processed_updates_count = len(all_current_updates)

            # --- Optional Current State Summary ---
            # 可以取消注释以查看每步状态摘要
            # print(f"--- Current State Summary ---")
            # print(f"  Search steps completed: {current_state.get('current_search_step_index', 0)}")
            # print(f"  Analysis steps completed: {current_state.get('current_analysis_step_index', 0)}")
            # print(f"  Total results so far: {len(current_state.get('search_results', []))}")
            # print("-" * 30)


    except RateLimitError as e: # 捕获特定的 OpenAI Quota 错误
        error_occurred = e # 标记错误
        print("\n" + "="*40)
        print("!!! OpenAI API Error: Insufficient Quota !!!")
        print("="*40)
        print("The research process was stopped because your OpenAI account has exceeded its quota.")
        print("Please check your OpenAI plan and billing details.")
        print(f"Original error message: {e}")
        print("Attempting to show partial results obtained before the error...")
    except Exception as e: # 捕获其他可能的意外错误
         error_occurred = e
         print("\n" + "="*40)
         print("!!! An Unexpected Error Occurred During Graph Execution !!!")
         print("="*40)
         print(f"Error type: {type(e).__name__}")
         print(f"Error details: {e}")
         # 打印详细的 traceback 以便调试
         import traceback
         traceback.print_exc()
         print("Attempting to show partial results obtained before the error...")


    # --- Process Final State ---
    if error_occurred:
         print("\n--- Graph Execution INTERRUPTED ---")
    else:
         print("\n--- Graph Execution Finished ---")

    # 检查 final_state 是否有效
    if not final_state or not isinstance(final_state, dict):
         print("Error: Invalid or unavailable final state after execution.")
         return None

    # --- Print Final State Summary (始终尝试打印) ---
    print("\n--- FINAL (Possibly Partial) RESEARCH STATE (Summary) ---") # 调整标题
    print(f"Topic: {final_state.get('topic', 'N/A')}")
    print(f"Depth: {final_state.get('depth', 'N/A')}")
    research_plan = final_state.get('research_plan')
    if research_plan and hasattr(research_plan, 'search_queries') and hasattr(research_plan, 'required_analyses'):
        print("\nResearch Plan:")
        print(f"- {len(research_plan.search_queries)} Search Queries Planned")
        print(f"- {len(research_plan.required_analyses)} Analyses Planned")
    search_results = final_state.get('search_results', [])
    print(f"\nTotal Search Results Collected: {len(search_results)}")
    gap_analysis = final_state.get('gap_analysis')
    if gap_analysis and hasattr(gap_analysis, 'limitations') and hasattr(gap_analysis, 'knowledge_gaps'):
        print("\nGap Analysis:")
        print(f"- {len(gap_analysis.limitations)} Limitations Identified")
        print(f"- {len(gap_analysis.knowledge_gaps)} Knowledge Gaps Identified")


    # --- Save Final Synthesis Report (只有在没有错误且报告存在时才保存) ---
    final_markdown = final_state.get('final_report_markdown')

    if not error_occurred and final_markdown and isinstance(final_markdown, str) and "Report Generation Failed" not in final_markdown:
        # 打印 Synthesis 摘要 (如果存在)
        final_synthesis_data = final_state.get('final_synthesis')
        if final_synthesis_data and hasattr(final_synthesis_data, 'key_findings') and hasattr(final_synthesis_data, 'remaining_uncertainties'):
             print("\nFinal Synthesis Summary:")
             print(f"- {len(final_synthesis_data.key_findings)} Key Findings")
             print(f"- {len(final_synthesis_data.remaining_uncertainties)} Remaining Uncertainties")

        print("\n--- Saving Final Report to Markdown ---")
        try:
            markdown_content = final_markdown
            # 使用 .get 提供默认值以防 topic 丢失
            topic_slug = slugify(final_state.get('topic', 'unknown_topic'))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"research_report_{topic_slug}_{timestamp}.md"

            # --- 保存路径逻辑 ---
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, "Output")
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)
            # --- 路径逻辑结束 ---

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            print(f"Successfully saved report to: {filepath}")

        except Exception as e:
            print(f"Error saving report to Markdown: {e}")

    elif final_markdown and isinstance(final_markdown, str) and "Report Generation Failed" in final_markdown:
         # 如果报告生成节点本身出错并返回了错误信息
         print("\n--- Final Report Generation Failed ---")
         # 只打印错误部分，避免打印整个 Markdown 错误模板
         print(final_markdown.split('\n\n', 1)[-1]) # 尝试只打印 Error: ...
         print("Report not saved.")
    elif error_occurred:
         # 如果是因为 RateLimitError 等原因中断
         print("\nFinal Report: Not generated due to execution error.")
    else:
         # 正常结束但没有报告（例如 basic depth 或 synthesis 缺失）
         print("\nFinal Report: Not generated (Flow did not reach, complete report generation step, or synthesis was missing).")


    print("\n--- END OF RESEARCH ---")
    return final_state

# --- Main Execution Block ---
async def main():
     # --- 用户输入 topic ---
     topic = input("Please enter the research topic: ")
     if not topic:
         print("No topic entered. Exiting.")
         return
     # --- (可选) 用户输入 depth ---
     depth_input = input("Enter search depth (basic/advanced) [Default: advanced]: ").strip().lower()
     depth: Literal['basic', 'advanced'] = 'basic' if depth_input == 'basic' else 'advanced'
     # ---

     await run_research(topic, depth=depth)

if __name__ == "__main__":
    # 运行 asyncio 事件循环
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nResearch interrupted by user.")