from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_community.tools import TavilySearchResults
from langgraph.checkpoint.memory import MemorySaver
from core.tools.e2b_tool import E2BCodeInterpreterTool
from core.tools.registry import register_tool, ToolCategory
from core.llm.llm_manager import LLMManager

load_dotenv()  # 自动加载 .env 文件
# 初始化大模型
model = LLMManager().get_model("deepseek_v3")

# 创建Tavily搜索工具
tavily_search = TavilySearchResults(
    max_results=3,
    include_answer=True,
    include_raw_content=False,
    include_images=False,
    search_depth="advanced"
)

# 创建E2B代码解释器工具
e2b_code_interpreter = E2BCodeInterpreterTool()


research_agent = create_react_agent(
    model=model,
    tools=[tavily_search, e2b_code_interpreter],
    name="research_expert",
    # Prompt 告诉它是一个研究型 Agent，可调用 tavily_search 和 e2b_code_interpreter
    prompt=(
        "你是一位世界级的研究专家和数据分析师，擅长信息检索和数据分析。你有两个强大的工具可以使用：\n"
        "1. 'tavily_search_results_json'：用于搜索网络获取实时信息\n"
        "2. 'e2b_code_interpreter'：用于执行Python代码，支持数据分析和可视化\n\n"
        "当面对问题时，请遵循以下方法论：\n"
        "1. 分析问题：理解用户的需求和问题本质\n"
        "2. 制定计划：确定需要搜索哪些信息，以及是否需要进行数据分析\n"
        "3. 执行搜索：使用tavily_search_results_json工具获取最新信息\n"
        "4. 数据分析：如果需要，使用e2b_code_interpreter工具编写和执行Python代码进行数据分析和可视化\n"
        "5. 综合信息：将搜索结果和数据分析结果综合成一个连贯的回答\n\n"
        "重要提示：\n"
        "- 对于信息检索任务，使用tavily_search_results_json工具，并在回答中引用来源URL\n"
        "- 对于数据分析和可视化任务，使用e2b_code_interpreter工具执行Python代码\n"
        "- 在使用代码解释器时，确保导入必要的库（如pandas, matplotlib, numpy等）\n"
        "- 在代码中添加详细注释，解释关键步骤\n"
        "- 执行代码后，解释结果含义和见解"
    ),
    checkpointer=MemorySaver(),
)


def get_graph():
    return research_agent