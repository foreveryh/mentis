from langgraph.prebuilt import create_react_agent
from core.agents.react_supervisor_agent import SupervisorAgent
from core.agents.research_agent import ResearchAgent
from core.agents.base.react_agent import ReactAgent
from langchain_openai import ChatOpenAI
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages
from dotenv import load_dotenv
from langchain_community.tools import TavilySearchResults
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

# 使用我们自定义的ResearchAgent替代create_react_agent创建的agent
research_agent = ResearchAgent(
    name="research_expert",
    model=model,
    max_iterations=5,
    cache_enabled=True,
    debug=False
)
research_agent_2 = ReactAgent(
    name="research_expert",
    model=model,
    tools=[tavily_search])

##############################################################################
# 使用带有Planning功能的SupervisorAgent
##############################################################################

# 创建 SupervisorAgent 实例，启用Planning功能
supervisor = SupervisorAgent(
    agents=[joke_agent,research_agent_2],
    model=model,
)
##############################################################################
# 测试：复杂请求需要规划和多个步骤
##############################################################################
result = supervisor.run({
    "messages": [
        {
            "role": "user",
            "content": (
                "I'm preparing a presentation about tech companies. I need three things: "
                "1) A joke about tech companies to start with, "
                "2) The employee count for FANNG, and "
                "3) A comparison of which company has more employees."
            )
        }
    ]
})

##############################################################################
# 打印最终对话消息
##############################################################################
for m in result["messages"]:
    m.pretty_print()

# 打印任务列表
print("\n##############################################################################")
print("# 最终任务列表")
print("##############################################################################")
if "plan" in result and result["plan"] and "tasks" in result["plan"]:
    tasks = result["plan"]["tasks"]
    print(f"总共 {len(tasks)} 个任务:")
    for i, task in enumerate(tasks):
        print(f"\n任务 {i+1}: {task['description']}")
        print(f"  状态: {task['status']}")
        print(f"  代理: {task['agent'] if task['agent'] else '未分配'}")
        print(f"  创建时间: {task['created_at']}")
        print(f"  完成时间: {task['completed_at'] if task['completed_at'] else '未完成'}")
else:
    print("没有任务列表信息")

# 打印原始任务列表（如果存在）
if "tasks" in result:
    print("\n原始任务列表:")
    for t in result["tasks"]:
        t.pretty_print()