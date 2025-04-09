from typing import Dict, Any, Optional, List
import os
import sys
import traceback
import asyncio
import time
import json
import functools # 导入 functools
from mcp.server.fastmcp import FastMCP
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.tools.registry import get_registered_tools, get_tool_instance
from langchain_core.tools import BaseTool

print("--- DEBUG: Loading REFACTORED server.py (Fix InvalidSignature) ---")

class MentisMCPServer:
    def __init__(self, name: str = "MentisMCP", host: Optional[str] = None, port: Optional[int] = None):
        print(f"DEBUG: Initializing MentisMCPServer(name='{name}', host={host}, port={port})")
        fastmcp_kwargs = {}
        if host is not None: fastmcp_kwargs['host'] = host
        if port is not None: fastmcp_kwargs['port'] = port
        try:
            print(f"DEBUG: Calling FastMCP(name='{name}', **{fastmcp_kwargs})")
            self.mcp = FastMCP(name, **fastmcp_kwargs)
            print("DEBUG: FastMCP initialized successfully.")
        except Exception as e_fastmcp:
            print(f"ERROR: Failed to initialize FastMCP!"); print(traceback.format_exc()); raise
        # 使用修正后的属性名
        self.registered_tools_wrappers = {}

    def register_all_tools(self):
        tools_dict = get_registered_tools(as_dict=True)
        print(f"DEBUG: Registering all tools ({len(tools_dict)} found)...")
        registered_count = 0
        for tool_name, tool_info in tools_dict.items():
            tool_instance = tool_info.get("tool")
            if isinstance(tool_instance, BaseTool):
                if self._register_tool_with_simplified_wrapper(tool_instance):
                    registered_count += 1
            else: print(f"WARNING: Item '{tool_name}' not BaseTool, skipping.")
        print(f"DEBUG: Finished registering all tools. Registered: {registered_count}")

    def register_single_tool(self, tool_name: str):
        print(f"DEBUG: Attempting to register single tool: {tool_name}")
        try:
            tool_instance = get_tool_instance(tool_name)
            if not tool_instance: print(f"ERROR: Tool '{tool_name}' not found in registry."); return
            if isinstance(tool_instance, BaseTool):
                if self._register_tool_with_simplified_wrapper(tool_instance):
                     print(f"DEBUG: Successfully registered single tool: {tool_instance.name}")
                else: print(f"ERROR: Failed wrapper registration for: {tool_instance.name}")
            else: print(f"WARNING: Tool '{tool_name}' not BaseTool, skipping.")
        except Exception as e: print(f"ERROR during register_single_tool for '{tool_name}': {e}"); print(traceback.format_exc())

    def _register_tool_with_simplified_wrapper(self, tool: BaseTool) -> bool:
        """(Fix InvalidSignature) 为工具创建并注册包装器"""
        try:
            tool_name = getattr(tool, 'name', None)
            tool_description = getattr(tool, 'description', None)
            if not tool_name or not isinstance(tool_name, str): print(f"ERROR: Invalid tool name: {tool_name}. Skip."); return False
            if not tool_description or not isinstance(tool_description, str): print(f"WARNING: Empty/invalid description for '{tool_name}'."); tool_description = f"Tool {tool_name}"

            print(f"DEBUG: Defining wrapper for tool: '{tool_name}'")

            # --- FIX: Rename parameter from _tool_instance to tool_for_wrapper ---
            @self.mcp.tool(name=tool_name, description=tool_description)
            async def simplified_tool_wrapper(tool_for_wrapper=tool, **kwargs): # 使用不允许下划线开头的参数名
                # --- 使用 tool_for_wrapper ---
                _tool_name = tool_for_wrapper.name # 从绑定的实例获取名字
                log_file = "/tmp/mcp_wrapper.log"; timestamp = time.strftime("%Y-%m-%d %H:%M:%S"); log_prefix = f"--- {timestamp} WRAPPER for '{_tool_name}' ---"
                log_lines = [f"{log_prefix} START", f"Received kwargs: {kwargs}"]
                try: # 主执行逻辑
                    result = None
                    if hasattr(tool_for_wrapper, '_arun'): # 使用 tool_for_wrapper
                        log_lines.append(f"Calling await tool_for_wrapper._arun(**kwargs)")
                        result = await tool_for_wrapper._arun(**kwargs)
                        log_lines.append(f"Await _arun completed.")
                    elif hasattr(tool_for_wrapper, '_run'): # 使用 tool_for_wrapper
                        log_lines.append(f"Calling tool_for_wrapper._run(**kwargs) via run_in_executor")
                        loop = asyncio.get_running_loop()
                        sync_func_with_args = functools.partial(tool_for_wrapper._run, **kwargs)
                        result = await loop.run_in_executor(None, sync_func_with_args)
                        log_lines.append(f"Executor _run completed.")
                    else: log_lines.append("ERROR: Tool no _arun/_run!"); raise NotImplementedError(f"{_tool_name} no method.")
                    log_lines.append(f"Raw result type: {type(result)}"); log_lines.append(f"Raw value snippet: {str(result)[:500]}...")
                    final_result = result
                    try: json.dumps(result); log_lines.append("Result JSON serializable.")
                    except TypeError: log_lines.append(f"WARN: Non-JSON type {type(result)}.->str."); final_result = str(result)
                    log_lines.append(f"Returning final (type {type(final_result)})."); log_lines.append(f"{log_prefix} END (Success)")
                    return final_result
                except Exception as e: # 捕获工具执行异常
                    log_lines.append(f"!!! EXCEPTION in tool exec for '{_tool_name}': {e} !!!"); tb_lines = traceback.format_exc().splitlines(); log_lines.append("--- Traceback ---"); log_lines.extend(tb_lines); log_lines.append("-----------------"); log_lines.append(f"{log_prefix} END (Exception)")
                    return f"ERROR_EXECUTING_TOOL_{_tool_name}: {str(e)}"
                finally: # 确保日志记录
                    try:
                        for line in log_lines: print(line, flush=True, file=sys.stderr)
                        with open(log_file, "a") as f: f.write("\n".join(log_lines) + "\n\n")
                    except Exception as log_e: print(f"!!! Logging Error for '{_tool_name}': {log_e} !!!", flush=True, file=sys.stderr)

            simplified_tool_wrapper.__name__ = f"{tool_name}_simplified_wrapper"
            # 使用修正后的属性名
            self.registered_tools_wrappers[tool_name] = simplified_tool_wrapper
            print(f"DEBUG: Registered simplified wrapper for tool: '{tool_name}'")
            return True # 注册成功
        except Exception as registration_error:
             failed_tool_name = getattr(tool, 'name', 'unknown')
             print(f"ERROR: Failed to create/register wrapper for tool '{failed_tool_name}': {registration_error}")
             print(traceback.format_exc())
             return False # 注册失败

    def run(self, transport: str = "stdio"):
        """运行 MCP 服务器 (签名中移除了 host/port)"""
        print(f"DEBUG: MentisMCPServer.run(transport='{transport}') called.")
        print(f"正在启动 MCP 服务器，传输方式: {transport}")
        if transport == "sse":
            host = 'N/A'; port = 'N/A'
            if hasattr(self.mcp, 'settings'): host = getattr(self.mcp.settings, 'host', 'N/A'); port = getattr(self.mcp.settings, 'port', 'N/A')
            print(f"配置 SSE 服务器监听在: http://{host}:{port} (如果 N/A 表示未配置或获取失败)")
            try:
                import importlib
                try: fastmcp_module = importlib.import_module('mcp.server.fastmcp'); print(f"FastMCP version: {getattr(fastmcp_module, '__version__', '未知')}")
                except: pass
                import uvicorn, fastapi; print(f"FastAPI: {fastapi.__version__}, Uvicorn: {uvicorn.__version__}")
                print(f"DEBUG: Calling self.mcp.run(transport='{transport}') for SSE")
                self.mcp.run(transport=transport)
            except Exception as e: print(f"SSE 服务器启动失败: {e}"); print(traceback.format_exc()); raise
        else: # stdio
             print(f"启动 stdio 模式服务器...")
             try:
                 print(f"DEBUG: Calling self.mcp.run(transport='{transport}') for STDIO")
                 self.mcp.run(transport=transport)
             except Exception as e: print(f"stdio 服务器启动失败: {e}"); print(traceback.format_exc()); raise