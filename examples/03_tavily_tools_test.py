import os
from langgraph.prebuilt import create_react_agent
from core.agents.react_supervisor_agent import SupervisorAgent
from langchain_openai import ChatOpenAI
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages
from langchain_community.tools import TavilySearchResults
from dotenv import load_dotenv
load_dotenv()  # 自动加载 .env 文件
# 1. 初始化大模型
model = ChatOpenAI(model="gpt-4o-mini")

##############################################################################
# Agent 1: Joke Generator (Functional API)
##############################################################################

@task
def generate_joke(messages):
    """Generate a short joke (no tool calls)."""
    system_message = {
        "role": "system", 
        "content": "You are a witty comedian. Write a short joke."
    }
    # 直接调用 model.invoke，拼接 system_message + 用户消息
    msg = model.invoke([system_message] + messages)
    return msg

@entrypoint()
def joke_agent(state):
    # 调用上面的函数型任务
    joke = generate_joke(state['messages']).result()
    # 将产物插入消息列表
    messages = add_messages(state["messages"], [joke])
    return {"messages": messages}

joke_agent.name = "joke_agent"

##############################################################################
# Agent 2: Research Expert with Tavily Search (Graph API)
##############################################################################

# 创建Tavily搜索工具
tavily_search = TavilySearchResults(
    max_results=3,
    include_answer=True,
    include_raw_content=False,
    include_images=False,
    search_depth="advanced"
)

research_agent = create_react_agent(
    model=model,
    tools=[tavily_search],
    name="research_expert",
    # Prompt 告诉它是一个研究型 Agent，可调用 tavily_search
    prompt=(
        "You are a world-class researcher. You have access to the 'tavily_search_results_json' tool "
        "which can search the web for real-time information. "
        "When asked a question, use this tool to find accurate and up-to-date information. "
        "Summarize the search results in a clear and concise manner. "
        "Always cite your sources by including the URLs from the search results."
    ),
)

##############################################################################
# 使用 SupervisorAgent 类来协调多个智能体
##############################################################################

# 创建 SupervisorAgent 实例
supervisor = SupervisorAgent(
    agents=[research_agent, joke_agent],
    model=model,
    prompt=(
        "You are the overall supervisor. You manage two specialized agents:\n"
        "1) joke_agent: for telling jokes.\n"
        "2) research_expert: for factual or data-related questions using real-time web search.\n\n"
        "If the user wants a joke, call joke_agent.\n"
        "If the user wants factual information or research data, call research_expert.\n"
        "If the user wants a joke AND some research data in the same query, "
        "you MUST call joke_agent first, get the joke, then call research_expert for the data. "
        "After both calls, provide a final combined response. "
        "Do not call more than one agent in a single LLM message; do it step by step."
    ),
)

# 编译得到一个可调用的"App"
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

# print(f"Image saved as {graph_path}")

# 使用示例
if __name__ == "__main__":
    # 示例1：只询问笑话
    result1 = app.invoke({"messages": [{"role": "user", "content": "讲个笑话"}]})
    print("\n示例1 - 只询问笑话:")
    for message in result1["messages"]:
        message.pretty_print()
    
    # 示例2：只询问研究数据
    result2 = app.invoke({"messages": [{"role": "user", "content": "谁是现任美国总统？"}]})
    print("\n示例2 - 只询问研究数据:")
    for message in result2["messages"]:
        message.pretty_print()
    
    # 示例3：同时询问笑话和研究数据
    result3 = app.invoke({"messages": [{"role": "user", "content": "讲个关于人工智能的笑话，然后告诉我什么是大型语言模型"}]})
    print("\n示例3 - 同时询问笑话和研究数据:")
    for message in result3["messages"]:
        message.pretty_print()