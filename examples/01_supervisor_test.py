from langgraph.prebuilt import create_react_agent
from core.agents.supervisor import create_supervisor
from langchain_openai import ChatOpenAI
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages
from dotenv import load_dotenv
from core.utils.agent_utils import visualize_agent

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
# Agent 2: Research Expert (Graph API)
##############################################################################

def web_search(query: str) -> str:
    """Search the web for information. (Mocked data here)"""
    return (
        "Here are the headcounts for each of the FAANG companies in 2024:\n"
        "1. **Facebook (Meta)**: 67,317 employees.\n"
        "2. **Apple**: 164,000 employees.\n"
        "3. **Amazon**: 1,551,000 employees.\n"
        "4. **Netflix**: 14,000 employees.\n"
        "5. **Google (Alphabet)**: 181,269 employees."
    )

research_agent = create_react_agent(
    model=model,
    tools=[web_search],
    name="research_expert",
    # Prompt 告诉它是一个研究型 Agent，可调用 web_search
    prompt=(
        "You are a world-class researcher. You have access to a 'web_search(query: str)' tool. "
        "Do not do any complicated math, just provide factual info from the web_search if needed."
    ),
)

##############################################################################
# Supervisor Workflow
##############################################################################

# 让 Supervisor 在一次对话中可以多轮调用 joke_agent 和 research_expert
# 这里的 prompt 告诉它：如果用户要“先讲笑话再查信息”，请先调用 joke_agent，再调用 research_expert，
# 这样可以在同一个用户请求下顺序执行两个 Agent。
# 这是最简单的示例，只是为了演示 create_supervisor 的基本用法，该方法没有被封装成一个 Agent
# 也不具备 Planning 能力
workflow = create_supervisor(
    [research_agent, joke_agent],
    model=model,
    prompt=(
        "You are the overall supervisor. You manage two specialized agents:\n"
        "1) joke_agent: for telling jokes.\n"
        "2) research_expert: for factual or data-related questions.\n\n"
        "If the user wants a joke AND some research data in the same query, "
        "you MUST call joke_agent first, get the joke, then call research_expert for the data. "
        "After both calls, provide a final combined response. "
        "Do not call more than one agent in a single LLM message; do it step by step."
    ),
)

# 编译得到一个可调用的"App"
agent = workflow.compile()
# 保存为一个可视化的图
# visualize_agent(agent)
##############################################################################
# 测试：单个用户请求想要 "先讲笑话，再查Apple的2024年人数" 并合并结果
##############################################################################
result = agent.invoke({
    "messages": [
        {
            "role": "user",
            "content": (
                "Hi! I'd like to start with a short joke to lighten the mood, "
                "then please check Apple's headcount in 2024. Summarize both."
            )
        }
    ]
})

##############################################################################
# 打印最终对话消息
##############################################################################
for m in result["messages"]:
    m.pretty_print()