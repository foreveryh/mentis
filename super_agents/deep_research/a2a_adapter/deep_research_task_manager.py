# super_agents/deep_research/a2a_adapter/deep_research_task_manager.py
import asyncio
import logging
import traceback
from typing import Dict, Any, Union, AsyncIterable, Optional, List
from collections import defaultdict # Import defaultdict

# Ensure all necessary types are imported
from core.a2a.types import (
    TaskState, TaskStatus, Task, Artifact, Message, TextPart, DataPart,
    SendTaskRequest, SendTaskResponse, GetTaskRequest, GetTaskResponse,
    CancelTaskRequest, CancelTaskResponse, SendTaskStreamingRequest, SendTaskStreamingResponse,
    SetTaskPushNotificationRequest, SetTaskPushNotificationResponse,
    GetTaskPushNotificationRequest, GetTaskPushNotificationResponse,
    TaskResubscriptionRequest, TaskSendParams, JSONRPCResponse, InvalidParamsError,
    TaskNotFoundError, TaskNotCancelableError, PushNotificationNotSupportedError,
    TaskArtifactUpdateEvent, TaskStatusUpdateEvent, InternalError, TaskIdParams,
    PushNotificationConfig
)
from core.a2a.server.task_manager import TaskManager, InMemoryTaskManager
from core.a2a.server import utils

# 导入DeepResearch相关组件
from super_agents.deep_research.reason_graph.graph import get_app
from super_agents.deep_research.reason_graph.state import ResearchState
# Assume StreamUpdate has a specific structure, likely including a 'data' field
from super_agents.deep_research.reason_graph.schemas import StreamUpdate

logger = logging.getLogger(__name__)

# Sentinel object to signal queue closure
SSE_CLOSE_SENTINEL = object()

class DeepResearchTaskManager(InMemoryTaskManager):
    """
    DeepResearchTaskManager (已修改 _process_stream_updates 以发送更详细的日志)
    """
    def __init__(self, notification_sender_auth=None):
        super().__init__()
        self.notification_sender_auth = notification_sender_auth
        self.research_app = get_app(for_web=True)
        self.sse_queues: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self.sse_queues_lock = asyncio.Lock()
        # --- ADDED: Track last processed stream update index per task ---
        self.last_stream_update_index: Dict[str, int] = defaultdict(int)
        # --- END ADDED ---

    # --- send_task_notification method (保持不变) ---
    async def send_task_notification(self, task: Task):
        # ... (代码同上一版本) ...
        if not task or not task.id: logger.error("send_task_notification called with invalid task object."); return
        try:
            has_info = await self.has_push_notification_info(task.id)
            if not has_info: logger.debug(f"No push notification info found for task {task.id}"); return
            push_info: Optional[PushNotificationConfig] = await self.get_push_notification_info(task.id)
            if not push_info or not push_info.url: logger.warning(f"Push notification info incomplete or URL missing for task {task.id}"); return
            if self.notification_sender_auth:
                logger.info(f"Sending push notification for task {task.id} to {push_info.url} (State: {task.status.state.value})")
                notification_data = task.model_dump(exclude_none=True)
                await self.notification_sender_auth.send_push_notification(push_info.url, data=notification_data)
            else: logger.warning(f"Push notification URL configured for task {task.id} but no 'notification_sender_auth' object was provided.")
        except AttributeError as e: logger.error(f"Push notification methods missing in base class? Error: {e}", exc_info=True)
        except Exception as e: logger.error(f"Failed to send push notification for task {task.id}: {e}", exc_info=True)

    # --- SSE Management Methods (保持不变) ---
    async def setup_sse_consumer(self, task_id: str) -> asyncio.Queue:
        # ... (代码同上一版本) ...
        queue = asyncio.Queue()
        async with self.sse_queues_lock: self.sse_queues[task_id].append(queue)
        logger.debug(f"SSE consumer queue created and registered for task {task_id}. Total consumers: {len(self.sse_queues[task_id])}")
        return queue

    async def enqueue_events_for_sse(self, task_id: str, event: Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent, object]):
         # ... (代码同上一版本) ...
        async with self.sse_queues_lock:
            if task_id in self.sse_queues:
                queues = self.sse_queues[task_id]
                logger.debug(f"Enqueuing event for task {task_id} to {len(queues)} consumers. Event: {type(event)}")
                put_tasks = [q.put(event) for q in queues]
                await asyncio.gather(*put_tasks, return_exceptions=True)
            else: logger.debug(f"No active SSE consumers found for task {task_id} when enqueuing event.")

    async def _cleanup_sse_queues(self, task_id: str, queue_to_remove: Optional[asyncio.Queue] = None):
         # ... (代码同上一版本) ...
        async with self.sse_queues_lock:
            if task_id in self.sse_queues:
                if queue_to_remove:
                    try: self.sse_queues[task_id].remove(queue_to_remove); logger.debug(f"Removed specific SSE queue for task {task_id}.")
                    except ValueError: logger.warning(f"Attempted to remove a non-existent SSE queue for task {task_id}.")
                else:
                    queues = self.sse_queues.pop(task_id, []); logger.debug(f"Cleaning up all {len(queues)} SSE queues for task {task_id}.")
                if not self.sse_queues.get(task_id): self.sse_queues.pop(task_id, None); logger.debug(f"Task ID {task_id} removed from SSE queue registry.")
            else: logger.debug(f"No SSE queues found for task {task_id} during cleanup.")
            # --- ADDED: Clean up last processed index ---
            self.last_stream_update_index.pop(task_id, None)
            logger.debug(f"Removed last stream update index tracker for task {task_id}.")
            # --- END ADDED ---

    async def dequeue_events_for_sse(self, request_id: str, task_id: str, queue: asyncio.Queue) -> AsyncIterable[SendTaskStreamingResponse]:
        # ... (代码同上一版本) ...
        logger.debug(f"Starting SSE event dequeuing for task {task_id}, request {request_id}.")
        try:
            while True:
                event = await queue.get()
                logger.debug(f"Dequeued event for task {task_id}, request {request_id}. Event type: {type(event)}")
                try:
                    if event is SSE_CLOSE_SENTINEL: logger.debug(f"SSE close sentinel received for task {task_id}, request {request_id}. Closing stream."); break
                    if isinstance(event, (TaskStatusUpdateEvent, TaskArtifactUpdateEvent)): yield SendTaskStreamingResponse(id=request_id, result=event)
                    else: logger.warning(f"Dequeued unexpected event type for SSE: {type(event)} for task {task_id}")
                finally:
                     if hasattr(queue, 'task_done'): queue.task_done()
                 # Check final flag AFTER processing the event
                if hasattr(event, 'final') and event.final: logger.debug(f"Received final event flag for task {task_id}, request {request_id}. Closing stream after yielding."); break
        except asyncio.CancelledError: logger.info(f"SSE stream cancelled for task {task_id}, request {request_id}.")
        except Exception as e: logger.error(f"Error during SSE event dequeuing for task {task_id}, request {request_id}: {e}", exc_info=True)
        finally: logger.debug(f"Cleaning up SSE queue for task {task_id}, request {request_id}."); await self._cleanup_sse_queues(task_id, queue)

    # --- _get_user_query (保持不变) ---
    def _get_user_query(self, task_send_params: TaskSendParams) -> str:
        # ... (代码同上一版本) ...
        if not task_send_params.message or not task_send_params.message.parts: logger.warning(f"[_get_user_query] Message or parts are empty for task {task_send_params.id}"); return ""
        part = task_send_params.message.parts[0]; text = ""
        if isinstance(part, TextPart): text = part.text
        elif isinstance(part, dict) and part.get("type") == "text": text = part.get("text", "")
        elif hasattr(part, 'text'): text = part.text
        else: logger.error(f"[_get_user_query] First part is not a recognized text part! Type: {type(part)}, Value: {part!r}"); raise ValueError(f"Expected first message part to contain text, but got {type(part)}")
        logger.debug(f"[_get_user_query] Extracted query: '{text}'"); return text.strip()

    # --- _validate_request (保持不变) ---
    def _validate_request(self, request: Union[SendTaskRequest, SendTaskStreamingRequest]) -> JSONRPCResponse | None:
         # ... (代码同上一版本) ...
        task_send_params: TaskSendParams = request.params; supported_content_types = ["text"]
        if not utils.are_modalities_compatible(task_send_params.acceptedOutputModes, supported_content_types): logger.warning(f"Unsupported output mode. Received %s, Support %s", task_send_params.acceptedOutputModes, supported_content_types); return utils.new_incompatible_types_error(request.id)
        if task_send_params.pushNotification and not task_send_params.pushNotification.url: logger.warning("Push notification URL is missing"); return JSONRPCResponse(id=request.id, error=InvalidParamsError(message="Push notification URL is missing"))
        return None

    # --- on_send_task (保持不变) ---
    async def on_send_task(self, request: SendTaskRequest) -> SendTaskResponse:
         # ... (代码同上一版本) ...
        validation_error = self._validate_request(request);
        if validation_error: return SendTaskResponse(id=request.id, error=validation_error.error)
        if request.params.pushNotification:
             try:
                if not await self.set_push_notification_info(request.params.id, request.params.pushNotification): return SendTaskResponse(id=request.id, error=InvalidParamsError(message="Failed to set push notification info"))
             except AttributeError: logger.error("set_push_notification_info method not found/implemented."); return SendTaskResponse(id=request.id, error=InternalError(message="Server config error (push notifications setup)."))
             except Exception as e: logger.error(f"Error during set_push_notification_info: {e}", exc_info=True); return SendTaskResponse(id=request.id, error=InternalError(message=f"Error setting push notification: {e}"))
        await self.upsert_task(request.params)
        task_working: Optional[Task] = await self.update_store(request.params.id, TaskStatus(state=TaskState.WORKING), None)
        if not task_working: logger.error(f"Failed to update task {request.params.id} to WORKING state."); return SendTaskResponse(id=request.id, error=InternalError(message="Failed to initialize task state."))
        await self.send_task_notification(task_working)
        asyncio.create_task(self._process_research_task(request.params))
        return SendTaskResponse(id=request.id, result=task_working)

    # --- _process_research_task (修正 finally 块) ---
    async def _process_research_task(self, task_send_params: TaskSendParams):
        query = self._get_user_query(task_send_params)
        task_id = task_send_params.id
        task_failed = None
        try:
            logger.info(f"Starting research process for task {task_id} with query: '{query}'")
            initial_state: ResearchState = { "topic": query, "depth": "advanced", "research_plan": None, "search_steps_planned": [], "analysis_steps_planned": [], "current_search_step_index": 0, "current_analysis_step_index": 0, "current_gap_search_index": 0, "search_results": [], "gap_analysis": None, "additional_queries_planned": [], "final_synthesis": None, "final_report_markdown": None, "stream_updates": [], "completed_steps_count": 0, "total_steps": 0, }
            config = {"recursion_limit": 100}

            async for current_state in self.research_app.astream(initial_state, config=config, stream_mode="values"):
                await self._process_stream_updates(task_id, current_state) # 将当前状态传递给处理函数
                if current_state.get("final_report_markdown"):
                    await self._finalize_task(task_id, current_state)
                    return # 正常结束

            logger.warning(f"Research task {task_id} stream finished without producing final report.")
            await self._finalize_task(task_id, {"final_report_markdown": "研究过程异常结束，未能生成报告。"})

        except Exception as e:
            # ... (异常处理逻辑不变, 包含 send_task_notification 和 enqueue SSE close) ...
            logger.error(f"Error during research task processing for task {task_id}: {e}", exc_info=True)
            error_message = f"研究过程中发生错误: {str(e) or type(e).__name__}"; parts = [TextPart(text=error_message)]
            task_status = TaskStatus(state=TaskState.FAILED, message=Message(role="agent", parts=parts))
            try:
                task_failed = await self.update_store(task_id, task_status, None)
                if task_failed:
                    await self.send_task_notification(task_failed)
                    status_event = TaskStatusUpdateEvent(id=task_id, status=task_status, final=True)
                    await self.enqueue_events_for_sse(task_id, status_event)
                    await self.enqueue_events_for_sse(task_id, SSE_CLOSE_SENTINEL)
                else: logger.error(f"Failed to update task {task_id} to FAILED state after error.")
            except Exception as final_err: logger.error(f"Further error during task failure handling for {task_id}: {final_err}", exc_info=True)
        finally:
            # --- 修正 finally 块 ---
            logger.debug(f"Entering finally block for task {task_id} processing.")
            # 直接访问基类提供的任务存储字典 self.tasks (假设存在)
            final_task_object: Optional[Task] = self.tasks.get(task_id) # 使用 .get() 安全地获取

            # 检查任务是否以最终状态结束
            if not final_task_object or final_task_object.status.state not in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED]:
                logger.warning(f"Task {task_id} processing ended but task not in final state ({getattr(final_task_object, 'status', None)}). Enqueuing SSE close sentinel just in case.")
                # 确保向所有等待的客户端发送关闭信号
                await self.enqueue_events_for_sse(task_id, SSE_CLOSE_SENTINEL)
            else:
                logger.debug(f"Task {task_id} processing ended in final state: {final_task_object.status.state.value}. SSE cleanup should be handled by dequeue.")
            # 不再需要在这里主动清理所有队列
            # await self._cleanup_sse_queues(task_id)
            # --- 修改结束 ---


    async def _process_stream_updates(self, task_id: str, current_state: Dict[str, Any]):
        """
        处理来自 research_app 的流式状态更新，提取详细信息并发送 A2A 事件。
        (已增强以发送更丰富的更新)
        """
        last_index = self.last_stream_update_index[task_id]
        stream_updates: List[StreamUpdate] = current_state.get("stream_updates", [])
        new_updates = stream_updates[last_index:]

        if not new_updates:
            return

        logger.debug(f"Processing {len(new_updates)} new stream updates for task {task_id} (from index {last_index})")

        for update in new_updates:
            # 尝试从 update.data 中提取结构化信息和详细消息
            # (这里的字段名 'step', 'status', 'query', 'source', 'message' 是基于日志的推测,
            # 你需要根据 StreamUpdate 的实际定义调整)
            update_data = getattr(update, 'data', None)
            structured_data = {}
            detail_message = None

            if update_data:
                detail_message = getattr(update_data, 'message', None)
                structured_data['step'] = getattr(update_data, 'step', getattr(update_data, 'step_name', None)) # 尝试不同可能的字段名
                structured_data['status'] = getattr(update_data, 'status', None)
                structured_data['query'] = getattr(update_data, 'query', None)
                structured_data['source'] = getattr(update_data, 'source', None)
                structured_data['results_count'] = getattr(update_data, 'results_count', None)
                # 添加原始消息作为备用细节
                structured_data['detail'] = detail_message if detail_message else str(update_data)[:200] + "..."
            else:
                # 如果没有 data 字段，则使用 update 本身的字符串表示
                detail_message = str(update)[:200] + "..."
                structured_data['detail'] = detail_message

            # 清理 structured_data 中的 None 值
            structured_data = {k: v for k, v in structured_data.items() if v is not None}

            # 构造人类可读的文本 (基于提取到的信息)
            readable_text = detail_message if detail_message else structured_data.get('detail', 'Processing...')
            # 可以添加更多信息到 readable_text，例如:
            prefix = ""
            if step := structured_data.get('step'): prefix += f"[{step}] "
            if query := structured_data.get('query'): prefix += f"Query: '{query}' "
            if source := structured_data.get('source'): prefix += f"Source: {source} "
            if count := structured_data.get('results_count'): prefix += f"({count} results) "
            if prefix: readable_text = prefix.strip() + (f": {detail_message}" if detail_message and not detail_message.startswith(prefix) else "")


            # 如果提取到了有效更新
            if structured_data or readable_text:
                parts_to_send = []
                # 添加结构化数据部分 (推荐)
                if structured_data:
                     logger.debug(f"Sending DataPart for task {task_id}: {structured_data}")
                     parts_to_send.append(DataPart(data=structured_data))
                # 添加人类可读文本部分
                logger.debug(f"Sending TextPart for task {task_id}: {readable_text}")
                parts_to_send.append(TextPart(text=readable_text))

                if parts_to_send:
                    message = Message(role="agent", parts=parts_to_send)
                    # 状态始终是 WORKING，因为这是中间更新
                    task_status = TaskStatus(state=TaskState.WORKING, message=message)

                    # 更新内存中的任务状态（可选）
                    task_updated = await self.update_store(task_id, task_status, None)
                    if task_updated:
                        await self.send_task_notification(task_updated) # 发送推送（如果配置）
                    else:
                        logger.warning(f"Failed to update store during stream processing for task {task_id}")

                    # 将 TaskStatusUpdateEvent 放入 SSE 队列
                    task_update_event = TaskStatusUpdateEvent(
                        id=task_id, status=task_status, final=False # final=False 表示是中间更新
                    )
                    await self.enqueue_events_for_sse(task_id, task_update_event)

        # 更新此任务已处理的最新索引
        self.last_stream_update_index[task_id] = len(stream_updates)
        logger.debug(f"Updated last stream update index for task {task_id} to {len(stream_updates)}")
    # --- 核心修改结束 ---


    # --- _finalize_task (添加 index 清理) ---
    async def _finalize_task(self, task_id: str, final_state: Dict[str, Any]):
        logger.info(f"Finalizing task {task_id}")
        final_report = final_state.get("final_report_markdown", "未能生成研究报告")
        parts = [TextPart(text=final_report)]
        artifact = Artifact(parts=parts, index=0, append=False)
        task_status = TaskStatus(state=TaskState.COMPLETED)

        task_completed = await self.update_store(task_id, task_status, [artifact])
        if task_completed: await self.send_task_notification(task_completed)
        else: logger.error(f"Failed to update task {task_id} to COMPLETED state.")

        # 发送最终事件到 SSE 队列
        artifact_event = TaskArtifactUpdateEvent(id=task_id, artifact=artifact)
        await self.enqueue_events_for_sse(task_id, artifact_event)
        status_event = TaskStatusUpdateEvent(id=task_id, status=task_status, final=True) # 标记 final=True
        await self.enqueue_events_for_sse(task_id, status_event)
        await self.enqueue_events_for_sse(task_id, SSE_CLOSE_SENTINEL) # 发送关闭信号

        # 清理 stream update index 跟踪器
        async with self.sse_queues_lock: # 使用锁确保线程安全
            self.last_stream_update_index.pop(task_id, None)
            logger.debug(f"Removed last stream update index tracker for completed task {task_id}.")

    # --- on_send_task_subscribe (保持不变, 使用已修正的 SSE 方法) ---
    async def on_send_task_subscribe(self, request: SendTaskStreamingRequest) -> Union[AsyncIterable[SendTaskStreamingResponse], JSONRPCResponse]:
        # ... (代码同上一版本) ...
        logger.debug(f"Received on_send_task_subscribe request: {request.id} for task {request.params.id}"); validation_error = self._validate_request(request);
        if validation_error: logger.warning(f"Validation failed for task {request.params.id}: {validation_error.error}"); return JSONRPCResponse(id=request.id, error=validation_error.error)
        if request.params.pushNotification:
             try:
                if not await self.set_push_notification_info(request.params.id, request.params.pushNotification): logger.warning(f"Failed to set push notification info for task {request.params.id}"); return JSONRPCResponse(id=request.id, error=InvalidParamsError(message="Failed to set push notification info"))
             except AttributeError: logger.error("set_push_notification_info method not found/implemented."); return JSONRPCResponse(id=request.id, error=InternalError(message="Server config error (push notifications setup)."))
             except Exception as e: logger.error(f"Error during set_push_notification_info for task {request.params.id}: {e}", exc_info=True); return JSONRPCResponse(id=request.id, error=InternalError(message=f"Error setting push notification: {e}"))
        await self.upsert_task(request.params)
        task_working: Optional[Task] = await self.update_store(request.params.id, TaskStatus(state=TaskState.WORKING), None)
        if not task_working: logger.error(f"Failed to update task {request.params.id} to WORKING state."); return JSONRPCResponse(id=request.id, error=InternalError(message="Failed to initialize task state."))
        await self.send_task_notification(task_working)
        logger.info(f"Creating background task for research processing: {request.params.id}")
        asyncio.create_task(self._process_research_task(request.params))
        logger.debug(f"Attempting to setup SSE for task {request.params.id}, request {request.id}")
        try:
            sse_consumer_queue = await self.setup_sse_consumer(request.params.id); logger.debug(f"SSE consumer queue setup successfully for task {request.params.id}, request {request.id}")
            result_iterable = self.dequeue_events_for_sse(request.id, request.params.id, sse_consumer_queue); logger.debug(f"[TaskManager DEBUG] Returning from on_send_task_subscribe (Success - SSE Iterable): type={type(result_iterable)}, value={result_iterable!r}")
            return result_iterable
        except Exception as e:
            logger.error(f"Fatal error setting up SSE consumer or dequeuing for task {request.params.id}, request {request.id}: {e}", exc_info=True)
            error_response = JSONRPCResponse(id=request.id, error=InternalError(message="Failed to setup streaming response channel")); logger.debug(f"[TaskManager DEBUG] Returning from on_send_task_subscribe (SSE Setup Exception): type={type(error_response)}, value={error_response!r}")
            return error_response

    # --- Other methods like on_get_task, on_cancel_task should be inherited ---
    # Implement set_push_notification_info if not provided by base class and verification is needed
    # async def set_push_notification_info(self, task_id: str, push_notification_config: PushNotificationConfig):
    #     if self.notification_sender_auth:
    #         is_verified = await self.notification_sender_auth.verify_push_notification_url(push_notification_config.url)
    #         if not is_verified:
    #             return False
    #     # Assuming base class handles storage
    #     await super().set_push_notification_info(task_id, push_notification_config)
    #     return True