# core/a2a/server/server.py
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

# --- 添加 Pydantic 的 ValidationError 导入 ---
from pydantic import ValidationError
# --- 导入结束 ---

from core.a2a.types import (
    A2ARequest,
    JSONRPCResponse,
    InvalidRequestError,
    JSONParseError,
    GetTaskRequest,
    CancelTaskRequest,
    SendTaskRequest,
    SetTaskPushNotificationRequest,
    GetTaskPushNotificationRequest,
    InternalError,
    AgentCard,
    TaskResubscriptionRequest,
    SendTaskStreamingRequest,
    MethodNotFoundError,
    # 确保 ValidationError 没有在这里导入
)
import json
from typing import AsyncIterable, Any, Optional, Union
from core.a2a.server.task_manager import TaskManager

import logging

logger = logging.getLogger(__name__)


class A2AServer:
    def __init__(
        self,
        host="0.0.0.0",
        port=5000,
        endpoint="/",
        agent_card: AgentCard = None,
        task_manager: TaskManager = None,
        allowed_origins: Optional[list[str]] = None,
    ):
        self.host = host
        self.port = port
        self.endpoint = endpoint
        self.task_manager = task_manager
        self.agent_card = agent_card

        if allowed_origins is None:
            # 本地开发时默认只允许 localhost:3000
            allowed_origins = ["http://localhost:3000"]
            logger.warning("CORS allow_origins set to 'http://localhost:3000' for local development.")
        else:
            logger.info(f"CORS allow_origins configured: {allowed_origins}")

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ]
        self.app = Starlette(middleware=middleware, debug=True)
        self.app.add_route(self.endpoint, self._process_request, methods=["POST"])
        self.app.add_route(
            "/.well-known/agent.json", self._get_agent_card, methods=["GET"]
        )
        logger.info(f"A2AServer initialized. Endpoint: {self.endpoint}, Agent Card Endpoint: /.well-known/agent.json")

    def start(self):
        if self.agent_card is None: raise ValueError("agent_card must be provided to A2AServer")
        if self.task_manager is None: raise ValueError("task_manager must be provided to A2AServer")
        import uvicorn
        logger.info(f"Starting Uvicorn server on {self.host}:{self.port}...")
        uvicorn.run(self.app, host=self.host, port=self.port)

    def _get_agent_card(self, request: Request) -> JSONResponse:
        logger.debug("Received request for /.well-known/agent.json")
        if not self.agent_card:
             logger.error("Agent card requested but not configured in A2AServer.")
             return JSONResponse({"error": "Agent card not configured"}, status_code=500)
        return JSONResponse(self.agent_card.model_dump(exclude_none=True))

    async def _process_request(self, request: Request) -> Union[JSONResponse, EventSourceResponse]:
        result = None; json_rpc_request = None; request_id_for_error = None
        try:
            try: body = await request.json(); logger.debug(f"Received request body: {body}")
            except json.JSONDecodeError as e: logger.error(f"JSON decoding failed: {e}"); raise JSONParseError()

            try:
                json_rpc_request = A2ARequest.validate_python(body); request_id_for_error = getattr(json_rpc_request, 'id', None)
                logger.info(f"Processing valid A2A request: Method='{json_rpc_request.method}', ID='{request_id_for_error}', TaskID='{getattr(json_rpc_request.params, 'id', 'N/A')}'")
            except ValidationError as e:
                logger.error(f"A2A request validation failed: {e}"); req_id_fallback = body.get('id') if isinstance(body, dict) else None
                # 注意: 这里抛出的 InvalidRequestError 会在下面的 except Exception 中被捕获
                raise InvalidRequestError(data=json.loads(e.json())) from e

            # 分发给 TaskManager
            if isinstance(json_rpc_request, GetTaskRequest): result = await self.task_manager.on_get_task(json_rpc_request)
            elif isinstance(json_rpc_request, SendTaskRequest): result = await self.task_manager.on_send_task(json_rpc_request)
            elif isinstance(json_rpc_request, SendTaskStreamingRequest): result = await self.task_manager.on_send_task_subscribe(json_rpc_request)
            elif isinstance(json_rpc_request, CancelTaskRequest): result = await self.task_manager.on_cancel_task(json_rpc_request)
            elif isinstance(json_rpc_request, SetTaskPushNotificationRequest): result = await self.task_manager.on_set_task_push_notification(json_rpc_request)
            elif isinstance(json_rpc_request, GetTaskPushNotificationRequest): result = await self.task_manager.on_get_task_push_notification(json_rpc_request)
            elif isinstance(json_rpc_request, TaskResubscriptionRequest): result = await self.task_manager.on_resubscribe_to_task(json_rpc_request)
            else: logger.warning(f"Unhandled validated request type: {type(json_rpc_request)}"); raise MethodNotFoundError(data={"method": getattr(json_rpc_request, 'method', 'unknown')})

            logger.debug(f"[A2AServer] Result from TaskManager method '{json_rpc_request.method}': type={type(result)}")
            return self._create_response(result) # 调用 _create_response

        except Exception as e:
            # 统一处理所有在请求处理（包括验证和 task manager 调用）中发生的异常
            logger.error(f"Exception during request processing: {e}", exc_info=True)
            return self._handle_exception(e, request_id=request_id_for_error) # 使用 _handle_exception

    def _handle_exception(self, e: Exception, request_id: Optional[Union[str, int]] = None) -> JSONResponse:
        status_code = 500; json_rpc_error: Optional[JSONRPCError] = None
        if isinstance(e, JSONParseError): json_rpc_error = e; status_code = 400
        elif isinstance(e, InvalidRequestError): json_rpc_error = e; status_code = 400
        elif isinstance(e, MethodNotFoundError): json_rpc_error = e; status_code = 404 # 或 501
        # --- 现在可以正确捕获 Pydantic 的 ValidationError ---
        elif isinstance(e, ValidationError):
            logger.warning(f"Pydantic Validation error caught in handler: {e}")
            error_data = str(e); 
            try: error_data = json.loads(e.json()) 
            except: pass
            # 通常 Pydantic 验证错误发生在请求处理阶段是 InvalidRequestError 的一种
            # 如果发生在响应创建阶段则更像是 InternalError
            json_rpc_error = InvalidRequestError(message="Request/Response data validation failed", data=error_data)
            status_code = 400 # 认为是客户端请求或服务器返回的数据结构问题
        # --- 捕获结束 ---
        elif isinstance(e, ValueError) and "Unexpected result type" in str(e):
             logger.error(f"Internal error due to unexpected result type: {e}", exc_info=False)
             json_rpc_error = InternalError(message="Server error: Unexpected result type from handler.")
             status_code = 500
        elif isinstance(e, NotImplementedError):
             logger.error(f"Method not implemented: {e}", exc_info=True)
             json_rpc_error = MethodNotFoundError(message=f"Method not implemented: {e}")
             status_code = 501
        else:
            logger.error(f"Unhandled internal exception: {e}", exc_info=True)
            json_rpc_error = InternalError(message=f"An internal server error occurred: {type(e).__name__}")
            status_code = 500

        response = JSONRPCResponse(id=request_id, error=json_rpc_error)
        logger.debug(f"Returning error response: {response.model_dump(exclude_none=True)}")
        return JSONResponse(response.model_dump(exclude_none=True), status_code=status_code)

    def _create_response(self, result: Any) -> Union[JSONResponse, EventSourceResponse]:
        if isinstance(result, AsyncIterable):
            logger.debug("[A2AServer] Creating EventSourceResponse (text/event-stream)")
            async def event_generator(stream_result: AsyncIterable) -> AsyncIterable[dict[str, str]]:
                try:
                    async for item in stream_result:
                        if hasattr(item, 'model_dump_json'):
                            json_data = item.model_dump_json(exclude_none=True)
                            logger.debug(f"A2AServer yielding SSE data: {json_data}")
                            yield {"data": json_data}
                        else:
                            logger.warning(f"Yielding non-Pydantic object in event stream: {type(item)}")
                            yield {"data": json.dumps(str(item))}
                except Exception as gen_err:
                    logger.error(f"Error during SSE event generation: {gen_err}", exc_info=True)
                    try:
                        # 尝试 yield 一个标准的 JSON-RPC 错误事件
                        error_payload = JSONRPCResponse(id=None, error=InternalError(message=f"Streaming generation error: {gen_err}"))
                        yield {"event": "error", "data": error_payload.model_dump_json(exclude_none=True)}
                    except Exception as yield_err:
                         logger.error(f"Failed to yield error event to SSE stream: {yield_err}", exc_info=True)

            return EventSourceResponse(event_generator(result))
        elif isinstance(result, JSONRPCResponse):
            logger.debug("[A2AServer] Creating JSONResponse (application/json)")
            return JSONResponse(result.model_dump(exclude_none=True))
        else:
            logger.error(f"Unexpected result type received by _create_response: {type(result)}")
            raise ValueError(f"Unexpected result type: {type(result)}")