# examples/14_mcp_integration_test.py

import os
import sys
import asyncio
import subprocess
import time
from dotenv import load_dotenv
from typing import List, Dict, Any
import traceback  # Import traceback at the top

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 加载环境变量
load_dotenv()

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
# Ensure correct import path for get_mcp_client if used, MultiServerMCPClient and MentisMCPClient
from core.mcp.client import get_mcp_client, MultiServerMCPClient, MentisMCPClient
from core.llm.llm_manager import LLMManager
from mcp import ClientSession # Import ClientSession
from langchain_mcp_adapters.tools import load_mcp_tools # Import load_mcp_tools

# 确定 MCP 服务器脚本路径
MCP_SERVER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core",
    "mcp",
    "run_server.py"
)

# 初始化 LLM 管理器
llm_manager = LLMManager()

def start_mcp_server(transport="stdio", host="0.0.0.0", port=8000, debug=True):
    """
    启动 MCP 服务器（主要用于 SSE 传输的后台启动）

    Args:
        transport: 传输方式 ("stdio" 或 "sse")
        host: 主机地址 (通常使用 "0.0.0.0" 允许任何地址连接)
        port: 端口号
        debug: 是否启用调试模式

    Returns:
        subprocess.Popen 实例 or None if transport is not sse
    """
    if transport == "sse":
        print(f"正在启动 MCP 服务器 (SSE) on {host}:{port}...")

        # 构建命令行
        cmd = [
            sys.executable,
            MCP_SERVER_SCRIPT,
            "--transport", "sse",
            "--host", host,
            "--port", str(port)
        ]

        if debug:
            cmd.append("--debug")

        print(f"启动命令: {' '.join(cmd)}")

        # 启动进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # 行缓冲
            # Use different environment variables or cwd if needed
            # env=os.environ.copy(),
            # cwd=os.path.dirname(MCP_SERVER_SCRIPT) # Example if script needs specific CWD
        )

        # 等待服务器启动，并检查输出
        print("等待服务器启动...")
        start_time = time.time()
        ready = False
        startup_indicators = [
            "SSE 服务器将监听",
            "Application startup complete",
            "Uvicorn running on",
            "INFO:     Application startup complete",  # uvicorn 标准日志
            "INFO:     Uvicorn running on"             # uvicorn 标准日志
        ]

        # 收集输出以备后用
        output_lines = []
        error_lines = []
        max_wait_time = 30 # Increased wait time

        output_monitor_thread = None # Define thread variable

        def monitor_output_thread(proc, out_q, err_q):
            """Monitors stdout and stderr in a separate thread."""
            if proc.stdout:
                for line in iter(proc.stdout.readline, ''):
                    out_q.put(line)
                proc.stdout.close()
            if proc.stderr:
                for line in iter(proc.stderr.readline, ''):
                    err_q.put(line)
                proc.stderr.close()

        # Use queues to get output from the thread
        import queue
        stdout_q = queue.Queue()
        stderr_q = queue.Queue()

        # Start the monitoring thread
        import threading
        output_monitor_thread = threading.Thread(
            target=monitor_output_thread, args=(process, stdout_q, stderr_q), daemon=True
        )
        output_monitor_thread.start()


        while time.time() - start_time < max_wait_time:
            # Check stdout queue
            while not stdout_q.empty():
                try:
                    line = stdout_q.get_nowait().strip()
                    if line:
                        output_lines.append(line)
                        print(f"服务器输出: {line}")
                        if any(indicator in line for indicator in startup_indicators):
                            ready = True
                except queue.Empty:
                    break # Should not happen with get_nowait but good practice

            # Check stderr queue
            while not stderr_q.empty():
                try:
                    line = stderr_q.get_nowait().strip()
                    if line:
                        error_lines.append(line)
                        print(f"服务器错误: {line}") # Log errors immediately
                except queue.Empty:
                    break

            # 检查进程是否仍在运行
            if process.poll() is not None:
                print(f"警告: 服务器进程已退出，返回码: {process.returncode}")
                # Drain queues one last time
                while not stdout_q.empty(): output_lines.append(stdout_q.get_nowait().strip())
                while not stderr_q.empty(): error_lines.append(stderr_q.get_nowait().strip())
                break

            # 如果已经找到启动成功的指示，退出循环
            if ready:
                print("✅ 检测到服务器启动指示符.")
                break

            # 等待一段时间再继续检查
            time.sleep(0.5)

        # Check if process exited prematurely
        if process.poll() is not None and not ready:
             print("❌ 服务器进程意外退出，未能启动成功。")
             # Print collected logs
             if output_lines:
                 print("\n服务器最终输出:")
                 for line in output_lines: print(f"  {line}")
             if error_lines:
                 print("\n服务器最终错误日志:")
                 for line in error_lines: print(f"  {line}")
             return None # Indicate failure

        # 检查端口是否已经在监听 (secondary check)
        import socket
        listening = False
        try:
            # Check specifically the host we asked it to bind to, or localhost if 0.0.0.0
            check_host = "127.0.0.1" if host == "0.0.0.0" else host
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1) # Don't wait too long for connection
            result = sock.connect_ex((check_host, port))
            sock.close()

            if result == 0:
                print(f"✅ 确认端口 {port} 在 {check_host} 上已在监听状态")
                listening = True
            else:
                print(f"⚠️ 端口 {port} 在 {check_host} 上未处于监听状态 (connect_ex code: {result})")
        except Exception as e:
            print(f"检查端口 {port} 时出错: {e}")

        if ready and listening:
            print(f"✅ MCP 服务器似乎已成功启动并监听 http://{host}:{port}/sse")
        elif ready and not listening:
             print(f"⚠️ 检测到启动指示符，但端口 {port} 未监听。服务器可能仍在初始化或配置错误。")
        elif not ready and listening:
             print(f"⚠️ 端口 {port} 已监听，但未检测到预期的启动日志。服务器可能已启动但日志格式不同。")
        else:
            print("❌ 未能确认服务器启动成功。将继续尝试连接，但这可能会失败。")

            # 输出收集的所有日志
            # Drain queues one last time
            while not stdout_q.empty(): output_lines.append(stdout_q.get_nowait().strip())
            while not stderr_q.empty(): error_lines.append(stderr_q.get_nowait().strip())
            if output_lines:
                print("\n服务器完整输出:")
                for line in output_lines: print(f"  {line}")
            if error_lines:
                print("\n服务器错误日志:")
                for line in error_lines: print(f"  {line}")

        # Keep the process handle but don't start a new monitoring thread here
        # The background thread `output_monitor_thread` is already running

        # 等待额外时间确保服务器完全就绪
        extra_wait = 5
        print(f"给予服务器额外 {extra_wait} 秒完全初始化...")
        time.sleep(extra_wait)
        return process # Return process handle
    else:
        print("注意: STDIO 模式不需要预先启动服务器")
        return None

async def run_single_server_example():
    """运行单服务器 MCP 示例 (STDIO)"""
    print("\n=== 运行单服务器 MCP 示例 (STDIO) ===")

    # 初始化 LLM
    try:
        model = llm_manager.get_model("xai_grok") # Example model
    except ValueError as e:
        print(f"获取 LLM 时出错: {e}. 请确保 LLM 配置正确。")
        return

    client = None

    # 使用 try-finally 确保资源正确清理，即使出现错误
    try:
        print(f"尝试连接 MCP 服务器 (STDIO): {MCP_SERVER_SCRIPT}")
        # 使用 MentisMCPClient 连接
        client = MentisMCPClient()
        # Assuming connect_stdio is the correct method for stdio
        await client.connect_stdio(command=sys.executable, args=[MCP_SERVER_SCRIPT])

        # 获取工具
        tools = client.get_tools()
        print(f"成功加载 {len(tools)} 个工具")

        if not tools:
            print("警告：没有加载到任何工具，请检查工具注册情况。")
            return # Exit if no tools loaded

        # 创建 agent
        agent = create_react_agent(model, tools)

        # 运行 agent - 添加超时和取消处理
        print("正在运行 Agent 查询 (STDIO)...")
        try:
            # 设置一个较长的超时时间
            response = await asyncio.wait_for(
                agent.ainvoke({
                    "messages": [
                        {
                            "role": "user",
                            "content": "calculate 7 * 6 using Python. Return the result."
                        }
                    ]
                }),
                timeout=60.0  # 60秒超时
            )

            # 打印结果
            print("\nAgent 响应 (STDIO)：")
            if response and "messages" in response and response["messages"]:
                 print(response["messages"][-1].content)
            else:
                 print("Agent 未返回有效响应。")
        except asyncio.TimeoutError:
            print("Agent 执行超时 (STDIO)")
        except asyncio.CancelledError:
            print("Agent 执行被取消 (STDIO)")
        except Exception as e:
            print(f"Agent 执行失败 (STDIO): {e}")
            print(f"错误详情:\n{traceback.format_exc()}")
    except Exception as e:
        print(f"单服务器 STDIO 示例运行失败: {e}")
        print(f"错误详情:\n{traceback.format_exc()}")
    finally:
        # 确保关闭客户端，即使出现错误
        if client:
            print("正在关闭 MCP 客户端 (STDIO)...")
            await client.close()
            print("MCP 客户端已关闭 (STDIO)")

    print("=== 单服务器 MCP 示例 (STDIO) 结束 ===")

async def run_sse_server_example():
    """运行 SSE 服务器 MCP 示例"""
    print("\n=== 运行 SSE 服务器 MCP 示例 ===")

    # 使用端口 8000
    port = 8000
    host = "localhost" # Connect to localhost
    server_host_bind = "0.0.0.0" # Ask server to bind to 0.0.0.0
    server_process = None
    client = None # Use the MentisMCPClient instance

    try:
        # 检查端口是否已被占用 on the specific host we intend to connect to
        import socket
        port_busy = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                port_busy = True
                print(f"端口 {port} 在 {host} 上已被占用，可能是已经有 MCP 服务器正在运行")
                print("尝试直接连接到现有服务器...")
            else:
                 print(f"端口 {port} 在 {host} 上可用。")
        except Exception as e:
            print(f"检查端口 {port} 时出错: {e}. 假设端口可用。")


        if not port_busy:
            # 启动 SSE 服务器, telling it to bind to 0.0.0.0
            server_process = start_mcp_server(transport="sse", host=server_host_bind, port=port)
            if server_process is None:
                 print("❌ 启动服务器进程失败。无法继续 SSE 示例。")
                 return
            # Give server time to start *after* start_mcp_server confirms readiness/waits
            print("等待服务器完成启动...")
            await asyncio.sleep(2) # Shorter sleep as start_mcp_server already waits


        # 初始化 LLM
        try:
             print("初始化 LLM...")
             model = llm_manager.get_model("xai_grok") # Or another configured model
        except ValueError as e:
             print(f"获取 LLM 时出错: {e}. 请确保 LLM 配置正确。")
             if server_process: server_process.terminate() # Clean up server if LLM fails
             return

        # 连接到 SSE 服务器 using MentisMCPClient
        url = f"http://{host}:{port}/sse" # URL to connect to localhost
        print(f"尝试连接 SSE 服务器: {url}")

        try:
            # Use the client class for connection
            client = MentisMCPClient()
            await client.connect_sse(url=url) # Use the client's connect method

            # Get tools via client
            tools = client.get_tools()
            print(f"成功加载 {len(tools)} 个工具 (SSE)")

            if not tools:
                print("警告：没有加载到任何工具 (SSE)，请检查服务器工具注册情况。")
                # Don't return immediately, let cleanup happen
            else:
                # 筛选出我们需要的工具进行检查（可选）
                # 创建 agent
                print("创建 Agent (SSE)...")
                agent = create_react_agent(model, tools)

                # 运行 agent
                print("运行 Agent 查询 (SSE - 简单 Python)...")
                response = await asyncio.wait_for(
                    agent.ainvoke({
                        "messages": [
                            {
                                "role": "user",
                                "content": "Calculate 7 * 6 using Python. Return the result."
                            }
                        ]
                    }),
                    timeout=60.0  # 60秒超时
                )
                # 打印结果
                print("\nAgent 响应 (SSE)：")
                if response and "messages" in response and response["messages"]:
                     print(response["messages"][-1].content)
                else:
                     print("Agent 未返回有效响应 (SSE)。")

                print("运行 Agent 查询 (SSE - 日期获取)...")
                # 一个简单的查询，目标是让 Agent 使用 requests_get
                query = "搜索今天是几月几号星期几？"
                print(f"查询: {query}")
                # --- 查询修改结束 ---

                response = await asyncio.wait_for(
                    agent.ainvoke({"messages": [
                        {"role": "user", "content": query}
                    ]}),
                    timeout=60.0  # 保持超时
                )

                # 打印结果
                print("\nAgent 响应 (SSE)：")
                if response and "messages" in response and response["messages"]:
                     print(response["messages"][-1].content)
                else:
                     print("Agent 未返回有效响应 (SSE)。")

        except Exception as e:
            print(f"SSE 客户端连接或 Agent 执行失败: {e}")
            print(f"错误详情:\n{traceback.format_exc()}")
            # Don't re-raise, allow finally block to run

    except Exception as e:
        print(f"SSE 服务器示例运行期间发生意外错误: {e}")
        print(f"错误详情:\n{traceback.format_exc()}")
    finally:
        # Close client connection if it exists
        if client:
             print("正在关闭 MCP 客户端 (SSE)...")
             await client.close()
             print("MCP 客户端已关闭 (SSE)")

        # 关闭服务器进程 if we started it
        if server_process:
            print("正在关闭 SSE 服务器进程...")
            if server_process.poll() is None: # Check if it's still running
                server_process.terminate()
                try:
                    server_process.wait(timeout=5)  # 等待最多5秒
                    print("服务器进程已正常终止。")
                except subprocess.TimeoutExpired:
                    print("服务器进程未能及时退出，强制终止")
                    server_process.kill()
                    server_process.wait() # Wait after killing
                except Exception as e_wait:
                    print(f"等待服务器进程退出时出错: {e_wait}")
            else:
                print("服务器进程已自行退出。")
            print("SSE 服务器进程处理完毕。")

    print("=== SSE 服务器 MCP 示例结束 ===")


async def run_multi_server_example():
    """运行多服务器 MCP 示例"""
    print("\n=== 运行多服务器 MCP 示例 ===")

    # 初始化 LLM
    try:
        model = llm_manager.get_model("xai_grok") # Example model
    except ValueError as e:
        print(f"获取 LLM 时出错: {e}. 请确保 LLM 配置正确。")
        return

    # 配置多服务器
    server_configs = {
        "main_tools": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [MCP_SERVER_SCRIPT] # Assumes this server provides needed tools
        },
        # 如果有其他服务器，可以添加在这里
        "sse_server_tools": {
            "transport": "sse",
            "url": "http://localhost:8000/sse" # Example SSE server
        }
    }

    try:
        # 使用多服务器客户端
        print("尝试连接多服务器...")
        # The MultiServerMCPClient handles __aenter__ and __aexit__ for connections
        async with MultiServerMCPClient(server_configs) as client:
            # 获取所有工具
            tools = client.get_tools()
            print(f"成功从所有服务器加载 {len(tools)} 个工具")

            if not tools:
                print("警告：没有从任何服务器加载到工具，请检查服务器配置和工具注册情况。")
                return # Exit if no tools loaded

            # 创建 agent
            agent = create_react_agent(model, tools)

            # 运行 agent
            print("正在运行 Agent 查询 (Multi-Server)...")
            response = await asyncio.wait_for(
                 agent.ainvoke({"messages": [
                     {"role": "user", "content": "分析一下提供的代码，并告诉我它的主要功能。"} # Example query
                 ]}),
                 timeout=120.0 # Longer timeout for potentially complex tasks
            )


            # 打印结果
            print("\nAgent 响应 (Multi-Server)：")
            if response and "messages" in response and response["messages"]:
                 print(response["messages"][-1].content)
            else:
                 print("Agent 未返回有效响应 (Multi-Server)。")

    except asyncio.TimeoutError:
            print("Agent 执行超时 (Multi-Server)")
    except Exception as e:
        print(f"多服务器示例运行失败: {e}")
        print(f"错误详情:\n{traceback.format_exc()}")

    print("=== 多服务器 MCP 示例结束 ===")

async def main():
    """主函数"""
    print("开始 MCP 集成测试...")

    # 运行单服务器示例 (STDIO)
    await run_single_server_example()

    # # 运行 SSE 服务器示例
    await run_sse_server_example()

    # # 运行多服务器示例 (Optional)
    await run_multi_server_example()

    print("\nMCP 集成测试完成！")

if __name__ == "__main__":
    # 检查依赖
    try:
        import mcp
        import langchain_mcp_adapters
        import langgraph
        import langchain_openai # Or your specific LLM provider library
        import dotenv
        import socket # Used in script
        import queue # Used in script
        import threading # Used in script
    except ImportError as e:
        print(f"错误：缺少必要的依赖: {e}")
        print("请确保已安装所有必要的包 (mcp, langchain_mcp_adapters, langgraph, langchain_openai, python-dotenv, etc.)")
        sys.exit(1)

    asyncio.run(main())