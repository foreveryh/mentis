# examples/a2a/langgraph_integration.py

import os
import sys
import asyncio # asyncio 仍然可能被依赖库使用，保留导入
import logging
# 确保导入了 List, Tuple, Optional, TypedDict
from typing import Dict, Any, List, Optional, AsyncIterable, Union, TypedDict, Tuple

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入A2A相关组件
# 从你的项目结构导入
from core.a2a.types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Task, TaskState, TaskStatus, Artifact, Message, TextPart, # TextPart 可能不再直接使用
    JSONRPCResponse, InvalidParamsError, InternalError,
    SendTaskRequest, SendTaskResponse, TaskSendParams
)
from core.a2a.server.server import A2AServer
from core.a2a.agent_task_manager import AgentTaskManager

# 导入LangChain和LLM相关组件
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
# StateGraph 和 END 不再直接使用，但保留导入
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

# 配置日志
logging.basicConfig(level=logging.INFO) # 可以改为 DEBUG 获取更详细日志
logger = logging.getLogger(__name__)

# --- 定义工具 (保持不变) ---
@tool
def search(query: str) -> str:
    """搜索互联网获取信息"""
    # 实际应用中应调用真实搜索引擎 API
    logger.info(f"Tool 'search' called with query: {query}")
    return f"这是关于 '{query}' 的模拟搜索结果。"

@tool
def calculator(expression: str) -> str:
    """计算数学表达式"""
    logger.info(f"Tool 'calculator' called with expression: {expression}")
    try:
        # 注意：生产环境中使用 eval 非常危险，这里仅作示例
        # 限制 eval 的能力，只允许简单的数学运算
        allowed_names = {
            k: v for k, v in __import__("math").__dict__.items() if not k.startswith("_")
        }
        allowed_names.update({"abs": abs, "int": int, "float": float}) # 添加常用函数
        code = compile(expression, "<string>", "eval")

        for name in code.co_names:
             if name not in allowed_names:
                  raise NameError(f"Use of name '{name}' not allowed")

        result = eval(code, {"__builtins__": {}}, allowed_names)
        return f"计算结果: {result}"
    except NameError as e:
         logger.error(f"Calculation error (NameError): {e} in expression '{expression}'")
         return f"计算错误: 不允许的名称 '{e.name}'"
    except Exception as e:
        logger.error(f"Calculation error: {e} in expression '{expression}'")
        return f"计算错误: {e}"

# --- 修正 AgentState 定义 ---
class AgentState(TypedDict):
    # 使用 'messages' 字段来传递对话内容
    # 格式为 (角色, 内容) 的元组列表
    messages: List[Tuple[str, str]]
    # session_id 可以保留，如果Agent内部逻辑需要的话 (create_react_agent 通常不需要)
    # session_id: Optional[str]
    # 注意: ReAct Agent 运行时可能会在状态中添加其他键 (例如 intermediate_steps)

# --- 修正 CurrencyAgent 类 ---
class CurrencyAgent:
    """一个简单的货币转换和信息查询Agent (已修正)"""

    # 支持的内容类型 (保持不变)
    SUPPORTED_CONTENT_TYPES = ["text"]

    def __init__(self, llm):
        """初始化Agent，直接使用 create_react_agent 创建的 Runnable"""
        self.tools = [search, calculator]
        # create_react_agent 返回一个可直接调用的 Runnable (图)
        self.agent_runnable = create_react_agent(llm, self.tools)
        logger.info("CurrencyAgent initialized with ReAct runnable.")

    def invoke(self, query: str, session_id: str = None) -> str:
        """同步调用Agent Runnable"""
        # (session_id 在此实现中未传递给 agent_runnable，如果需要可以添加)
        logger.debug(f"[CurrencyAgent.invoke] Received query: '{query}', session_id: '{session_id}'")
        if not query:
             logger.error("[CurrencyAgent.invoke] Query is empty!")
             return "错误：输入查询为空。"

        # 准备 ReAct Agent Runnable 所需的输入
        invoke_input = {"messages": [("user", query)]}

        logger.debug(f"[CurrencyAgent.invoke] Invoking agent runnable with input: {invoke_input}")
        try:
            # 直接调用 create_react_agent 返回的 runnable
            result = self.agent_runnable.invoke(invoke_input)
            logger.debug(f"[CurrencyAgent.invoke] Agent runnable result: {result}")

            # 提取最终响应
            final_output = "错误：未能从Agent获取有效响应。"
            if isinstance(result, dict) and isinstance(result.get("messages"), list) and result["messages"]:
                last_message = result["messages"][-1]
                if isinstance(last_message, tuple) and len(last_message) == 2:
                    final_output = last_message[1]
                elif hasattr(last_message, 'content'):
                     final_output = last_message.content
                else:
                     logger.warning(f"[CurrencyAgent.invoke] Last message format unexpected: {last_message!r}")
            else:
                 logger.warning(f"[CurrencyAgent.invoke] Could not find 'messages' list in result: {result}")

            logger.debug(f"[CurrencyAgent.invoke] Returning output: {final_output}")
            return str(final_output)
        except Exception as e:
             logger.error(f"[CurrencyAgent.invoke] Exception during agent invocation: {e}", exc_info=True)
             raise

    async def ainvoke(self, inputs: dict) -> dict:
        """异步调用Agent Runnable (输入格式也需调整)"""
        # TODO: 确认这里的输入格式是否也需要转换为 {"messages": [...]}
        logger.debug(f"[CurrencyAgent.ainvoke] Invoking agent runnable async with input: {inputs}")
        # 假设输入字典已经包含了正确的 "messages" 键
        return await self.agent_runnable.ainvoke(inputs)

    async def stream(self, query: str, session_id: str = None):
        """流式调用Agent (当前为模拟)"""
        # TODO: 实现真实的流式调用
        logger.warning("[CurrencyAgent.stream] Stream method is currently mocked.")
        # --- 模拟实现 ---
        yield { "content": "正在处理您的请求...", "is_task_complete": False, "require_user_input": False }
        await asyncio.sleep(0.5)
        final_simulated_answer = f"关于 '{query}' 的信息如下：这是一个模拟的回应，因为真实流未实现。"
        yield { "content": final_simulated_answer, "is_task_complete": True, "require_user_input": False }
        # --- 模拟结束 ---


# --- A2A 服务器设置 (修正函数定义和 AgentCard) ---
# 将函数改为同步定义 (def 而不是 async def)
def setup_a2a_server():
    """设置并返回 A2A 服务器实例 (同步函数)"""
    print("\n=== 配置 LangGraph A2A 服务器 ===\n")

    # 创建LLM
    try:
        llm = ChatOpenAI(model="gpt-4o-mini")
        logger.info("Using OpenAI LLM: gpt-4o-mini")
    except Exception as e:
        print(f"警告: 无法创建OpenAI LLM ({e})，将使用模拟模式")
        from langchain.llms.fake import FakeListLLM
        llm = FakeListLLM(responses=["这是一个模拟的LLM响应"])
        logger.info("Using FakeListLLM (simulation mode)")

    # 创建 Agent 实例
    agent = CurrencyAgent(llm)

    # 创建 Agent 卡片 (添加缺失字段)
    agent_card = AgentCard(
        name="LangGraph ReAct Agent",
        description="一个使用LangGraph ReAct处理查询并调用工具的Agent",
        url="http://127.0.0.1:8000/agent", # Agent 的访问 URL (示例)
        version="0.1.0",                  # Agent 的版本号
        capabilities=AgentCapabilities(   # 设置 Agent 的能力
            streaming=False,              # 当前 stream 是模拟的，设为 False
            pushNotifications=False       # 假设不支持推送
        ),
        skills=[                          # skills 列表在 AgentCard 顶层
            AgentSkill(
                id="react_query_skill",   # 技能的唯一 ID
                name="react_query",
                description="处理自然语言查询，可使用搜索和计算器工具",
                inputModes=["text"],
                outputModes=["text"]
            )
        ]
        # 其他可选字段可以按需添加
    )

    # 创建 AgentTaskManager
    task_manager = AgentTaskManager(agent)

    # 创建A2A服务器实例 (不在此处设置 host/port)
    server = A2AServer(agent_card=agent_card, task_manager=task_manager)
    print("A2A服务器实例已创建。")
    return server # 返回实例


# --- 主函数入口 (修正启动逻辑) ---
if __name__ == "__main__":
    try:
        # 调用同步函数来设置服务器
        server_instance = setup_a2a_server()

        # 定义 HOST 和 PORT
        HOST = "127.0.0.1"
        PORT = 8000
        print(f"准备启动A2A服务器，监听地址 http://{HOST}:{PORT}")

        # 在调用 start 前设置 host 和 port
        # (或者修改 A2AServer 的 __init__ 让其接受 host/port)
        server_instance.host = HOST
        server_instance.port = PORT

        # 启动服务器 (调用同步的 start 方法)
        server_instance.start()

    except KeyboardInterrupt:
        print("\n服务器已手动停止。")
    except Exception as e:
        # 捕获设置或启动过程中的其他异常
        logger.error(f"启动服务器时发生未处理的异常: {e}", exc_info=True)