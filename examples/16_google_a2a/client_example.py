# examples/a2a/client_example.py

import os
import sys
import asyncio
import json
import logging # 添加 logging
from typing import Dict, Any, List, Optional
from uuid import uuid4 # 用于生成示例 Task ID

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入A2A客户端和类型
from core.a2a.client.client import A2AClient
# 导入 Message 和 TextPart 以构建请求，导入响应类型以进行类型提示
from core.a2a.types import (
    Part, TextPart, Message, TaskState, # 添加 TaskState
    SendTaskResponse, GetTaskResponse, SendTaskStreamingResponse, Task, # 添加 Task
    JSONRPCError # 添加 JSONRPCError
)

# 配置日志
logging.basicConfig(level=logging.INFO) # 可以改为 DEBUG 获取更详细客户端日志
logger = logging.getLogger(__name__)

# 示例: 使用A2A客户端连接到A2A服务器
async def run_a2a_client():
    print("\n=== 运行A2A客户端示例 ===\n")

    # 创建A2A客户端
    client = A2AClient(url="http://127.0.0.1:8000") # 指向你的服务器地址

    # 发送同步任务
    await send_sync_task(client)

    # 发送流式任务
    await send_streaming_task(client)

# --- 修正发送同步任务 ---
async def send_sync_task(client: A2AClient):
    print("\n=== 发送同步任务 ===\n")
    query = "请计算 123 + 456 的结果"
    task_id = "client_sync_" + uuid4().hex # 生成一个唯一的任务 ID
    try:
        # 1. 构建 Message 对象
        message = Message(role="user", parts=[TextPart(text=query)])

        # 2. 构建 TaskSendParams 对应的 payload 字典 (添加 id)
        payload_dict = {
            "id": task_id, # --- 添加必需的 id 字段 ---
            "sessionId": "client_session_sync_1",
            "message": message.model_dump(),
            "acceptedOutputModes": ["text"],
            "metadata": {"skill_name": "react_query"}
        }
        logger.debug(f"Sending sync task with payload: {payload_dict}")

        # 3. 调用 send_task，传入 payload 字典
        response: SendTaskResponse = await client.send_task(payload=payload_dict)
        logger.debug(f"Send task response: {response}")

        # 4. 处理响应
        if response.error:
            # 类型提示帮助访问属性
            error: JSONRPCError = response.error
            print(f"发送任务时出错: Code={error.code}, Message={error.message}")
            return
        # SendTaskResponse 的 result 是 Task 对象或 None
        if not response.result:
             print(f"发送任务成功，但响应中未包含任务详情: {response}")
             # 我们可以继续使用我们发送的 task_id 来查询状态
        elif response.result.id != task_id:
            # 理论上服务器应该使用或确认客户端提供的 ID
             logger.warning(f"服务器返回的任务ID '{response.result.id}' 与客户端发送的ID '{task_id}' 不匹配。")
             task_id = response.result.id # 以服务器返回的为准（如果存在）


        print(f"任务已发送，ID: {task_id}")

        # --- 轮询等待任务完成 ---
        print("等待任务完成...")
        task_result: Optional[Task] = None # 用于存储最终的任务对象
        for attempt in range(10): # 最多尝试 10 次
            await asyncio.sleep(2) # 等待 2 秒

            # 5. 构建 get_task 的 payload
            get_payload = {"id": task_id}
            logger.debug(f"Getting task with payload: {get_payload} (Attempt {attempt+1})")

            # 6. 获取任务结果 (传入 payload 字典)
            get_response: GetTaskResponse = await client.get_task(payload=get_payload)
            logger.debug(f"Get task response: {get_response}")

            if get_response.error:
                 error: JSONRPCError = get_response.error
                 print(f"获取任务时出错: Code={error.code}, Message={error.message}")
                 return # 出错则停止轮询
            if not get_response.result:
                 print(f"获取任务成功，但未收到任务详情: {get_response}")
                 continue # 继续轮询

            task_result = get_response.result # 获取任务对象
            print(f"  当前任务状态: {task_result.status.state}")
            # 检查任务是否完成或失败
            if task_result.status.state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.INPUT_REQUIRED]:
                break
        else:
            print("任务在限定时间内未完成。")
            return

        # 7. 处理最终任务结果 (使用属性访问)
        if task_result.status.state == TaskState.COMPLETED and task_result.artifacts:
            print("任务成功完成。结果:")
            for artifact in task_result.artifacts:
                 if artifact.parts:
                    for part in artifact.parts:
                        if isinstance(part, TextPart):
                             print(f"  - {part.text}")
        elif task_result.status.state == TaskState.FAILED:
             error_msg = "未知错误"
             if task_result.status.message and task_result.status.message.parts:
                 # 假设错误信息在第一个 TextPart
                 if isinstance(task_result.status.message.parts[0], TextPart):
                    error_msg = task_result.status.message.parts[0].text
             print(f"任务失败: {error_msg}")
        else:
             print(f"任务最终状态为: {task_result.status.state}")

    except Exception as e:
        logger.error(f"发送或处理同步任务时发生异常: {e}", exc_info=True)
        print(f"发送同步任务失败: {e}")

# --- 修正发送流式任务 ---
async def send_streaming_task(client: A2AClient):
    print("\n=== 发送流式任务 ===\n")
    query = "请搜索关于人工智能的最新进展"
    task_id = "client_stream_" + uuid4().hex # 为流式任务生成 ID
    try:
        # 1. 构建 Message 对象
        message = Message(role="user", parts=[TextPart(text=query)])

        # 2. 构建 TaskSendParams 对应的 payload 字典 (添加 id)
        payload_dict = {
            "id": task_id, # --- 添加必需的 id 字段 ---
            "sessionId": "client_session_stream_1",
            "message": message.model_dump(),
            "acceptedOutputModes": ["text"],
            "metadata": {"skill_name": "react_query"}
        }
        logger.debug(f"Sending streaming task with payload: {payload_dict}")
        print(f"任务已发送，ID: {task_id}") # 流式任务 ID 在发送时就已知

        # 3. 调用 send_task_streaming (不再使用 await)
        # 它返回一个异步生成器
        event_stream_generator = client.send_task_streaming(payload=payload_dict)

        # 4. 使用 async for 处理流式事件
        print("开始接收流式响应:")
        async for event_response in event_stream_generator: # 正确迭代异步生成器
            logger.debug(f"Received stream event: {event_response}")

            # 检查整个响应是否有错误
            if event_response.error:
                 error: JSONRPCError = event_response.error
                 print(f"流式传输中出错: Code={error.code}, Message={error.message}")
                 continue # 或 break

            # 获取事件具体内容
            event = event_response.result
            if not event:
                 logger.warning("Received stream response with empty result.")
                 continue

            # 处理状态更新事件中的消息部分
            if hasattr(event, "status") and event.status and event.status.message:
                 if event.status.message.parts:
                    for part in event.status.message.parts:
                        if isinstance(part, TextPart):
                            print(f"  流式更新: {part.text}")

            # 处理制品更新事件
            if hasattr(event, "artifact") and event.artifact:
                 print("  收到 Artifact:")
                 if event.artifact.parts:
                    for part in event.artifact.parts:
                        if isinstance(part, TextPart):
                            print(f"    流式结果 (TextPart): {part.text}")

            # 检查流结束标志
            if hasattr(event, "final") and event.final:
                 print("流式响应结束标志收到。")

        print("流式任务处理完成。")

    except Exception as e:
        logger.error(f"发送或处理流式任务时发生异常: {e}", exc_info=True)
        print(f"发送流式任务失败: {e}")

# 主函数
if __name__ == "__main__":
    # 使用 asyncio.run 运行顶层异步函数
    asyncio.run(run_a2a_client())