# examples/a2a/currency_agent_test.py

import os
import sys
import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from uuid import uuid4 # Import uuid

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入A2A客户端和所需类型
from core.a2a.client.client import A2AClient
# 导入 Message, TextPart, TaskState, SendTaskResponse, GetTaskResponse, Task, JSONRPCError
from core.a2a.types import (
    Part, TextPart, Message, TaskState,
    SendTaskResponse, GetTaskResponse, Task, JSONRPCError,
    SendTaskStreamingResponse # 导入流式响应类型
)

# 配置日志
logging.basicConfig(level=logging.INFO) # 可以改为 DEBUG 获取详细日志
logger = logging.getLogger(__name__)

# 测试场景1: 同步请求 - 货币转换查询 (修正)
async def test_sync_currency_conversion(client: A2AClient):
    print("\n=== 测试场景1: 同步请求 - Agent 调用 (计算器) ===")
    # query = "How much is the exchange rate for 1 USD to INR?" # 这个查询可能需要搜索工具
    query = "计算 58 * 34 的结果" # 使用计算器工具确保能得到结果
    task_id = "test_sync_" + uuid4().hex # 客户端生成任务ID
    try:
        # 1. 构建 Message 对象
        message = Message(role="user", parts=[TextPart(text=query)])

        # 2. 构建 TaskSendParams 对应的 payload 字典
        payload_dict = {
            "id": task_id,
            "sessionId": "test_session_sync_1",
            "message": message.model_dump(), # 序列化为字典
            "acceptedOutputModes": ["text"],
            "metadata": {"skill_name": "react_query"} # 与 AgentCard 中的 skill name/id 对应
        }
        logger.debug(f"Sending sync task with payload: {payload_dict}")

        # 3. 调用 send_task，传入 payload 字典
        response: SendTaskResponse = await client.send_task(payload=payload_dict)
        logger.debug(f"Send task response: {response}")

        # 4. 处理响应
        if response.error:
            error: JSONRPCError = response.error
            print(f"发送任务时出错: Code={error.code}, Message={error.message}")
            return None
        if not response.result:
             print(f"发送任务成功，但未收到任务详情: {response}")
             # 继续使用我们发送的 task_id 查询
        elif response.result.id != task_id:
            logger.warning(f"服务器返回的任务ID '{response.result.id}' 与客户端发送的ID '{task_id}' 不匹配。")
            task_id = response.result.id # 以服务器返回的为准

        print(f"任务已发送，ID: {task_id}")

        # 5. 轮询等待任务完成
        print("等待任务完成...")
        task_result: Optional[Task] = None
        for attempt in range(10):
            await asyncio.sleep(2)
            get_payload = {"id": task_id}
            logger.debug(f"Getting task with payload: {get_payload} (Attempt {attempt+1})")
            get_response: GetTaskResponse = await client.get_task(payload=get_payload)
            logger.debug(f"Get task response: {get_response}")

            if get_response.error:
                 error: JSONRPCError = get_response.error
                 print(f"获取任务时出错: Code={error.code}, Message={error.message}")
                 return None
            if not get_response.result:
                 print(f"获取任务成功，但未收到任务详情: {get_response}")
                 continue

            task_result = get_response.result
            print(f"  当前任务状态: {task_result.status.state.value}") # 使用 .value 获取枚举值
            if task_result.status.state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED]:
                break
        else:
            print("任务在限定时间内未完成。")
            return None

        # 6. 处理最终任务结果 (使用属性访问)
        if task_result.status.state == TaskState.COMPLETED and task_result.artifacts:
            print("任务成功完成。结果:")
            for artifact in task_result.artifacts:
                 if artifact.parts:
                    for part in artifact.parts:
                        if isinstance(part, TextPart): # 检查类型
                             print(f"  - {part.text}") # 访问属性
        elif task_result.status.state == TaskState.FAILED:
             error_msg = "未知错误"
             if task_result.status.message and task_result.status.message.parts:
                 if isinstance(task_result.status.message.parts[0], TextPart):
                    error_msg = task_result.status.message.parts[0].text
             print(f"任务失败: {error_msg}")
        else:
             print(f"任务最终状态为: {task_result.status.state.value}")

        return task_result

    except Exception as e:
        logger.error(f"处理同步任务时发生异常: {e}", exc_info=True)
        print(f"发送同步任务失败: {e}")
        return None

# 测试场景2: 多轮对话 - 不完整信息 (修正，但有局限性)
async def test_multi_turn_conversation(client: A2AClient):
    print("\n=== 测试场景2: 多轮对话 (Agent 可能不支持) ===")
    print("注意：当前服务器端的 Agent 实现可能不支持真正的多轮状态保持。")

    # --- 第一轮对话 ---
    session_id = "test_session_multi_" + uuid4().hex # 为多轮对话创建唯一 session ID
    query1 = "100美元等于多少" # 故意不指定目标货币
    task_id_1 = "test_multi_1_" + uuid4().hex

    try:
        print(f"\n第一轮对话 (Session: {session_id}): 发送 '{query1}'")
        # 1a. 构建 Message 和 Payload
        message1 = Message(role="user", parts=[TextPart(text=query1)])
        payload_dict1 = {
            "id": task_id_1,
            "sessionId": session_id, # 传递 session ID
            "message": message1.model_dump(),
            "acceptedOutputModes": ["text"],
            "metadata": {"skill_name": "react_query"}
        }
        logger.debug(f"Sending multi-turn task 1 with payload: {payload_dict1}")

        # 1b. 发送任务
        response1: SendTaskResponse = await client.send_task(payload=payload_dict1)
        logger.debug(f"Send task 1 response: {response1}")

        if response1.error:
            error: JSONRPCError = response1.error
            print(f"发送第一轮任务时出错: Code={error.code}, Message={error.message}")
            return None
        if response1.result:
            task_id_1 = response1.result.id # Use server-confirmed ID

        print(f"第一轮任务已发送，ID: {task_id_1}")

        # 1c. 轮询获取结果
        print("等待第一轮任务响应...")
        task1_result: Optional[Task] = None
        for attempt in range(5): # 减少轮询次数
            await asyncio.sleep(2)
            get_payload1 = {"id": task_id_1}
            get_response1: GetTaskResponse = await client.get_task(payload=get_payload1)
            if get_response1.result:
                task1_result = get_response1.result
                print(f"  当前任务状态: {task1_result.status.state.value}")
                if task1_result.status.state != TaskState.WORKING:
                    break
        else:
            print("第一轮任务在限定时间内未完成或未开始。")
            return None

        # 1d. 检查 Agent 是否要求输入 (当前 Agent 可能直接完成或失败)
        if task1_result.status.state == TaskState.INPUT_REQUIRED and task1_result.status.message:
             print("Agent 要求更多信息:")
             for part in task1_result.status.message.parts:
                 if isinstance(part, TextPart):
                     print(f"  Agent: {part.text}")

             # --- 第二轮对话 ---
             query2 = "日元" # 提供目标货币
             task_id_2 = "test_multi_2_" + uuid4().hex
             print(f"\n第二轮对话 (Session: {session_id}): 发送 '{query2}'")

             # 2a. 构建 Message 和 Payload
             message2 = Message(role="user", parts=[TextPart(text=query2)])
             payload_dict2 = {
                 "id": task_id_2,
                 "sessionId": session_id, # 必须使用相同的 session ID
                 "message": message2.model_dump(),
                 "acceptedOutputModes": ["text"],
                 "metadata": {"skill_name": "react_query"}
             }
             logger.debug(f"Sending multi-turn task 2 with payload: {payload_dict2}")

             # 2b. 发送任务
             response2: SendTaskResponse = await client.send_task(payload=payload_dict2)
             logger.debug(f"Send task 2 response: {response2}")

             if response2.error:
                 error: JSONRPCError = response2.error
                 print(f"发送第二轮任务时出错: Code={error.code}, Message={error.message}")
                 return None
             if response2.result:
                 task_id_2 = response2.result.id

             print(f"第二轮任务已发送，ID: {task_id_2}")

             # 2c. 轮询获取最终结果
             print("等待第二轮任务完成...")
             task2_result: Optional[Task] = None
             for attempt in range(10):
                 await asyncio.sleep(2)
                 get_payload2 = {"id": task_id_2}
                 get_response2: GetTaskResponse = await client.get_task(payload=get_payload2)
                 if get_response2.result:
                     task2_result = get_response2.result
                     print(f"  当前任务状态: {task2_result.status.state.value}")
                     if task2_result.status.state != TaskState.WORKING:
                         break
             else:
                 print("第二轮任务在限定时间内未完成。")
                 return None

             # 2d. 处理最终结果
             if task2_result.status.state == TaskState.COMPLETED and task2_result.artifacts:
                 print("多轮任务成功完成。最终结果:")
                 for artifact in task2_result.artifacts:
                      if artifact.parts:
                         for part in artifact.parts:
                             if isinstance(part, TextPart):
                                  print(f"  - {part.text}")
             else:
                  print(f"第二轮任务最终状态为: {task2_result.status.state.value}")

             return task2_result

        elif task1_result.status.state == TaskState.COMPLETED:
            print("Agent 在第一轮就已完成任务 (可能直接使用了默认货币或无法处理):")
            if task1_result.artifacts:
                for artifact in task1_result.artifacts:
                     if artifact.parts:
                        for part in artifact.parts:
                            if isinstance(part, TextPart):
                                print(f"  - {part.text}")
            return task1_result
        else:
            print(f"第一轮任务未要求输入，最终状态为: {task1_result.status.state.value}")
            return task1_result

    except Exception as e:
        logger.error(f"处理多轮对话时发生异常: {e}", exc_info=True)
        print(f"多轮对话测试失败: {e}")
        return None


# 测试场景3: 流式响应 (修正)
async def test_streaming_response(client: A2AClient):
    print("\n=== 测试场景3: 流式响应 (Agent 端为模拟) ===")

    # query = "What are the current exchange rates between USD, EUR, and JPY?"
    query = "用中文写一首关于春天的短诗" # 更适合流式输出的查询
    task_id = "test_stream_" + uuid4().hex
    try:
        # 1. 构建 Message 和 Payload
        message = Message(role="user", parts=[TextPart(text=query)])
        payload_dict = {
            "id": task_id,
            "sessionId": "test_session_stream_1",
            "message": message.model_dump(),
            "acceptedOutputModes": ["text"],
            "metadata": {"skill_name": "react_query"}
        }
        logger.debug(f"Sending streaming task with payload: {payload_dict}")
        print(f"任务已发送，ID: {task_id}")

        # 2. 调用 send_task_streaming (不使用 await) 并使用 async for 迭代
        event_stream_generator = client.send_task_streaming(payload=payload_dict)

        print("开始接收流式响应:")
        async for event_response in event_stream_generator:
            logger.debug(f"Received stream event: {event_response}")

            if event_response.error:
                 error: JSONRPCError = event_response.error
                 print(f"流式传输中出错: Code={error.code}, Message={error.message}")
                 continue

            event = event_response.result
            if not event:
                 logger.warning("Received stream response with empty result.")
                 continue

            # 处理状态更新事件
            if hasattr(event, "status") and event.status and event.status.message:
                 if event.status.message.parts:
                    for part in event.status.message.parts:
                        if isinstance(part, TextPart):
                            print(f"  流式更新: {part.text}")

            # 处理 Artifact 事件
            if hasattr(event, "artifact") and event.artifact:
                 # print("  收到 Artifact:") # 打印多次可能比较干扰，注释掉
                 if event.artifact.parts:
                    for part in event.artifact.parts:
                        if isinstance(part, TextPart):
                            print(f"  流式结果: {part.text}")

            # 检查结束标志
            if hasattr(event, "final") and event.final:
                 print("流式响应结束标志收到。")

        print("流式任务处理完成。")
        return True

    except Exception as e:
        logger.error(f"处理流式任务时发生异常: {e}", exc_info=True)
        print(f"发送流式任务失败: {e}")
        return False

# 主函数 (修正)
async def main():
    print("=== LangGraph Agent A2A协议测试 ===\n")
    # print("此测试脚本将测试LangGraph Currency Agent通过A2A协议的三种交互场景:")
    # print("1. 同步请求 - Agent 调用 (计算器)")
    # print("2. 多轮对话 - 处理不完整信息 (Agent 可能不支持)")
    # print("3. 流式响应 - 实时状态更新 (Agent 端为模拟)")

    # 创建A2A客户端
    client = A2AClient(url="http://127.0.0.1:8000")

    # --- 移除了 get_agent_info 调用 ---
    # (如果需要验证服务器是否在线，可以尝试发送一个简单的任务)
    print("尝试连接到服务器并运行测试...")
    print("-" * 30)

    # 执行测试场景
    await test_sync_currency_conversion(client)
    print("-" * 30)
    # 注意：多轮对话测试依赖于 Agent 对话状态的处理能力
    await test_multi_turn_conversation(client)
    print("-" * 30)
    await test_streaming_response(client)
    print("-" * 30)
    print("所有测试场景执行完毕。")

# 运行测试
if __name__ == "__main__":
    asyncio.run(main())