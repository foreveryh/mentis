from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, Optional, List # 确保导入 List
import os
import sys
import traceback
import asyncio
import time # 用于日志时间戳
import json # 用于序列化检查

# 导入工具注册表
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.tools.registry import get_registered_tools, get_tool_instance
from langchain_core.tools import BaseTool

print("--- DEBUG: Loading FINAL REFACTORED server.py ---")

class MentisMCPServer:
    """
    Mentis MCP 服务器 (最终优化版)
    将现有工具转换为 MCP 工具，采用简化的包装器逻辑
    """

    def __init__(self, name: str = "MentisMCP", host: Optional[str] = None, port: Optional[int] = None):
        """初始化 Mentis MCP 服务器"""
        print(f"DEBUG: Initializing MentisMCPServer(name='{name}', host={host}, port={port})")
        fastmcp_kwargs = {}
        if host is not None: fastmcp_kwargs['host'] = host
        if port is not None: fastmcp_kwargs['port'] = port
        try:
            print(f"DEBUG: Calling FastMCP(name='{name}', **{fastmcp_kwargs})")
            self.mcp = FastMCP(name, **fastmcp_kwargs)
            print("DEBUG: FastMCP initialized successfully.")
        except Exception as e_fastmcp:
            print(f"ERROR: Failed to initialize FastMCP!")
            print(traceback.format_exc())
            raise
        # 保留用于调试
        self.registered_tools_wrappers = {}

    def register_all_tools(self):
        """将所有注册的工具转换为 MCP 工具"""
        tools_dict = get_registered_tools(as_dict=True)
        print(f"DEBUG: Registering all tools ({len(tools_dict)} found)...")
        registered_count = 0
        for tool_name, tool_info in tools_dict.items():
            tool_instance = tool_info.get("tool")
            if isinstance(tool_instance, BaseTool):
                if self._register_tool_with_simplified_wrapper(tool_instance):
                    registered_count += 1
            else:
                 print(f"WARNING: Item '{tool_name}' in registry is not a BaseTool instance, skipping.")
        print(f"DEBUG: Finished registering all tools. Successfully registered: {registered_count}")

    def register_single_tool(self, tool_name: str):
        """将单个工具转换为 MCP 工具"""
        print(f"DEBUG: Attempting to register single tool: {tool_name}")
        try:
            tool_instance = get_tool_instance(tool_name)
            if not tool_instance:
                # 不抛出异常，仅打印错误，允许服务器继续启动（可能加载其他工具）
                print(f"ERROR: Tool '{tool_name}' not found in registry during single registration.")
                # raise ValueError(f"Tool {tool_name} not found in registry") # 原代码
                return # 找不到就算了

            if isinstance(tool_instance, BaseTool):
                if self._register_tool_with_simplified_wrapper(tool_instance):
                     print(f"DEBUG: Successfully registered single tool: {tool_instance.name}")
                else:
                     print(f"ERROR: Failed to register wrapper for single tool: {tool_instance.name}")

            else:
                print(f"WARNING: Tool '{tool_name}' from registry is not a BaseTool instance, skipping.")
        except Exception as e:
            print(f"ERROR during register_single_tool for '{tool_name}': {e}")
            print(traceback.format_exc())


    def _register_tool_with_simplified_wrapper(self, tool: BaseTool) -> bool:
        """为单个工具创建并注册一个简化的 MCP 包装函数。返回是否注册成功。"""
        try:
            tool_name = tool.name
            tool_description = tool.description

            # 检查名称和描述是否有效
            if not tool_name or not isinstance(tool_name, str):
                 print(f"ERROR: Tool has invalid name: {tool_name}. Skipping registration.")
                 return False
            if not tool_description or not isinstance(tool_description, str):
                 print(f"WARNING: Tool '{tool_name}' has empty or invalid description.")
                 tool_description = tool_description or f"Tool named {tool_name}" # Provide default

            print(f"DEBUG: Creating simplified wrapper for tool: '{tool_name}'")

            @self.mcp.tool(name=tool_name, description=tool_description)
            async def simplified_tool_wrapper(**kwargs):
                log_file = "/tmp/mcp_wrapper.log"
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                log_prefix = f"--- {timestamp} WRAPPER for '{tool_name}' ---"
                # 使用列表存储日志行，方便最后写入
                log_lines = [f"{log_prefix} START", f"Received kwargs: {kwargs}"]

                try:
                    result = None
                    if hasattr(tool, '_arun'):
                        log_lines.append(f"Calling await tool._arun(**kwargs)")
                        result = await tool._arun(**kwargs)
                        log_lines.append(f"Await _arun completed.")
                    elif hasattr(tool, '_run'):
                        log_lines.append(f"Calling tool._run(**kwargs) via run_in_executor")
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(None, lambda: tool._run(**kwargs))
                        log_lines.append(f"Executor _run completed.")
                    else:
                        log_lines.append("ERROR: Tool has neither _arun nor _run method!")
                        raise NotImplementedError(f"Tool {tool_name} has no _arun or _run method.")

                    log_lines.append(f"Raw result type: {type(result)}")
                    log_lines.append(f"Raw result value (snippet): {str(result)[:500]}...") # Log more snippet

                    final_result = result
                    try:
                         json.dumps(result)
                         log_lines.append("Result IS JSON serializable.")
                    except TypeError:
                         log_lines.append(f"WARNING: Result type {type(result)} is not JSON serializable. Converting to string.")
                         final_result = str(result)

                    log_lines.append(f"Returning final result (type {type(final_result)}).")
                    log_lines.append(f"{log_prefix} END (Success)")
                    return final_result

                except Exception as e:
                    log_lines.append(f"!!! EXCEPTION during tool execution: {e} !!!")
                    tb_lines = traceback.format_exc().splitlines()
                    log_lines.append("--- Traceback ---")
                    log_lines.extend(tb_lines)
                    log_lines.append("-----------------")
                    log_lines.append(f"{log_prefix} END (Exception)")
                    # 返回明确的错误信息
                    return f"ERROR_EXECUTING_TOOL_{tool_name}: {str(e)}"

                finally:
                    # 确保日志被写入或打印
                    try:
                        # 打印到 stderr 并强制刷新
                        for line in log_lines:
                             print(line, flush=True, file=sys.stderr)
                        # 尝试写入文件
                        with open(log_file, "a") as f:
                             f.write("\n".join(log_lines) + "\n\n") # Add separator
                    except Exception as log_e:
                        print(f"!!! Logging Error for tool {tool_name}: {log_e} !!!", flush=True, file=sys.stderr)

            simplified_tool_wrapper.__name__ = f"{tool_name}_simplified_wrapper"
            self.registered_tools_wrappers[tool_name] = simplified_tool_wrapper
            print(f"DEBUG: Registered simplified wrapper for tool: '{tool_name}'")
            return True # 注册成功

        except Exception as registration_error:
             print(f"ERROR: Failed to create/register wrapper for tool instance {tool}: {registration_error}")
             print(traceback.format_exc())
             return False # 注册失败

    # 移除 run 方法签名中未使用的 host/port
    def run(self, transport: str = "stdio"):
        """运行 MCP 服务器"""
        print(f"DEBUG: MentisMCPServer.run(transport='{transport}') called.")
        print(f"正在启动 MCP 服务器，传输方式: {transport}")
        if transport == "sse":
            # 打印信息基于 FastMCP 实例的配置 (如果能获取到)
            host = getattr(self.mcp, 'host', 'N/A') # 尝试获取
            port = getattr(self.mcp, 'port', 'N/A') # 尝试获取
            print(f"配置 SSE 服务器监听在: http://{host}:{port} (如果 N/A 表示 FastMCP 未暴露)")
            try:
                import importlib
                try:
                    fastmcp_module = importlib.import_module('mcp.server.fastmcp')
                    print(f"已加载 FastMCP 模块，版本: {getattr(fastmcp_module, '__version__', '未知')}")
                except: pass
                import uvicorn, fastapi
                print(f"FastAPI version: {fastapi.__version__}, Uvicorn version: {uvicorn.__version__}")
                print(f"DEBUG: Calling self.mcp.run(transport='{transport}') for SSE")
                self.mcp.run(transport=transport)
            except Exception as e:
                print(f"SSE 服务器启动失败: {e}")
                print(traceback.format_exc())
                raise
        else: # stdio
             print(f"启动 stdio 模式服务器...")
             try:
                 print(f"DEBUG: Calling self.mcp.run(transport='{transport}') for STDIO")
                 self.mcp.run(transport=transport)
             except Exception as e:
                 print(f"stdio 服务器启动失败: {e}")
                 print(traceback.format_exc())
                 raise