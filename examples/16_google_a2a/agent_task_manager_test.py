# examples/a2a/agent_task_manager_test.py

import os
import sys
import asyncio
import logging
from typing import TypedDict, Any, List, Optional,Tuple

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入A2A相关组件
from core.a2a.types import (
    TaskState, TaskStatus, Task, Artifact, Message,
    SendTaskRequest, SendTaskResponse, SendTaskStreamingRequest,
    TaskSendParams, JSONRPCResponse
)
from core.a2a.agent_task_manager import AgentTaskManager

# 导入LangChain和LLM相关组件
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 定义一个简单的工具
@tool
def search(query: str) -> str:
    """搜索互联网获取信息"""
    return f"这是关于 '{query}' 的搜索结果。"

@tool
def calculator(expression: str) -> str:
    """计算数学表达式"""
    try:
        result = eval(expression)
        return f"计算结果: {result}"
    except Exception as e:
        return f"计算错误: {e}"

# 定义一个简单的LangGraph Agent

class AgentState(TypedDict):
    messages: List[Tuple[str, str]]
    session_id: Optional[str] # 保留 session_id

class TestAgent:
    """测试用Agent"""
    
    # 支持的内容类型
    SUPPORTED_CONTENT_TYPES = ["text"]
    
    def __init__(self, llm=None):
        if llm is None:
            try:
                llm = ChatOpenAI(model="gpt-4o-mini")
            except Exception as e:
                print(f"警告: 无法创建OpenAI LLM ({e})，使用模拟模式")
                from langchain.llms.fake import FakeListLLM
                llm = FakeListLLM(responses=["这是一个模拟的LLM响应"])
                
        self.tools = [search, calculator]
        self.agent = create_react_agent(llm, self.tools)
        self.graph = self._build_graph()
    
    def _build_graph(self):
        """构建Agent的工作流图"""
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self.agent)
        workflow.set_entry_point("agent")
        workflow.add_edge("agent", END)
        return workflow.compile()
    
    def invoke(self, query: str, session_id: str = None) -> str:
        """同步调用Agent"""
        result = self.graph.invoke({"input": query, "session_id": session_id})
        return result["output"]
    
    async def stream(self, query: str, session_id: str = None):
        """流式调用Agent"""
        # 模拟流式输出
        chunks = [
            "正在处理您的请求...",
            "正在搜索相关信息...",
            "找到了一些结果，正在整理...",
            f"关于 '{query}' 的信息如下：这是一个模拟的流式响应。"
        ]
        
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            yield {
                "content": chunk,
                "is_task_complete": is_last,
                "require_user_input": False
            }
            await asyncio.sleep(0.5)  # 模拟延迟

# 测试AgentTaskManager的同步任务处理
async def test_sync_task():
    print("\n=== 测试同步任务处理 ===\n")
    
    # 创建Agent和AgentTaskManager
    agent = TestAgent()
    task_manager = AgentTaskManager(agent)
    
    # 创建任务请求
    task_id = "test_sync_task_1"
    session_id = "test_session_1"
    content = [{"type": "text", "text": "计算 123 + 456 的结果"}]
    
    task_params = TaskSendParams(
        id=task_id,
        sessionId=session_id,
        message=Message(role="user", parts=content),
        acceptedOutputModes=["text"],
        historyLength=10
    )
    
    request = SendTaskRequest(id="req1", params=task_params)
    
    # 发送任务
    response = await task_manager.on_send_task(request)
    
    # 打印结果
    print(f"任务ID: {task_id}")
    print(f"响应类型: {type(response)}")
    
    if hasattr(response, "error") and response.error:
        print(f"错误: {response.error}")
    else:
        print("任务成功完成")
        
        # 获取任务
        task = task_manager.tasks.get(task_id)
        if task:
            print(f"任务状态: {task.status.state}")
            if task.artifacts:
                for artifact in task.artifacts:
                    for part in artifact.parts:
                        if part.get("type") == "text":
                            print(f"任务结果: {part.get('text')}")

# 测试AgentTaskManager的流式任务处理
async def test_streaming_task():
    print("\n=== 测试流式任务处理 ===\n")
    
    # 创建Agent和AgentTaskManager
    agent = TestAgent()
    task_manager = AgentTaskManager(agent)
    
    # 创建任务请求
    task_id = "test_stream_task_1"
    session_id = "test_session_1"
    content = [{"type": "text", "text": "搜索关于人工智能的信息"}]
    
    task_params = TaskSendParams(
        id=task_id,
        sessionId=session_id,
        message=Message(role="user", parts=content),
        acceptedOutputModes=["text"],
        historyLength=10
    )
    
    request = SendTaskStreamingRequest(id="req2", params=task_params)
    
    # 发送流式任务
    response_generator = await task_manager.on_send_task_subscribe(request)
    
    # 检查响应类型
    if isinstance(response_generator, JSONRPCResponse):
        print(f"错误: {response_generator.error}")
        return
    
    # 处理流式响应
    print("开始接收流式响应:")
    async for response in response_generator:
        if hasattr(response, "error") and response.error:
            print(f"流式响应错误: {response.error}")
        else:
            result = response.result
            if hasattr(result, "status") and result.status and result.status.message:
                for part in result.status.message.parts:
                    # --- 修改开始 ---
                    # 直接访问对象的属性 type 和 text
                    if hasattr(part, 'type') and part.type == "text":
                        text_content = getattr(part, 'text', '') # 安全获取 text
                        print(f"流式更新: {text_content}")
                    # --- 修改结束 ---

            if hasattr(result, "artifact") and result.artifact:
                for part in result.artifact.parts:
                    # --- 修改开始 ---
                    # 直接访问对象的属性 type 和 text
                    if hasattr(part, 'type') and part.type == "text":
                         text_content = getattr(part, 'text', '') # 安全获取 text
                         print(f"流式结果: {text_content}")
                    # --- 修改结束 ---

            if hasattr(result, "final") and result.final:
                print("流式响应结束")

# 主函数
async def main():
    print("=== AgentTaskManager 测试 ===\n")
    
    # 测试同步任务
    await test_sync_task()
    
    # 测试流式任务
    await test_streaming_task()

# 运行测试
if __name__ == "__main__":
    asyncio.run(main())