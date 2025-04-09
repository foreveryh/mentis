import os
import sys
import argparse
import traceback
import logging
from typing import List, Optional # Type hint Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_server")

current_dir = os.path.dirname(os.path.abspath(__file__)); project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir))); sys.path.insert(0, project_root)

from core.mcp.server import MentisMCPServer # 使用修正后的 server
try:
    from core.tools import preregister_core_tools
    PREREGISTER_AVAILABLE = True
except ImportError:
    print("WARNING: preregister_core_tools not found, skipping pre-registration.")
    def preregister_core_tools(): pass
    PREREGISTER_AVAILABLE = False
# 可能不再需要导入 BaseTool 等
# from langchain_core.tools import BaseTool

print("--- DEBUG: Loading run_server.py (Fix AttributeError + Optional Preregister) ---")

def register_tools(server: MentisMCPServer, tool_names: Optional[List[str]] = None): # Type hint Optional
    """向服务器注册工具 (调用 server 的方法)"""
    print("--- DEBUG: Running register_tools() in run_server.py ---")
    try:
        if tool_names:
            print(f"Attempting to register specific tools: {tool_names}")
            for tool_name in tool_names:
                try: server.register_single_tool(tool_name)
                except Exception as e_single: print(f"ERROR during register_single_tool for '{tool_name}': {e_single}")
        else:
            print("Attempting to register all tools...")
            server.register_all_tools()

        # --- FIX: 使用正确的属性名 registered_tools_wrappers ---
        final_tool_count = len(server.registered_tools_wrappers) # 使用 _wrappers
        print(f"MCP 工具注册过程结束，最终尝试注册了 {final_tool_count} 个工具:")
        if final_tool_count > 0:
             for name in server.registered_tools_wrappers: # 使用 _wrappers
                 print(f" - {name}")
        # --- End Fix ---
        else: print("  (没有工具包装器被成功注册)") # 修改提示信息
    except Exception as e: print(f"ERROR during register_tools function: {e}"); traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description='Start Mentis MCP Server (Refactored)')
    # 参数定义保持不变
    parser.add_argument('--transport', type=str, choices=['stdio', 'sse'], default='stdio'); parser.add_argument('--host', type=str, default='0.0.0.0'); parser.add_argument('--port', type=int, default=8000); parser.add_argument('--name', type=str, default='MentisMCP'); parser.add_argument('--tools', nargs='+'); parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    if args.debug: logger.setLevel(logging.DEBUG); print("DEBUG Logging Enabled")

    try:
        # --- OPTIMIZATION: 仅在加载所有工具时才执行预注册 ---
        if not args.tools and PREREGISTER_AVAILABLE:
             print("DEBUG: No specific tools requested, calling preregister_core_tools...")
             preregister_core_tools() # 预注册所有核心工具
             print("DEBUG: preregister_core_tools finished.")
        elif args.tools:
             print(f"DEBUG: Specific tools requested ({args.tools}), skipping general preregister_core_tools.")
             # 注意：如果 preregister_core_tools 是【唯一】注册工具的地方，
             # 那么当使用 --tools 时，需要确保 get_tool_instance 能找到这些工具
             # 可能需要调整 core/tools/__init__.py 的逻辑，确保核心工具总是被加载到 registry
             # 或者让 preregister_core_tools 只加载【不】注册？这是一个设计选择。
             # 暂时保持现有逻辑：即使用 --tools 时不调用 preregister_core_tools。
        else: # No --tools and preregister unavailable
             print("DEBUG: Skipping preregister_core_tools (unavailable or --tools used).")
        # ---

        print(f"创建 MCP 服务器: {args.name}")
        server = MentisMCPServer(name=args.name, host=args.host if args.transport == 'sse' else None, port=args.port if args.transport == 'sse' else None)

        # 注册工具 (根据 --tools 参数或注册所有)
        # 这一步会调用 server 内部的方法，该方法内部会处理注册
        register_tools(server, args.tools)

        # 检查是否真的有工具被注册成功了
        if len(server.registered_tools_wrappers) == 0:
             print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
             print("!!! WARNING: No tools were successfully registered!    !!!")
             print("!!! Server might start but will have no capabilities.  !!!")
             print("!!! Check previous logs for registration errors.       !!!")
             print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
             # Consider exiting if no tools are essential? sys.exit(1)

        print(f"启动 MCP 服务器，传输方式: {args.transport}...")
        server.run(transport=args.transport) # 调用 server.run

    except KeyboardInterrupt: print("Server shutting down..."); sys.exit(0)
    except Exception as e: print(f"Error starting server: {e}"); traceback.print_exc(); sys.exit(1)

if __name__ == "__main__":
    main()