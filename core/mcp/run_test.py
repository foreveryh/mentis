# examples/14_mcp_integration_test.py
import os
import sys
import asyncio
import subprocess
import time
from dotenv import load_dotenv
import traceback # 确保导入 traceback
from typing import List, Dict, Any # 确保导入

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from langchain_openai import ChatOpenAI # 或其他 LLM
from langgraph.prebuilt import create_react_agent
from core.mcp.client import MentisMCPClient # 使用这个客户端
from core.llm.llm_manager import LLMManager
# 可能还需要导入 BaseTool 如果 get_tools 类型提示需要
from langchain_core.tools import BaseTool


# --- 指定 Minimal Server 脚本路径 ---
# 假设 minimal_fastmcp_test.py 在 mentis 项目根目录
# 如果你保存在其他地方，请修改此路径
MINIMAL_SERVER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), # 项目根目录
    "mcp/minimal_fastmcp_test.py"
)
# ---

llm_manager = LLMManager()

# 保留其他测试函数定义，但 main 只调用 minimal 测试

# --- 用于 Minimal Server 的新测试函数 ---
async def run_minimal_server_stdio_test():
    """运行 Minimal FastMCP Server 测试 (STDIO)"""
    print("\n=== 运行 Minimal FastMCP Server 测试 (STDIO) ===")

    # 初始化 LLM
    try:
        # 使用一个快速或免费的模型进行测试
        model = llm_manager.get_model("deepseek_v3")
    except ValueError as e:
        print(f"获取 LLM 时出错: {e}. 请确保 LLM 配置正确。")
        return

    client = None
    try:
        # 检查 minimal server 脚本是否存在
        if not os.path.exists(MINIMAL_SERVER_SCRIPT):
            print(f"错误：找不到 Minimal Server 脚本: {MINIMAL_SERVER_SCRIPT}")
            print("请确保你已经将 minimal_fastmcp_test.py 保存在项目根目录，或修改脚本中的路径。")
            return

        print(f"尝试连接 Minimal MCP 服务器 (STDIO): {MINIMAL_SERVER_SCRIPT}")
        client = MentisMCPClient()

        # minimal_fastmcp_test.py 不需要额外的命令行参数
        server_args = [MINIMAL_SERVER_SCRIPT]
        print(f"DEBUG: Starting server with command: {sys.executable} {MINIMAL_SERVER_SCRIPT}")

        # 使用 connect_stdio 启动 minimal_fastmcp_test.py
        await client.connect_stdio(
            command=sys.executable,
            args=server_args
        )

        # 获取工具 (应该只包含 'ping')
        # 确保 MentisMCPClient 有 get_tools 方法
        if not hasattr(client, 'get_tools'):
             print("错误: MentisMCPClient 类缺少 get_tools 方法。请添加它。")
             # 临时添加一个简单的实现如果需要继续测试
             # client.tools = await load_mcp_tools(client.session) # 假设 session 可用
             # def get_tools_impl(self) -> List[BaseTool]: return self.tools
             # MentisMCPClient.get_tools = get_tools_impl
             # tools = client.get_tools() # 再次尝试
             return # 或者直接返回，让用户修复 client.py

        tools = client.get_tools()
        print(f"成功加载 {len(tools)} 个工具 (Minimal Mode)")
        if not tools:
            print("警告：没有加载到任何工具！")
            return

        # 验证加载的工具是否正确
        found_ping_tool = False
        expected_tool_name = "ping"
        if len(tools) == 1 and tools[0].name == expected_tool_name:
             found_ping_tool = True
             print(f"成功加载 '{expected_tool_name}': {tools[0].description}")
        else:
             print(f"警告：加载的工具不是预期的 '{expected_tool_name}'。")
             print("加载的工具:", [t.name for t in tools])


        if not found_ping_tool:
             print(f"错误: 未能加载预期的 '{expected_tool_name}' 工具")
             return

        # 创建 Agent
        agent = create_react_agent(model, tools)

        # --- 修改 Agent 查询以使用 'ping' 工具 ---
        print("正在运行 Agent 查询 (STDIO - Minimal Server Test)...")
        test_query_payload = "testing 123"
        query = f"Please use the ping tool with the query '{test_query_payload}'." # 明确指令
        print(f"查询: {query}")
        # ---

        try:
            response = await asyncio.wait_for(
                agent.ainvoke({"messages": [{"role": "user","content": query}]}),
                timeout=60.0
            )

            # 打印结果
            print("\nAgent 响应 (STDIO - Minimal Server Test)：")
            if response and "messages" in response and response["messages"]:
                 response_content = response["messages"][-1].content
                 print(response_content)
                 # 检查响应是否包含预期的 'pong: <payload>'
                 expected_response_part = f"pong: {test_query_payload}"
                 if expected_response_part in response_content: # case-sensitive check might be better
                      print(f"\n✅ 测试成功：Agent 响应包含 '{expected_response_part}'!")
                 else:
                      print(f"\n⚠️ 测试可能部分成功，但响应未明确包含 '{expected_response_part}'。检查 Agent 的思考过程和服务器日志。")
            else:
                 print("Agent 未返回有效响应。")
        except asyncio.TimeoutError:
            print("Agent 执行超时 (STDIO - Minimal Server Test)")
        except Exception as e:
            print(f"Agent 执行失败 (STDIO - Minimal Server Test): {e}")
            print(f"错误详情:\n{traceback.format_exc()}")

    except Exception as e:
        print(f"Minimal Server (STDIO) 示例运行失败: {e}")
        print(f"错误详情:\n{traceback.format_exc()}")
    finally:
        if client:
            print("正在关闭 MCP 客户端 (Minimal Test)...")
            await client.close()
            print("MCP 客户端已关闭 (Minimal Test)")

    print("=== Minimal FastMCP Server 测试 (STDIO) 结束 ===")


async def main():
    """主函数"""
    print("开始 MCP 集成测试 (Minimal Server Focus)...")
    # --- 只运行 Minimal Server 测试 ---
    await run_minimal_server_stdio_test()
    # ---
    # 注释掉其他测试
    # await run_single_server_stdio_test()
    # await run_sse_server_example()
    # await run_multi_server_example()
    print("\nMCP 集成测试完成！")

if __name__ == "__main__":
    # 依赖检查可以保留
    try:
        import mcp
        import langchain_mcp_adapters
        import langgraph
        import langchain_openai # 或你的 LLM 库
        import dotenv
    except ImportError as e:
        print(f"错误：缺少必要的依赖: {e}")
        sys.exit(1)

    # 确保 MentisMCPClient 有 get_tools 方法 (如果之前删除了需要加回来)
    if not hasattr(MentisMCPClient, 'get_tools'):
         print("DEBUG: Adding get_tools method back to MentisMCPClient for testing")
         def get_tools_impl(self) -> List[BaseTool]:
              return self.tools
         MentisMCPClient.get_tools = get_tools_impl

    asyncio.run(main())