import os
import asyncio
# --- 需要添加的 Imports ---
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Type, Literal, TypedDict
from types import TracebackType
# --- 添加结束 ---
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
try:
     from langchain_mcp_adapters.tools import load_mcp_tools
     LOAD_MCP_TOOLS_AVAILABLE = True
except ImportError:
     print("警告: 未找到 langchain-mcp-adapters。 load_mcp_tools 将不可用。")
     async def load_mcp_tools(session: ClientSession) -> list: return []
     LOAD_MCP_TOOLS_AVAILABLE = False

# --- 保持原来的导入 ---
from langchain_core.tools import BaseTool
from contextlib import asynccontextmanager, AsyncExitStack
import traceback
import json
try:
    from pydantic.v1 import BaseModel as BaseModelV1
except ImportError:
    from pydantic import BaseModel as BaseModelV1

# --- 添加缺失的 TypedDict 定义 ---
EncodingErrorHandler = Literal["strict", "ignore", "replace"]
DEFAULT_ENCODING = "utf-8"
DEFAULT_ENCODING_ERROR_HANDLER: EncodingErrorHandler = "strict"
DEFAULT_HTTP_TIMEOUT = 5.0 # 使用浮点数
DEFAULT_SSE_READ_TIMEOUT = 60.0 * 5 # 使用浮点数

class StdioConnection(TypedDict, total=False): # total=False 表示键是可选的
    transport: Literal["stdio"] # 必需
    command: str # 必需
    args: List[str] # 必需
    env: Optional[Dict[str, str]]
    cwd: Optional[Union[str, Path]]
    encoding: str # 可以设为 Optional[str] 如果想用默认值
    encoding_error_handler: EncodingErrorHandler # 可以设为 Optional[...]
    session_kwargs: Optional[Dict[str, Any]]

class SSEConnection(TypedDict, total=False): # total=False 表示键是可选的
    transport: Literal["sse"] # 必需
    url: str # 必需
    headers: Optional[Dict[str, Any]]
    timeout: float # 可以设为 Optional[float]
    sse_read_timeout: float # 可以设为 Optional[float]
    session_kwargs: Optional[Dict[str, Any]]
# --- 定义结束 ---

class MentisMCPClient:
    """
    Mentis MCP 客户端 (优化版)
    """
    def __init__(self):
        """初始化 Mentis MCP 客户端"""
        self.session: Optional[ClientSession] = None
        self.tools: List[BaseTool] = []
        # 使用 AsyncExitStack 来管理上下文
        self._stack: AsyncExitStack = AsyncExitStack()
        # 保留对 transport context 的引用，虽然 stack 会管理关闭
        self._transport_ctx: Optional[Any] = None

    async def _connect_internal(self, transport_ctx):
        """内部连接和初始化逻辑"""
        # 使用 self._stack 管理 transport 和 session 上下文
        try:
             self._transport_ctx = transport_ctx # 保存引用
             reader, writer = await self._stack.enter_async_context(transport_ctx)
             print("DEBUG: Transport context entered (streams acquired).")

             session_ctx = ClientSession(reader, writer)
             self.session = await self._stack.enter_async_context(session_ctx)
             print("DEBUG: ClientSession context entered.")

             print("正在初始化 MCP 会话...")
             await asyncio.wait_for(self.session.initialize(), timeout=20.0)
             print("MCP 会话初始化完成.")

             if LOAD_MCP_TOOLS_AVAILABLE:
                 print("正在加载 MCP 工具 (来自 langchain-mcp-adapters)...")
                 # --- 关键诊断步骤：打印加载后的工具及其 Schema ---
                 loaded_tools_from_mcp = await load_mcp_tools(self.session)
                 print(f"成功从服务器加载 {len(loaded_tools_from_mcp)} 个工具描述。")
                 print("--- 加载的工具及其 Args Schema (供调试) ---")
                 self.tools = []
                 for i, tool in enumerate(loaded_tools_from_mcp):
                      schema = getattr(tool, 'args_schema', 'N/A')
                      tool_name = getattr(tool, 'name', f'Tool_{i+1}')
                      print(f"{i+1}. Tool Name: {tool_name}")
                      print(f"   Description: {getattr(tool, 'description', 'N/A')}")
                      # 尝试更详细地打印 Schema
                      if schema != 'N/A':
                           if isinstance(schema, type) and issubclass(schema, BaseModelV1):
                                try:
                                     # Pydantic v1 schema()
                                     schema_dict = schema.schema()
                                     print(f"   Args Schema (Pydantic .schema()):\n{json.dumps(schema_dict, indent=2)}")
                                     # --- 在这里添加针对已知工具的 Schema 检查逻辑 ---
                                     if tool_name == "e2b_code_interpreter":
                                         if 'properties' in schema_dict and 'code' in schema_dict['properties'] and 'kwargs' not in schema_dict['properties']:
                                              print("   ✅ Schema 符合 E2B 预期 (包含 'code', 不含 'kwargs')")
                                         else:
                                              print("   ❌ Schema 不符合 E2B 预期! 'code' 字段缺失或存在 'kwargs'。")
                                     elif tool_name == "python_repl": # 假设 ExecPython 注册名是这个
                                         if 'properties' in schema_dict and 'command' in schema_dict['properties'] and 'kwargs' not in schema_dict['properties']:
                                               print("   ✅ Schema 符合 ExecPython 预期 (包含 'command', 不含 'kwargs')")
                                         else:
                                               print(f"  ❌ Schema 不符合 ExecPython 预期! 检查需要 'command' 还是 'code'?")
                                     # ----------------------------------------------------
                                except Exception as e_schema_v1:
                                     print(f"   Args Schema: {schema} (获取 .schema() 出错: {e_schema_v1})")
                           elif hasattr(schema, 'model_json_schema'): # 检查 Pydantic V2
                                try:
                                     schema_dict = schema.model_json_schema()
                                     print(f"   Args Schema (Pydantic V2 .model_json_schema()):\n{json.dumps(schema_dict, indent=2)}")
                                     # 添加 V2 的检查逻辑...
                                except Exception as e_schema_v2:
                                     print(f"   Args Schema: {schema} (获取 .model_json_schema() 出错: {e_schema_v2})")
                           else:
                                print(f"   Args Schema: {schema} (类型未知或无法解析)")
                      else:
                           print(f"   Args Schema: N/A (工具未定义 Args Schema?)")
                           print(f"   ❌ 警告: 工具 '{tool_name}' 未定义清晰的输入 Schema，可能导致 Agent 调用失败!")
                      print("-" * 15)
                      self.tools.append(tool)
                 print("-------------------------------------------")
                 # --- 诊断结束 ---
             else:
                 print("警告: load_mcp_tools 不可用，无法加载工具。")
                 self.tools = []

             print(f"客户端准备就绪，共加载 {len(self.tools)} 个工具。")
             return self.tools

        except Exception as connect_err:
             print(f"ERROR during _connect_internal: {connect_err}")
             # 出错时，尝试让 AsyncExitStack 清理已进入的上下文
             if self._stack:
                 print("Attempting cleanup via AsyncExitStack due to connection error...")
                 await self._stack.aclose()
                 self._stack = None # 重置
             # 重置状态
             self.session = None
             self.read = None
             self.write = None
             self.tools = []
             raise # 重新抛出连接错误

    async def connect_stdio(self, command: str, args: List[str]):
        """连接到 stdio 传输的 MCP 服务器"""
        if self._stack: await self.close() # 先关闭旧的 stack
        self._stack = AsyncExitStack() # 创建新的 stack
        server_params = StdioServerParameters(command=command, args=args, startup_timeout=30.0)
        print(f"正在启动 MCP 服务器 (stdio): {command} {' '.join(args)}")
        return await self._connect_internal(stdio_client(server_params))


    async def connect_sse(self, url: str):
        """连接到 SSE 传输的 MCP 服务器"""
        if self._stack: await self.close() # 先关闭旧的 stack
        self._stack = AsyncExitStack() # 创建新的 stack
        if not url.startswith("http://") and not url.startswith("https://"): url = f"http://{url}"
        print(f"正在连接到 SSE 服务器: {url}")
        # 注意: sse_client 的参数可能需要根据实际库版本调整
        sse_ctx = sse_client(url) # 使用默认超时等
        return await self._connect_internal(sse_ctx)

    async def close(self):
        """关闭连接和所有管理的上下文"""
        print("开始关闭 MCP 客户端...")
        if self._stack:
            print("  正在关闭管理的异步上下文 (via AsyncExitStack)...")
            try:
                await self._stack.aclose()
                print("  所有上下文已关闭。")
            except Exception as e:
                # 这里的错误更可能是 anyio/asyncio 底层问题
                print(f"警告: 关闭 AsyncExitStack 时出错 (可能与 asyncio 关闭有关): {type(e).__name__}: {e}")
                # traceback.print_exc() # 可以取消注释以获取完整堆栈，但可能很长
            finally:
                 self._stack = None # 重置 stack
        else:
             print("  没有活动的 AsyncExitStack 需要关闭。")

        # 重置状态
        self.session = None
        self.read = None
        self.write = None
        self.tools = []
        self._transport_ctx = None # 清理 transport 引用
        print("MCP 客户端状态已重置。")

    def get_tools(self) -> List[BaseTool]:
        """获取加载的工具列表"""
        return self.tools

# --- MultiServerMCPClient 和 get_mcp_client ---
# MultiServerMCPClient 内部已经使用了 AsyncExitStack，无需修改
# get_mcp_client 可以继续使用，它会创建并返回 MentisMCPClient 实例
class MultiServerMCPClient:
    """Client for connecting to multiple MCP servers."""
    # ... (使用之前提供的官方版本代码，它内部用了 AsyncExitStack) ...
    def __init__(
        self, connections: dict[str, StdioConnection | SSEConnection] | None = None
    ) -> None:
        self.connections: dict[str, StdioConnection | SSEConnection] = connections or {}
        self.exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.server_name_to_tools: dict[str, list[BaseTool]] = {}
    async def _initialize_session_and_load_tools(self, server_name: str, session: ClientSession) -> None:
        await session.initialize()
        self.sessions[server_name] = session
        if LOAD_MCP_TOOLS_AVAILABLE and load_mcp_tools:
             server_tools = await load_mcp_tools(session)
             # --- 这里也加入 Schema 打印 ---
             print(f"\n--- Loaded Tools & Schemas for server '{server_name}' ---")
             for i, tool in enumerate(server_tools):
                 schema = getattr(tool, 'args_schema', 'N/A')
                 tool_name = getattr(tool, 'name', f'Tool_{i+1}')
                 print(f"{i+1}. Tool Name: {tool_name}")
                 if schema != 'N/A' and isinstance(schema, type) and issubclass(schema, BaseModelV1):
                     try:
                          schema_dict = schema.schema()
                          print(f"   Args Schema:\n{json.dumps(schema_dict, indent=2)}")
                     except Exception as e_schema: print(f"   Args Schema: {schema} (Error: {e_schema})")
                 else: print(f"   Args Schema: {schema}")
                 print("-" * 10)
             print("-------------------------------------------")
             self.server_name_to_tools[server_name] = server_tools
        else:
             print(f"Cannot load tools for '{server_name}', load_mcp_tools unavailable.")
             self.server_name_to_tools[server_name] = []
    async def connect_to_server(self, server_name: str, *, transport: Literal["stdio", "sse"] = "stdio", **kwargs,) -> None:
         # ... (保持不变, 调用下方具体方法) ...
        if transport == "sse":
            if "url" not in kwargs: raise ValueError("'url' required for SSE")
            await self.connect_to_server_via_sse(server_name,url=kwargs["url"],headers=kwargs.get("headers"),timeout=kwargs.get("timeout", 5.0),sse_read_timeout=kwargs.get("sse_read_timeout", 300.0),session_kwargs=kwargs.get("session_kwargs"),)
        elif transport == "stdio":
            if "command" not in kwargs: raise ValueError("'command' required for stdio")
            if "args" not in kwargs: raise ValueError("'args' required for stdio")
            await self.connect_to_server_via_stdio(server_name,command=kwargs["command"],args=kwargs["args"],env=kwargs.get("env"),encoding=kwargs.get("encoding", "utf-8"),encoding_error_handler=kwargs.get("encoding_error_handler", "strict"),session_kwargs=kwargs.get("session_kwargs"),)
        else: raise ValueError(f"Unsupported transport: {transport}")
    async def connect_to_server_via_stdio(self, server_name: str, *, command: str, args: list[str], env: dict[str, str] | None = None, encoding: str = "utf-8", encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict", session_kwargs: dict[str, Any] | None = None,) -> None:
        env = env or {}; env.setdefault("PATH", os.environ.get("PATH", ""))
        server_params = StdioServerParameters(command=command, args=args, env=env, encoding=encoding, encoding_error_handler=encoding_error_handler)
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        read, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(read, write, **(session_kwargs or {})))
        await self._initialize_session_and_load_tools(server_name, cast(ClientSession, session))
    async def connect_to_server_via_sse(self, server_name: str, *, url: str, headers: dict[str, Any] | None = None, timeout: float = 5.0, sse_read_timeout: float = 300.0, session_kwargs: dict[str, Any] | None = None,) -> None:
        sse_transport = await self.exit_stack.enter_async_context(sse_client(url, headers, timeout, sse_read_timeout))
        read, write = sse_transport
        session = await self.exit_stack.enter_async_context(ClientSession(read, write, **(session_kwargs or {})))
        await self._initialize_session_and_load_tools(server_name, cast(ClientSession, session))
    def get_tools(self) -> list[BaseTool]:
        all_tools: list[BaseTool] = []; [all_tools.extend(server_tools) for server_tools in self.server_name_to_tools.values()]
        return all_tools
    async def get_prompt(self, server_name: str, prompt_name: str, arguments: Optional[dict[str, Any]]) -> list:
        session = self.sessions[server_name]; return await load_mcp_prompt(session, prompt_name, arguments)
    async def __aenter__(self) -> "MultiServerMCPClient":
        try:
            for server_name, connection in self.connections.items(): await self.connect_to_server(server_name, **connection)
            return self
        except Exception: await self.exit_stack.aclose(); raise
    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType],) -> None:
        await self.exit_stack.aclose()


@asynccontextmanager
async def get_mcp_client(stdio_script_path: Optional[str] = None,
                         sse_url: Optional[str] = None) -> MentisMCPClient:
    """获取 MCP 客户端的异步上下文管理器 (保持不变)"""
    client = MentisMCPClient()
    try:
        if stdio_script_path:
            await client.connect_stdio(command=sys.executable, args=[stdio_script_path])
        elif sse_url:
            await client.connect_sse(url=sse_url)
        else:
            raise ValueError("Either stdio_script_path or sse_url must be provided")
        yield client
    finally:
        await client.close()