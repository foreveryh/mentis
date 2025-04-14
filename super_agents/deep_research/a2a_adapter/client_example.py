# super_agents/deep_research/a2a_adapter/client_example.py

import os
import sys
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4 # Import uuid

# 添加项目根目录到路径
current_script_path = Path(__file__).resolve()
project_root = current_script_path.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入A2A客户端和所需类型
from core.a2a.client.client import A2AClient
from core.a2a.client.card_resolver import A2ACardResolver # Assuming this works as intended
# Import necessary types for requests and responses
from core.a2a.types import (
    Message, TextPart, AgentCard, Task, TaskState,DataPart,
    SendTaskResponse, GetTaskResponse, JSONRPCError,
    SendTaskStreamingResponse, TaskStatusUpdateEvent, TaskArtifactUpdateEvent # Import event types
)


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    """
    DeepResearch A2A客户端示例 (已修正)
    """
    # 定义服务器配置
    HOST = os.getenv("A2A_HOST", "127.0.0.1")
    PORT = int(os.getenv("A2A_PORT", "8000"))

    print(f"\n=== DeepResearch A2A 客户端示例 ===\n")
    print(f"连接到服务器: http://{HOST}:{PORT}")
    print("-" * 40)

    # 创建A2A客户端
    client = A2AClient(url=f"http://{HOST}:{PORT}")

    # 获取Agent卡片信息
    agent_card: Optional[AgentCard] = None # Initialize agent_card
    try:
        # Assuming A2ACardResolver works and might need await if it does I/O
        # If get_agent_card is synchronous, wrap it if running in async context,
        # but for simplicity, let's assume it works or replace with direct GET if needed.
        card_resolver = A2ACardResolver(base_url=f"http://{HOST}:{PORT}")
        # If get_agent_card is async: agent_card = await card_resolver.get_agent_card()
        # If get_agent_card is sync:
        try:
            agent_card = card_resolver.get_agent_card() # Assuming sync for now
            print("\n=== Agent卡片信息 ===\n")
            print(json.dumps(agent_card.model_dump(exclude_none=True), indent=2, ensure_ascii=False))
            print("-" * 40)
        except Exception as card_err:
             logger.warning(f"同步获取Agent卡片失败: {card_err}. 可能需要异步获取或直接请求URL.")
             # Fallback or re-raise depending on requirements

    except Exception as e:
        logger.error(f"处理Agent卡片时出错: {e}")
        # Decide if execution should continue without the card info
        # return

    # --- 使用 Agent Card 判断是否支持流式 ---
    # Use a default if agent_card couldn't be fetched
    supports_streaming = False
    if agent_card and hasattr(agent_card, 'capabilities'):
        supports_streaming = agent_card.capabilities.streaming
    else:
        logger.warning("无法获取 Agent Card 或 Capabilities，将尝试非流式请求。")


    # 发送研究请求
    research_topic = input("\n请输入研究主题 (或按 Enter 使用默认): ")
    if not research_topic:
        research_topic = "特斯拉电动汽车的市场分析和未来发展趋势"
        print(f"使用默认研究主题: {research_topic}")

    print("\n=== 发送研究请求 ===\n")
    print(f"研究主题: {research_topic}")
    print("正在处理，请稍候...")

    # 创建消息
    message = Message(
        role="user",
        parts=[TextPart(text=research_topic)] # type="text" is default
    )

    # 发送任务并获取响应
    try:
        # 生成唯一任务ID
        task_id = "deep_research_" + uuid4().hex

        # 构建任务参数字典
        payload = {
            "id": task_id,
            "sessionId": "deep_research_session_" + uuid4().hex, # Unique session per run
            "message": message.model_dump(), # Serialize message to dict
            "acceptedOutputModes": ["text"],
            "metadata": {"skill_name": "deep_research"} # Match skill name/id from setup.py
        }

        if supports_streaming:
            # --- 修正流式API调用和处理 ---
            print("\n=== 流式响应 ===\n")
            print(f"任务ID: {task_id}")
            # 1. 调用 send_task_streaming (不使用 await) 获取异步生成器
            event_stream_generator = client.send_task_streaming(payload=payload)

            # 2. 使用 async for 迭代生成器
            async for event_response in event_stream_generator:
                logger.debug(f"Received stream event: {event_response}")

                # 3. 检查整个响应是否有错误
                if event_response.error:
                     error: JSONRPCError = event_response.error
                     print(f"流式传输中出错: Code={error.code}, Message={error.message}")
                     continue # 或者 break

                # 4. 获取事件具体内容 (TaskStatusUpdateEvent 或 TaskArtifactUpdateEvent)
                event = event_response.result
                if not event:
                     logger.warning("Received stream response with empty result.")
                     continue

                # 5. 根据事件类型处理 (使用 isinstance 或 hasattr)
                if isinstance(event, TaskStatusUpdateEvent):
                    if event.status and event.status.message and event.status.message.parts:
                        readable_summary = ""
                        structured_info = {}
                        for part in event.status.message.parts:
                            if isinstance(part, TextPart):
                                readable_summary = part.text # 获取人类可读的文本
                            elif isinstance(part, DataPart): # *** 处理 DataPart ***
                                structured_info = part.data # 获取结构化数据字典
                                logger.debug(f"收到结构化数据: {structured_info}") # 打印原始数据

                        # 你可以根据需要选择性地打印信息
                        if readable_summary:
                            print(f"进度更新 (文本): {readable_summary}")
                        # 或者/并且 打印结构化信息
                        if structured_info:
                            step = structured_info.get('step', '-')
                            status = structured_info.get('status', '-')
                            detail = structured_info.get('detail', '-')
                            query = structured_info.get('query')
                            source = structured_info.get('source')
                            count = structured_info.get('results_count')

                            print(f"进度更新 (结构化): [步骤: {step}, 状态: {status}]", end="")
                            if source: print(f" - 来源: {source}", end="")
                            if query: print(f" - 查询: '{query}'", end="")
                            if count is not None: print(f" - 结果数: {count}", end="")
                            print(f" - 详情: {detail}")

                elif isinstance(event, TaskArtifactUpdateEvent):
                    # ... 处理 artifact.parts (也可能包含 DataPart) ...
                    print("\n收到最终 Artifact:")
                    if event.artifact and event.artifact.parts:
                        full_report = ""
                        for part in event.artifact.parts:
                            if isinstance(part, TextPart):
                                print(f"  研究报告片段 (TextPart): {part.text}")
                                full_report += part.text + "\n"
                            elif isinstance(part, DataPart):
                                # 如果最终报告也可能在 DataPart 中
                                print(f"  研究报告片段 (DataPart): {part.data}")
                                # 假设报告主要在 TextPart
                        # 如果需要打印完整报告
                        print(f"\n=== 最终研究报告 (来自Artifact) ===\n{full_report.strip()}")

                else:
                    logger.warning(f"收到未知类型的流式事件: {type(event)}")

            print("流式任务处理完成。")

        else:
            # --- 修正非流式API调用和处理 ---
            print("\n=== 非流式响应 ===\n")
            # 1. 调用 send_task
            send_response: SendTaskResponse = await client.send_task(payload=payload)
            logger.debug(f"Send task response: {send_response}")

            if send_response.error:
                error: JSONRPCError = send_response.error
                print(f"发送任务时出错: Code={error.code}, Message={error.message}")
                return # Exit if sending failed
            if not send_response.result:
                print(f"发送任务成功，但未收到任务详情: {send_response}")
                # Use the task_id we sent for polling
            elif send_response.result.id != task_id:
                logger.warning(f"服务器返回的任务ID '{send_response.result.id}' 与客户端发送的ID '{task_id}' 不匹配。")
                task_id = send_response.result.id # Use server's ID

            print(f"任务已发送，ID: {task_id}")

            # 2. 轮询 get_task
            print("等待任务完成...")
            task_result: Optional[Task] = None
            for attempt in range(20): # Increase attempts for potentially long research tasks
                await asyncio.sleep(5) # Increase sleep time
                get_payload = {"id": task_id}
                logger.debug(f"Getting task with payload: {get_payload} (Attempt {attempt+1})")
                get_response: GetTaskResponse = await client.get_task(payload=get_payload)
                logger.debug(f"Get task response: {get_response}")

                if get_response.error:
                     error: JSONRPCError = get_response.error
                     print(f"获取任务时出错: Code={error.code}, Message={error.message}")
                     return
                if not get_response.result:
                     print(f"获取任务成功，但未收到任务详情: {get_response}")
                     continue

                task_result = get_response.result
                print(f"  当前任务状态: {task_result.status.state.value}")
                if task_result.status.state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED]:
                    break
            else:
                print("任务在限定时间内未完成。")
                return

            # 3. 处理最终结果
            if task_result.status.state == TaskState.COMPLETED and task_result.artifacts:
                print(f"\n=== 研究报告 ===")
                full_report = ""
                for artifact in task_result.artifacts:
                    if artifact.parts:
                        for part in artifact.parts:
                            if isinstance(part, TextPart):
                                full_report += part.text + "\n" # Concatenate parts
                print(full_report.strip())

            elif task_result.status.state == TaskState.FAILED:
                 error_msg = "未知错误"
                 if task_result.status.message and task_result.status.message.parts:
                     if isinstance(task_result.status.message.parts[0], TextPart):
                        error_msg = task_result.status.message.parts[0].text
                 print(f"任务失败: {error_msg}")
            else:
                 print(f"任务最终状态为: {task_result.status.state.value}")


    except Exception as e:
        logger.error(f"处理任务时发生异常: {e}", exc_info=True)
        print(f"处理任务时出错: {e}")

    print("\n=== 示例完成 ===\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n客户端已手动停止。")
    except Exception as e:
        logger.error(f"运行客户端时发生未处理的异常: {e}", exc_info=True)