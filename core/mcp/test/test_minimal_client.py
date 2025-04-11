# test_minimal_client_fixed.py - 用于测试minimal_fastmcp_test.py的客户端脚本（修复版）
import os
import sys
import asyncio
import json
import traceback
from typing import Optional, Dict, Any

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入必要的MCP客户端库
try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.types import CallToolRequest
    DEPS_OK = True
except ImportError as e:
    print(f"错误: 缺少必要的依赖: {e}")
    print("请确保已安装mcp库: pip install mcp")
    DEPS_OK = False

async def main():
    """连接到minimal_fastmcp_test.py并测试ping工具"""
    print("=== MCP最小客户端测试（修复版）===\n")
    
    if not DEPS_OK:
        print("缺少必要的依赖，无法继续。")
        return
    
    # 准备minimal_fastmcp_test.py的路径
    script_path = os.path.join(os.path.dirname(__file__), "minimal_fastmcp_test.py")
    cmd = [sys.executable, script_path]
    print(f"准备连接到服务器: {script_path}")
    
    try:
        # 创建StdioServerParameters对象
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[script_path],
            # 可以根据需要添加其他参数，如env, cwd等
        )
        print("已创建服务器参数配置。")
        
        # 创建STDIO客户端连接
        print("\n创建STDIO客户端连接...")
        async with stdio_client(server_params) as (reader, writer):
            print("STDIO连接已建立。创建ClientSession...")
            async with ClientSession(reader, writer) as session:
                print("ClientSession已创建。初始化会话...")
                await session.initialize()
                print("会话已初始化。")
                
                # 获取服务器支持的工具列表
                print("\n获取服务器支持的工具列表...")
                tools_result = await session.list_tools()
                print(f"服务器支持的工具: {tools_result}")
                
                # 调用ping工具
                print("\n调用ping工具...")
                ping_request = CallToolRequest(
                    method="tools/call",
                    params={
                        "name": "ping",
                        "arguments": {"query": "Hello, MCP!"}
                    }
                )
                
                try:
                    print(f"发送请求: {ping_request}")
                    result = await session.call_tool("ping", {"query": "Hello, MCP!"})
                    print(f"\n收到响应: {result}")
                    if hasattr(result, 'result'):
                        print(f"结果: {result.result}")
                    elif hasattr(result, 'error'):
                        print(f"错误: {result.error}")
                    else:
                        print(f"未知响应格式: {result}")
                except Exception as e:
                    print(f"调用工具时出错: {e}")
                    print(traceback.format_exc())
    
    except Exception as e:
        print(f"运行测试时出错: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())