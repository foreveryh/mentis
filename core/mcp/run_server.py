# core/mcp/run_server.py

import os
import sys
import argparse
import traceback
import logging
from typing import List

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_server")

# 添加项目根目录到路径，以便导入项目模块
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.insert(0, project_root)

from core.mcp.server import MentisMCPServer
from core.tools.registry import get_registered_tools, get_tool_instance, register_tool, ToolCategory
from core.tools.e2b_tool import E2BCodeInterpreterTool

def preregister_core_tools():
    """预注册核心工具到注册表"""
    print("开始预注册核心工具...")
    try:
        # 尝试导入和注册 E2B Code Interpreter
        e2b_tool = E2BCodeInterpreterTool()
        register_tool(e2b_tool, ToolCategory.CODE_INTERPRETER)
        print(f"已预注册工具: {e2b_tool.name} (类别: {ToolCategory.CODE_INTERPRETER.value})")
            
    except Exception as e:
        print(f"预注册核心工具时出错: {e}")
        print(traceback.format_exc())

def register_tools(server: MentisMCPServer, tool_names: List[str] = None):
    """
    向服务器注册工具
    
    Args:
        server: MCP 服务器实例
        tool_names: 要注册的工具名称列表，如果为 None，则注册所有工具
    """
    try:
        if tool_names:
            # 注册指定的工具
            for tool_name in tool_names:
                try:
                    server.register_single_tool(tool_name)
                    print(f"已注册工具: {tool_name}")
                except ValueError as e:
                    print(f"注册工具 {tool_name} 时出错: {e}")
        else:
            # 注册所有工具
            server.register_all_tools()
            print("已注册所有工具")
            
        # 显示已注册工具
        print(f"MCP 工具注册完成，共 {len(server.registered_tools)} 个工具:")
        for name in server.registered_tools:
            print(f" - {name}")
    except Exception as e:
        print(f"注册工具时出错: {e}")
        print(traceback.format_exc())

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Start Mentis MCP Server')
    parser.add_argument('--transport', type=str, choices=['stdio', 'sse'], default='stdio',
                        help='Transport type (stdio or sse)')
    parser.add_argument('--host', type=str, default='0.0.0.0',  # 默认改为 0.0.0.0
                        help='Host for SSE server (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8000,
                        help='Port for SSE server (default: 8000)')
    parser.add_argument('--name', type=str, default='MentisMCP',
                        help='MCP server name (default: MentisMCP)')
    parser.add_argument('--tools', nargs='+', help='Specific tools to register (space separated)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.debug:
        logger.setLevel(logging.DEBUG)
        print("DEBUG 日志已启用")
    
    # 创建并初始化服务器
    try:
        # 预注册核心工具
        preregister_core_tools()
        
        # 创建 MCP 服务器
        print(f"创建 MCP 服务器: {args.name}")
        server = MentisMCPServer(
            name=args.name,
            host=args.host if args.transport == 'sse' else None, # Pass only for sse
            port=args.port if args.transport == 'sse' else None  # Pass only for sse
        )
        
        # 注册工具
        register_tools(server, args.tools)
        
        # 启动服务器
        print(f"启动 MCP 服务器，传输方式: {args.transport}...")
        if args.transport == 'sse':
            print(f"服务器将监听: http://{args.host}:{args.port}/sse")
            # 确保服务器监听的是 0.0.0.0
            server.run(transport=args.transport)
        else:
            print("启动 stdio 模式服务器")
            server.run(transport=args.transport)
    except KeyboardInterrupt:
        print("收到中断信号，服务器正在关闭...")
        sys.exit(0)
    except Exception as e:
        print(f"启动 MCP 服务器时出错: {e}")
        print(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()