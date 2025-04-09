# core/mcp/client.py (重构版 - 使用配置对象)

import os
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Type, Literal, TypedDict, cast
from types import TracebackType
import re # 用于从 stdout 提取 URL
import sys # 用于 stderr 输出
from langchain_core.tools import BaseTool, Tool
# --- MCP Imports ---
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
# --- Adapter Import ---
try:
     from langchain_mcp_adapters.tools import load_mcp_tools
     LOAD_MCP_TOOLS_AVAILABLE = True
except ImportError:
     print("警告: 未找到 langchain-mcp-adapters。 load_mcp_tools 将不可用。")
     async def load_mcp_tools(session: ClientSession) -> list: return []
     LOAD_MCP_TOOLS_AVAILABLE = False
# --- LangChain / Pydantic Imports ---
from langchain_core.tools import BaseTool
from contextlib import asynccontextmanager, AsyncExitStack
import traceback
import json
try: from pydantic.v1 import BaseModel as BaseModelV1
except ImportError: from pydantic import BaseModel as BaseModelV1

# --- 从 config_loader 导入配置模型 ---
# (确保 config_loader.py 在同一目录下或 sys.path 中)
try:
    from .config_loader import MCPConfig, StdioConfig, SSEConfig
except ImportError:
     # 如果直接运行 client.py 可能导入失败，提供 fallback 定义（不推荐）
     print("WARNING: Could not import config models from .config_loader. Using placeholder types.")
     class MCPConfig(BaseModelV1): connection: Any = None; timeout: int = 30 # Placeholder
     class StdioConfig(BaseModelV1): command: str = ""; args: List[str] = []; env: Optional[Dict[str, str]] = None; transport: str = "stdio"
     class SSEConfig(BaseModelV1): url: str = ""; transport: str = "sse"

print("--- DEBUG: Loading REFACTORED client.py (Config-Driven) ---")

# --- 新的 MCPClient ---
class MCPClient:
    """
    Config-driven MCP Client based on user guide.
    Handles server startup (command) or direct connection (url).
    Uses AsyncExitStack for resource management.
    Still uses load_mcp_tools internally for tool loading diagnostics.
    """
    def __init__(self, config: MCPConfig):
        """Initialize with a validated MCPConfig object."""
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools: List[BaseTool] = [] # Tools loaded by load_mcp_tools
        self._stack: AsyncExitStack = AsyncExitStack()
        self._server_process: Optional[asyncio.subprocess.Process] = None # For command-launched SSE server

    async def __aenter__(self) -> "MCPClient":
        """Establishes connection based on config."""
        print(f"DEBUG: MCPClient entering context for config ID: {self.config.id or 'N/A'}")
        try:
            connection_config = self.config.connection
            transport_ctx = None

            if isinstance(connection_config, SSEConfig) and connection_config.url:
                # --- Direct SSE Connection ---
                print(f"DEBUG: Configured for direct SSE connection to {connection_config.url}")
                transport_ctx = sse_client(
                    connection_config.url,
                    connection_config.headers,
                    connection_config.timeout,
                    connection_config.sse_read_timeout
                )
                self._transport_ctx = transport_ctx # Keep reference if needed
                reader, writer = await self._stack.enter_async_context(transport_ctx)
                print("DEBUG: SSE transport context entered.")

            elif isinstance(connection_config, StdioConfig) and connection_config.command:
                # --- Launch via Command ---
                print(f"DEBUG: Configured to launch command: {connection_config.command} {' '.join(connection_config.args)}")

                if connection_config.transport == "stdio":
                    # --- Launch and connect via STDIO ---
                    print("DEBUG: Using STDIO transport.")
                    merged_env = os.environ.copy()
                    if connection_config.env: merged_env.update(connection_config.env)
                    server_params = StdioServerParameters(
                        command=connection_config.command,
                        args=connection_config.args,
                        env=merged_env,
                        cwd=connection_config.cwd,
                        encoding=connection_config.encoding,
                        encoding_error_handler=connection_config.encoding_error_handler,
                        startup_timeout=connection_config.timeout
                    )
                    transport_ctx = stdio_client(server_params)
                    self._transport_ctx = transport_ctx # Keep reference
                    reader, writer = await self._stack.enter_async_context(transport_ctx)
                    print("DEBUG: STDIO transport context entered.")

                else: # Assume launch for SSE connection (default or transport: sse)
                    # --- Launch command, capture stdout for URL, connect via SSE ---
                    print("DEBUG: Assuming launch for SSE connection (capturing stdout for URL).")
                    merged_env = os.environ.copy()
                    if connection_config.env: merged_env.update(connection_config.env)

                    # Launch subprocess
                    print(f"DEBUG: Executing command: {connection_config.command} {' '.join(connection_config.args)}")
                    self._server_process = await asyncio.create_subprocess_exec(
                        connection_config.command,
                        *connection_config.args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE, # Capture stderr too
                        env=merged_env,
                        cwd=connection_config.cwd
                    )
                    print(f"DEBUG: Subprocess launched (PID: {self._server_process.pid}). Waiting for URL...")

                    # Add process termination to the exit stack
                    async def cleanup_process(proc):
                         if proc and proc.returncode is None:
                              print(f"DEBUG: Terminating server process (PID: {proc.pid})...")
                              try: proc.terminate()
                              except ProcessLookupError: pass # Already exited
                              try: await asyncio.wait_for(proc.wait(), timeout=5.0)
                              except asyncio.TimeoutError:
                                   print(f"WARNING: Server process {proc.pid} did not terminate gracefully, killing.")
                                   try: proc.kill()
                                   except ProcessLookupError: pass
                                   await proc.wait() # Wait after kill
                              print(f"DEBUG: Server process {proc.pid} terminated.")

                    await self._stack.push_async_callback(cleanup_process, self._server_process)

                    # Read stdout/stderr to find URL
                    found_url = None
                    url_pattern = re.compile(r"(https?://[^\s\"'>]+)") # Regex to find URLs
                    stderr_lines = [] # Collect stderr

                    try:
                        async with asyncio.timeout(connection_config.timeout):
                             while True:
                                 if self._server_process.stdout is None: break # Should not happen with PIPE
                                 try:
                                     # Read both stdout and stderr concurrently
                                     stdout_task = asyncio.create_task(self._server_process.stdout.readline())
                                     stderr_task = asyncio.create_task(self._server_process.stderr.readline())
                                     done, pending = await asyncio.wait(
                                         [stdout_task, stderr_task],
                                         return_when=asyncio.FIRST_COMPLETED
                                     )
                                     # Cancel pending tasks if any
                                     for task in pending: task.cancel()

                                     stdout_line = ""
                                     stderr_line = ""

                                     for task in done:
                                         if task == stdout_task and not task.cancelled() and task.result():
                                             stdout_line = task.result().decode(errors='ignore').strip()
                                         elif task == stderr_task and not task.cancelled() and task.result():
                                             stderr_line = task.result().decode(errors='ignore').strip()

                                     if stdout_line:
                                          print(f"Server Stdout: {stdout_line}")
                                          match = url_pattern.search(stdout_line)
                                          # Check for common listening messages
                                          if match and ("listening on" in stdout_line.lower() or "running on" in stdout_line.lower()):
                                               found_url = match.group(0)
                                               # Ensure trailing slash for SSE path (or adjust regex)
                                               # Assuming server prints http://host:port and client adds /sse
                                               # Or check if server prints full /sse path
                                               if "/sse" not in found_url: # Basic check, might need adjustment
                                                    print(f"WARNING: Found URL '{found_url}' might miss /sse path, check server output.")
                                               print(f"DEBUG: Found potential SSE URL: {found_url}")
                                               break # Found the URL

                                     if stderr_line:
                                          print(f"Server Stderr: {stderr_line}", file=sys.stderr)
                                          stderr_lines.append(stderr_line)

                                     # Check if process exited while waiting
                                     if self._server_process.returncode is not None:
                                         print(f"ERROR: Server process exited prematurely (code: {self._server_process.returncode}) while waiting for URL.")
                                         break

                                     if not stdout_line and not stderr_line: # EOF on both
                                          print("ERROR: Server process EOF reached before URL was found.")
                                          break

                                 except asyncio.CancelledError:
                                     print("DEBUG: URL detection cancelled.")
                                     break
                                 except Exception as read_err:
                                      print(f"ERROR reading server output: {read_err}")
                                      break # Exit loop on read error

                    except asyncio.TimeoutError:
                        print(f"ERROR: Timed out after {connection_config.timeout}s waiting for server URL.")
                        # Attempt to read remaining stderr
                        if self._server_process and self._server_process.stderr:
                             try:
                                  stderr_remaining = await asyncio.wait_for(self._server_process.stderr.read(), timeout=1.0)
                                  if stderr_remaining: stderr_lines.append(stderr_remaining.decode(errors='ignore'))
                             except: pass
                        raise TimeoutError(f"Server did not output listening URL within {connection_config.timeout}s. Stderr: {' '.join(stderr_lines)}")

                    if not found_url:
                         # Raise error including stderr if URL not found
                         raise ConnectionError(f"Could not find listening URL in server output. Stderr: {' '.join(stderr_lines)}")

                    # Add /sse if typically needed and not present
                    sse_connect_url = found_url
                    if "/sse" not in sse_connect_url.split('/')[-1]: # Simple check
                        sse_connect_url = sse_connect_url.rstrip('/') + "/sse"
                        print(f"DEBUG: Appending /sse, connecting to: {sse_connect_url}")

                    # Connect via SSE using the found URL
                    transport_ctx = sse_client(sse_connect_url) # Use default timeouts for SSE client
                    self._transport_ctx = transport_ctx
                    reader, writer = await self._stack.enter_async_context(transport_ctx)
                    print(f"DEBUG: SSE transport context entered using captured URL.")

            else:
                raise ValueError("Invalid configuration: must have 'url' or 'command'.")


            # --- Establish ClientSession (Common for all connection types) ---
            session_kwargs = getattr(connection_config, 'session_kwargs', None) or {}
            session_ctx = ClientSession(reader, writer, **session_kwargs)
            self.session = await self._stack.enter_async_context(session_ctx)
            print("DEBUG: ClientSession context entered.")

            # --- Initialize and Load Tools (Common) ---
            print("Initializing MCP session...")
            await asyncio.wait_for(self.session.initialize(), timeout=30.0) # Timeout for init
            print("MCP session initialized.")

            if LOAD_MCP_TOOLS_AVAILABLE:
                print("Loading MCP tools (via langchain-mcp-adapters)...")
                loaded_tools = await load_mcp_tools(self.session)
                print(f"Successfully loaded {len(loaded_tools)} tool descriptions from server.")
                print("--- Loaded Tools & Args Schema (Diagnostic) ---")
                self.tools = []
                for i, tool in enumerate(loaded_tools):
                     schema = getattr(tool, 'args_schema', 'N/A'); tool_name = getattr(tool, 'name', f'Tool_{i+1}')
                     print(f"{i+1}. Tool Name: {tool_name}")
                     schema_detail = "N/A"
                     if schema != 'N/A': # Schema printing logic...
                          if isinstance(schema, type) and issubclass(schema, BaseModelV1):
                               try: schema_detail = f"(PydanticV1): {json.dumps(schema.schema(), indent=2)}"
                               except Exception as e_schema: schema_detail = f"(PydanticV1): Error - {e_schema}"
                          elif hasattr(schema, 'model_json_schema'):
                               try: schema_detail = f"(PydanticV2): {json.dumps(schema.model_json_schema(), indent=2)}"
                               except Exception as e_schema: schema_detail = f"(PydanticV2): Error - {e_schema}"
                          else: schema_detail = f"(Unknown Type): {schema}"
                     print(f"   Args Schema: {schema_detail}")
                     print("-" * 15); self.tools.append(tool)
                print("-------------------------------------------")
            else: print("Warning: load_mcp_tools unavailable."); self.tools = []

            print(f"MCPClient ready. Loaded {len(self.tools)} tools via adapter.")
            return self # Return self for 'as client'

        except Exception as enter_err:
            print(f"ERROR: Failed during MCPClient __aenter__: {enter_err}")
            # Ensure stack is cleaned up even if __aenter__ fails midway
            await self.close() # close() now handles the stack
            raise # Re-raise the error

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]):
        """Closes connections using AsyncExitStack."""
        print("DEBUG: MCPClient exiting context...")
        await self.close() # Delegate cleanup to close method
        print("DEBUG: MCPClient context exited.")

    async def close(self):
        """Closes connections and resets state."""
        print("Closing MCP Client...")
        if hasattr(self, '_stack') and self._stack: # Check if stack exists
            print("  Closing managed async contexts via AsyncExitStack...")
            try:
                await self._stack.aclose()
                print("  AsyncExitStack closed successfully.")
            except Exception as e:
                # Log errors during cleanup but don't prevent reset
                print(f"WARNING: Error during AsyncExitStack cleanup: {type(e).__name__}: {e}")
                # Optionally print traceback for debugging cleanup errors
                # traceback.print_exc()
            finally:
                 self._stack = None # Reset stack after attempting close
        else:
             print("  No active AsyncExitStack to close.")
        # Reset state variables
        self.session = None; self.tools = []; self._transport_ctx = None; self._server_process = None
        print("MCP Client state reset.")

    def get_tools(self) -> List[BaseTool]:
        """Returns the list of tools loaded by load_mcp_tools."""
        # This returns the potentially problematic tools from the adapter
        return self.tools

    # --- Method for Manual Tool Creation ---
    async def create_manual_tool(self,
                                tool_name: str,
                                tool_description: str,
                                args_schema: Type[BaseModelV1]
                                ) -> Optional[Tool]:
        """Helper to manually create a LangChain Tool object for an MCP tool."""
        print(f"  Manually creating Tool object for '{tool_name}'...")
        if not CALL_TOOL_REQ_AVAILABLE: print("   ERROR: CallToolRequest not imported!"); return None
        if not self.session: print("   ERROR: MCP session not active!"); return None

        # Keep session reference for the wrapper
        current_session = self.session

        async def call_mcp_tool_wrapper(**kwargs) -> str:
            """Inner coroutine to call MCP tool via current session."""
            if not current_session: return "ERROR: MCP session missing in wrapper."
            try:
                 print(f"    [Manual Wrapper] Sending CallToolRequest: name='{tool_name}', args={kwargs}")
                 request_params = {"name": tool_name, "arguments": kwargs}
                 request = CallToolRequest(method='tools/call', params=request_params)
                 result_message = await asyncio.wait_for(current_session.call_tool(request), timeout=120.0)
                 if hasattr(result_message, 'result'):
                      res_val = result_message.result; print(f"    [Manual Wrapper] Success, result snippet: {str(res_val)[:200]}...")
                      return str(res_val) if not isinstance(res_val, str) else res_val
                 elif hasattr(result_message, 'error'):
                      err_msg = result_message.error.message; print(f"    [Manual Wrapper] MCP Error: {err_msg}")
                      return f"Tool Error: {err_msg}"
                 else: return "Unknown MCP response."
            except asyncio.TimeoutError: print(f"    [Manual Wrapper] Timeout ({tool_name})"); return "Error: Timeout."
            except Exception as e: print(f"    [Manual Wrapper] Error ({tool_name}): {e}"); print(traceback.format_exc()); return f"Error: {e}\n{traceback.format_exc()}"

        try:
            manual_tool = Tool.from_function(
                func=None, coroutine=call_mcp_tool_wrapper, name=tool_name,
                description=tool_description, args_schema=args_schema
            )
            print(f"  Manual Tool '{tool_name}' created successfully.")
            return manual_tool
        except Exception as e_create: print(f"  ERROR: Failed to create manual Tool '{tool_name}': {e_create}"); return None