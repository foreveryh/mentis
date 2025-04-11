import asyncio
from mcp.server.fastmcp import FastMCP
import logging

# 配置基本日志，看FastMCP内部是否有更多信息
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minimal_test")

print("--- Minimal FastMCP Server Test ---")

# 1. 创建 FastMCP 实例
# (假设 FastMCP 对于 stdio 不需要 host/port in __init__)
mcp_server = FastMCP(name="MinimalServer")
print("FastMCP instance created.")

# 2. 定义一个简单的 async 工具函数
async def ping_tool(query: str = "default ping") -> str:
    """A very basic tool that just returns pong."""
    print(f"\n--- PING TOOL CALLED! ---") # 在工具内部打印日志
    print(f"Received query: {query}")
    result = f"pong: {query}"
    print(f"Returning: {result}")
    print(f"--- PING TOOL END ---")
    return result

# 3. 直接用 FastMCP 实例的装饰器注册
try:
    mcp_server.tool(name="ping", description="Returns pong plus the query.")(ping_tool)
    # 上一行等价于:
    # @mcp_server.tool(name="ping", description="Returns pong plus the query.")
    # async def ping_tool(...) ...
    print("Tool 'ping' registered directly with FastMCP.")
except Exception as e_reg:
    print(f"Error registering tool directly: {e_reg}")
    import traceback
    traceback.print_exc()
    exit(1)

# 4. 运行服务器 (使用 STDIO)
try:
    print("Starting minimal server with STDIO transport...")
    # 假设 run() 只需 transport 参数对 stdio 有效
    mcp_server.run(transport="stdio")
    print("Server finished.") # 理应不会执行到，除非服务器停止
except Exception as e_run:
    print(f"Error running minimal server: {e_run}")
    import traceback
    traceback.print_exc()
    exit(1)