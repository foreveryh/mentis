import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_community.agent_toolkits import FileManagementToolkit
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from dotenv import load_dotenv
from langchain_community.tools import TavilySearchResults
from core.agents.react_supervisor_agent import SupervisorAgent

load_dotenv()  # 自动加载 .env 文件

# 初始化大模型
model = ChatOpenAI(model="gpt-4o-mini")

##############################################################################
# 创建一个记录Agent思考过程的函数
##############################################################################

def log_agent_actions(state: Dict[str, Any]) -> None:
    """记录Agent的思考过程和行动"""
    print("\n" + "=" * 50)
    print("当前状态:")
    
    # 打印最新消息
    if state.get("messages") and len(state["messages"]) > 0:
        latest_message = state["messages"][-1]
        
        if isinstance(latest_message, AIMessage):
            print(f"\nAI思考过程:")
            # 限制内容长度，避免过长输出
            content = latest_message.content
            if len(content) > 500:
                content = content[:250] + "\n... (内容过长，已截断) ...\n" + content[-250:]
            print(content)
            
            # 如果有工具调用，打印工具调用信息
            if latest_message.tool_calls:
                print(f"\n工具调用:")
                for tool_call in latest_message.tool_calls:
                    print(f"- 工具: {tool_call['name']}")
                    # 限制参数输出长度
                    args = str(tool_call['args'])
                    if len(args) > 100:
                        args = args[:100] + "... (参数过长，已截断)"
                    print(f"- 参数: {args}")
        
        elif isinstance(latest_message, ToolMessage):
            print(f"\n工具返回结果:")
            print(f"- 工具: {latest_message.name}")
            # 只打印结果的前200个字符，避免输出过长
            content = latest_message.content
            if len(content) > 200:
                content = content[:100] + "\n... (更多内容省略) ...\n" + content[-100:]
            print(f"- 结果: {content}")
    
    print("=" * 50)

##############################################################################
# 创建Web提取工具
##############################################################################
# 创建Tavily搜索工具

tavily_search = TavilySearchResults(
    max_results=3,
    include_answer=True,
    include_raw_content=False,
    include_images=False,
    search_depth="advanced"
)

##############################################################################
# 创建文件系统工具 - 用于保存提取的内容
##############################################################################

# 设置文件系统工具的根目录为examples/output
output_dir = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(output_dir, exist_ok=True)

# 创建文件系统工具集
filesystem_toolkit = FileManagementToolkit(
    root_dir=output_dir,
    selected_tools=["write_file", "read_file", "list_directory"]
)

# 获取文件系统工具
filesystem_tools = filesystem_toolkit.get_tools()

##############################################################################
# 创建Research Agent - 用于网站内容提取
##############################################################################

research_agent = create_react_agent(
    model=model,
    tools=[tavily_search],
    name="research_agent",
    # 提示词强调分解问题、多步思考和综合信息
    prompt=(
        "You are a world-class researcher. You have access to the 'tavily_search_results_json' tool "
        "which can search the web for real-time information. "
        "When asked a question, use this tool to find accurate and up-to-date information. "
        "Summarize the search results in a clear and concise manner. "
        "Always cite your sources by including the URLs from the search results."
    ),
    debug=False)

##############################################################################
# 创建FileSystem Agent - 用于保存提取的内容
##############################################################################

filesystem_agent = create_react_agent(
    model=model,
    tools=filesystem_tools,
    name="filesystem_agent",
    # 提示词强调文件操作和内容保存
    prompt=(
        "你是一位专业的文件系统管理专家，负责将网页内容保存到本地文件系统。\n"
        "你有以下工具可以使用:\n"
        "1. 'write_file': 用于将内容写入文件\n"
        "2. 'read_file': 用于读取文件内容\n"
        "3. 'list_directory': 用于列出目录内容\n\n"
        "当接收到保存内容的请求时，请遵循以下方法论:\n"
        "1. 分析内容: 确定内容的类型和结构\n"
        "2. 确定文件名: 根据内容类型和来源创建合适的文件名\n"
        "3. 保存内容: 使用write_file工具将内容保存到文件中\n"
        "4. 验证保存: 使用read_file或list_directory工具验证内容已正确保存\n\n"
        "重要提示:\n"
        "- 为文件创建有意义的名称，包含日期和内容描述\n"
        "- 对于结构化数据，优先使用JSON格式保存\n"
        "- 对于文本内容，使用TXT或MD格式保存\n"
        "- 确保文件名不包含非法字符\n"
        "- 在保存前，检查是否已存在同名文件，避免覆盖重要内容\n"
    ),
)

##############################################################################
# 创建Supervisor Agent - 协调Research Agent和FileSystem Agent
##############################################################################
# 创建内存存储器用于保存对话状态
memory_saver = MemorySaver()
supervisor = SupervisorAgent(
    agents=[research_agent, filesystem_agent],
    model=model,
    prompt=(
        "你是一个智能助手的总协调者，负责管理两个专业智能体:\n"
        "1) research_agent: 网页内容分析专家，可以爬取和分析网站内容\n"
        "2) filesystem_agent: 文件系统管理专家，可以将内容保存到本地文件系统\n\n"
        "你的工作流程如下:\n"
        "1. 分析用户请求，确定是需要网页内容提取还是文件操作，或两者都需要\n"
        "2. 如果需要网页内容提取，调用research_agent获取网页内容\n"
        "3. 如果需要将提取的内容保存到文件，调用filesystem_agent进行保存\n"
        "4. 如果用户同时需要提取内容并保存，先调用research_agent获取内容，再调用filesystem_agent保存内容\n\n"
        "重要规则:\n"
        "- 不要在一个消息中同时调用多个智能体，必须一步一步来\n"
        "- 当调用filesystem_agent保存内容时，必须提供完整的内容和建议的文件名\n"
        "- 确保在最终回复中告知用户内容已成功提取和/或保存\n"
        "- 如果用户只想提取内容而不保存，只调用research_agent\n"
        "- 如果用户只想操作文件而不提取新内容，只调用filesystem_agent\n\n"
        "上下文管理指南:\n"
        "- 当处理大型网站或多个页面时，指导research_agent采用分批处理策略\n"
        "- 对于大型内容提取任务，先让research_agent获取网站结构，再逐步处理各个页面\n"
        "- 当发现research_agent返回的内容过大时，指导它进行内容摘要或分批处理\n"
        "- 如果research_agent一次性尝试处理过多页面导致上下文超限，指导它减少并行处理的页面数量\n"
        "- 对于需要保存的大型内容，考虑将其分割成多个小文件，而不是一个大文件\n"
        "- 在处理多页面内容时，可以采用先保存再处理的策略，减轻上下文负担\n"
    ),
    checkpointer=memory_saver
)



# 编译得到一个可调用的"App"，添加checkpointer实现记忆功能
app = supervisor.compile()

# # 获取当前文件名（不含路径和扩展名）
# current_file = os.path.basename(__file__)
# file_name_without_ext = os.path.splitext(current_file)[0]
# graph_dir = os.path.join(os.path.dirname(__file__), "graphs")

# # 确保 graphs 目录存在
# os.makedirs(graph_dir, exist_ok=True)

# # 生成与文件名一致的图片名，并保存到 examples/graphs 目录
# image_data = app.get_graph().draw_mermaid_png()
# graph_path = os.path.join(graph_dir, f"{file_name_without_ext}.png")

# # 保存图片（如果已存在则覆盖）
# with open(graph_path, "wb") as f:
#     f.write(image_data)

# print(f"图表已保存为 {graph_path}")

##############################################################################
# 主函数 - 处理用户输入
##############################################################################

async def main():
    # 创建一个固定的thread_id用于保持对话上下文
    thread_id = "user_session_1"
    
    # 创建配置对象，包含thread_id
    config = {"configurable": {"thread_id": thread_id}}
    
    print("\n当前会话ID:", thread_id)
    print("(所有对话将在同一会话中保持上下文记忆)")
    
    while True:
        # 获取用户输入
        user_input = await asyncio.to_thread(input, "\n请输入您想了解的问题 (输入'退出'结束): ")
        
        # 检查是否退出
        if user_input.lower() in ['退出', 'exit', 'quit']:
            print("\n感谢使用，再见！")
            break
        
        # 准备初始状态 - 只包含当前用户消息
        initial_state = {
            "messages": [HumanMessage(content=user_input)]
        }
        
        try:
            print("\n=== 🔍 开始研究 ===\n")
            
            # 使用stream方法逐步获取中间状态，传入config以使用相同的thread_id
            for partial_state in app.stream(initial_state, config, stream_mode="values"):
                # 保存最终状态
                final_state = partial_state
                
                # 获取消息列表
                messages = partial_state.get("messages", [])
                if not messages:
                    continue
                    
                # 获取最新消息
                latest_message = messages[-1]
                
                # 使用log_agent_actions函数记录状态
                log_agent_actions({"messages": [latest_message]})
        
        except Exception as e:
            print(f"\n处理查询时出错: {e}")
            print("可能是由于上下文长度超出限制，请尝试减少查询范围或使用'批处理大小设置为X'命令调整批处理大小(1-5之间)")

##############################################################################
# 程序入口
##############################################################################

if __name__ == "__main__":
    print("\n欢迎使用具有记忆功能的网页爬取助手！")
    print("本助手可以记住您之前的对话内容，实现连续对话体验。")
    print("您可以询问之前提到过的内容，助手会根据上下文理解您的问题。")
    
    # 运行主函数
    asyncio.run(main())