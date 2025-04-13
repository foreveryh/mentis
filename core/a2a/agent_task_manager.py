import asyncio
import logging
import traceback
from typing import Dict, Any, Union, AsyncIterable, Optional
from core.a2a.types import (
    TaskState, TaskStatus, Task, Artifact, Message, TextPart,
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

logger = logging.getLogger(__name__)

class AgentTaskManager(InMemoryTaskManager):
    """
    AgentTaskManager是连接LangGraph Agent与A2A协议的关键组件。
    它负责管理任务生命周期、处理流式响应、更新任务状态以及发送推送通知。
    """
    def __init__(self, agent, notification_sender_auth=None):
        """
        初始化AgentTaskManager
        
        Args:
            agent: LangGraph Agent实例
            notification_sender_auth: 推送通知认证（可选）
        """
        super().__init__()
        self.agent = agent
        self.notification_sender_auth = notification_sender_auth
    
    async def _run_streaming_agent(self, request: SendTaskStreamingRequest):
        """
        运行流式Agent并处理响应
        
        Args:
            request: 流式任务请求
        """
        task_send_params: TaskSendParams = request.params
        query = self._get_user_query(task_send_params)
        try:
            async for item in self.agent.stream(query, task_send_params.sessionId):
                is_task_complete = item["is_task_complete"]
                require_user_input = item["require_user_input"]
                artifact = None
                message = None
                parts = [{"type": "text", "text": item["content"]}]
                end_stream = False
                
                if not is_task_complete and not require_user_input:
                    task_state = TaskState.WORKING
                    message = Message(role="agent", parts=parts)
                elif require_user_input:
                    task_state = TaskState.INPUT_REQUIRED
                    message = Message(role="agent", parts=parts)
                    end_stream = True
                else:
                    task_state = TaskState.COMPLETED
                    artifact = Artifact(parts=parts, index=0, append=False)
                    end_stream = True
                
                task_status = TaskStatus(state=task_state, message=message)
                latest_task = await self.update_store(
                    task_send_params.id,
                    task_status,
                    None if artifact is None else [artifact],
                )
                await self.send_task_notification(latest_task)

                if artifact:
                    task_artifact_update_event = TaskArtifactUpdateEvent(
                        id=task_send_params.id, artifact=artifact
                    )
                    await self.enqueue_events_for_sse(
                        task_send_params.id, task_artifact_update_event
                    )                    
                task_update_event = TaskStatusUpdateEvent(
                    id=task_send_params.id, status=task_status, final=end_stream
                )
                await self.enqueue_events_for_sse(
                    task_send_params.id, task_update_event
                )
        except Exception as e:
            logger.error(f"An error occurred while streaming the response: {e}")
            await self.enqueue_events_for_sse(
                task_send_params.id,
                InternalError(message=f"An error occurred while streaming the response: {e}")                
            )

    def _get_user_query(self, task_send_params: TaskSendParams) -> str:
        """
        从任务参数中提取用户查询 (采用 Google Demo 的严格方法)

        Args:
            task_send_params: 任务发送参数

        Returns:
            str: 用户查询文本
        """
        if not task_send_params.message or not task_send_params.message.parts:
            logger.warning(f"[_get_user_query] Message or parts are empty for task {task_send_params.id}")
            return "" # 或者可以抛出错误，取决于你的设计

        # 直接获取第一个 part
        part = task_send_params.message.parts[0]
        logger.debug(f"[_get_user_query] First part: type={type(part)}, value={part!r}") # 保留调试日志

        # 严格检查第一个 part 是否为 TextPart 实例
        if not isinstance(part, TextPart):
            logger.error(f"[_get_user_query] First part is not a TextPart instance! Type: {type(part)}")
            # 直接抛出错误，这会中断流程并提供明确信息
            raise ValueError(f"Expected first message part to be TextPart, but got {type(part)}")

        # 如果检查通过，直接返回文本
        logger.debug(f"[_get_user_query] Extracted query from TextPart: '{part.text}'")
        return part.text


    def _validate_request(
        self, request: Union[SendTaskRequest, SendTaskStreamingRequest]
    ) -> JSONRPCResponse | None:
        """
        验证请求参数
        
        Args:
            request: 任务请求
            
        Returns:
            JSONRPCResponse | None: 错误响应或None
        """
        task_send_params: TaskSendParams = request.params
        if not utils.are_modalities_compatible(
            task_send_params.acceptedOutputModes, self.agent.SUPPORTED_CONTENT_TYPES
        ):
            logger.warning(
                "Unsupported output mode. Received %s, Support %s",
                task_send_params.acceptedOutputModes,
                self.agent.SUPPORTED_CONTENT_TYPES,
            )
            return utils.new_incompatible_types_error(request.id)
        
        if task_send_params.pushNotification and not task_send_params.pushNotification.url:
            logger.warning("Push notification URL is missing")
            return JSONRPCResponse(id=request.id, error=InvalidParamsError(message="Push notification URL is missing"))
        
        return None
        
    async def on_send_task(self, request: SendTaskRequest) -> SendTaskResponse:
        """
        处理发送任务请求
        
        Args:
            request: 任务请求
            
        Returns:
            SendTaskResponse: 任务响应
        """
        validation_error = self._validate_request(request)
        if validation_error:
            return SendTaskResponse(id=request.id, error=validation_error.error)
        
        if request.params.pushNotification:
            if not await self.set_push_notification_info(request.params.id, request.params.pushNotification):
                return SendTaskResponse(id=request.id, error=InvalidParamsError(message="Push notification URL is invalid"))

        await self.upsert_task(request.params)
        task = await self.update_store(
            request.params.id, TaskStatus(state=TaskState.WORKING), None
        )
        await self.send_task_notification(task)

        task_send_params: TaskSendParams = request.params
        query = self._get_user_query(task_send_params)
        try:
            agent_response = self.agent.invoke(query, task_send_params.sessionId)
            # 处理Agent响应并更新任务状态
            parts = [{"type": "text", "text": agent_response}]
            artifact = Artifact(parts=parts, index=0, append=False)
            task = await self.update_store(
                task_send_params.id, 
                TaskStatus(state=TaskState.COMPLETED), 
                [artifact]
            )
            await self.send_task_notification(task)
            return SendTaskResponse(id=request.id, result=task)

        except Exception as e:
            # 建议也稍微改进一下异常处理日志和返回信息
            logger.error(f"Error during agent invocation or task processing: {e}", exc_info=True)
            # 记录失败状态
            try:
                # 确保即使在异常处理中也能更新状态
                task_failed : Task = await self.update_store(
                    task_send_params.id,
                    TaskStatus(state=TaskState.FAILED, error={"message": str(e)}),
                    None
                )
                await self.send_task_notification(task_failed)
            except Exception as update_err:
                # 如果更新状态也失败，记录下来
                logger.error(f"Failed to update task status to FAILED after initial error: {update_err}", exc_info=True)

            # 返回更合适的错误类型和消息
            # return SendTaskResponse(id=request.id, error=InvalidParamsError(message=f"Error processing task: {e}"))
            # InternalError 可能更合适，因为错误发生在服务器内部处理中
            return SendTaskResponse(id=request.id, error=InternalError(message=f"Error processing task: {str(e) or type(e).__name__}"))

    
    async def on_send_task_subscribe(
        self, request: SendTaskStreamingRequest
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        """
        处理流式任务请求
        
        Args:
            request: 流式任务请求
            
        Returns:
            AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse: 流式响应或错误
        """
        try:
            error = self._validate_request(request)
            if error:
                return error
            
            await self.upsert_task(request.params)
            
            if request.params.pushNotification:
                if not await self.set_push_notification_info(request.params.id, request.params.pushNotification):
                    return JSONRPCResponse(id=request.id, error=InvalidParamsError(message="Push notification URL is invalid"))
            
            task_send_params: TaskSendParams = request.params
            sse_event_queue = await self.setup_sse_consumer(task_send_params.id, False)            
            asyncio.create_task(self._run_streaming_agent(request))
            
            return self.dequeue_events_for_sse(
                request.id, task_send_params.id, sse_event_queue
            )
        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")
            print(traceback.format_exc())
            return JSONRPCResponse(
                id=request.id,
                error=InternalError(
                    message="An error occurred while streaming the response"
                ),
            )

    async def _process_agent_response(
        self, request: SendTaskRequest, agent_response: dict
    ) -> SendTaskResponse:
        """Processes the agent's response and updates the task store."""
        task_send_params: TaskSendParams = request.params
        task_id = task_send_params.id
        history_length = task_send_params.historyLength
        task_status = None

        parts = [{"type": "text", "text": agent_response["content"]}]
        artifact = None
        if agent_response["require_user_input"]:
            task_status = TaskStatus(
                state=TaskState.INPUT_REQUIRED,
                message=Message(role="agent", parts=parts),
            )
        else:
            task_status = TaskStatus(state=TaskState.COMPLETED)
            artifact = Artifact(parts=parts)
        task = await self.update_store(
            task_id, task_status, None if artifact is None else [artifact]
        )
        task_result = self.append_task_history(task, history_length)
        await self.send_task_notification(task)
        return SendTaskResponse(id=request.id, result=task_result)
    
    async def on_resubscribe_to_task(
        self, request: TaskResubscriptionRequest
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        task_id_params: TaskIdParams = request.params
        try:
            sse_event_queue = await self.setup_sse_consumer(task_id_params.id, True)
            return self.dequeue_events_for_sse(request.id, task_id_params.id, sse_event_queue)
        except Exception as e:
            logger.error(f"Error while reconnecting to SSE stream: {e}")
            return JSONRPCResponse(
                id=request.id,
                error=InternalError(
                    message=f"An error occurred while reconnecting to stream: {e}"
                ),
            )
    
    async def send_task_notification(self, task: Task):
        if not await self.has_push_notification_info(task.id):
            logger.info(f"No push notification info found for task {task.id}")
            return
        push_info = await self.get_push_notification_info(task.id)

        logger.info(f"Notifying for task {task.id} => {task.status.state}")
        await self.notification_sender_auth.send_push_notification(
            push_info.url,
            data=task.model_dump(exclude_none=True)
        )

    async def set_push_notification_info(self, task_id: str, push_notification_config: PushNotificationConfig):
        # Verify the ownership of notification URL by issuing a challenge request.
        if self.notification_sender_auth:
            is_verified = await self.notification_sender_auth.verify_push_notification_url(push_notification_config.url)
            if not is_verified:
                return False
        
        await super().set_push_notification_info(task_id, push_notification_config)
        return True