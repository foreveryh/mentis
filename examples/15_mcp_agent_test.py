# examples/14_mcp_fetch_basetool_test.py (最终版 - BaseTool 子类)
import os
import sys
import asyncio
import json
from dotenv import load_dotenv
import traceback
from typing import List, Dict, Any, Optional, Type

# --- 前置要求 ---
# 1. 确保 core/mcp/client.py 和 core/mcp/config_loader.py 是最新版本 (含 AsyncExitStack 和导入修复)。
# 2. 确保 core/mcp/config.json 文件存在，并包含 "fetch_via_uvx" 配置 (使用 uvx + stdio)。
# 3. 确保已安装 uv (`pip install uv`) 和 mcp-server-fetch。
# 4. 确保 OpenAI API Key (或其他 LLM Key) 在 .env 或环境变量中设置。
# 5. 推荐设置 LangSmith 环境变量用于详细追踪 Agent 行为。
# ---

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

# --- 核心依赖导入 ---
# LangChain
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage
try:
    # 尝试导入 Pydantic v1 (LangChain 常用的版本)
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    try:
        # 如果 V1 不可用，尝试导入 V2
        from pydantic import BaseModel, Field # type: ignore
    except ImportError:
         print("CRITICAL ERROR: Pydantic (v1 or v2) not found.")
         sys.exit(1)
# MCP Client/Config
try: from core.mcp.client import MCPClient
except ImportError: print("CRITICAL ERROR: Cannot import MCPClient."); sys.exit(1)
try: from core.mcp.config_loader import load_config, MCPConfig, StdioConfig
except ImportError: print("CRITICAL ERROR: Cannot import config loader."); sys.exit(1)
# LLM
from core.llm.llm_manager import LLMManager
# MCP Types
try: from mcp.types import CallToolRequest; CALL_TOOL_REQ_AVAILABLE = True
except ImportError: CallToolRequest = None; CALL_TOOL_REQ_AVAILABLE = False
# ---

# --- Fetch Tool Schema 定义 ---
FETCH_SCHEMA_AVAILABLE = False
FetchInputSchema = None
try:
    class FetchInputSchema(BaseModel): # 使用导入的 BaseModel
         url: str = Field(..., description="URL to fetch")
         max_length: Optional[int] = Field(default=5000, description="Maximum number of characters to return")
         start_index: Optional[int] = Field(default=0, description="Start content from this character index")
         raw: Optional[bool] = Field(default=False, description="Get raw content without markdown conversion")
    FETCH_SCHEMA_AVAILABLE = True
except Exception as e_pyd_fetch: print(f"ERROR defining FetchInputSchema: {e_pyd_fetch}")
# ---

# --- 全局设置 ---
# **重要**: 确认此路径指向你的中央配置文件
CENTRAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "mcp", "mcp_server_config.json")
# 使用 OpenAI 模型通常更稳定
LLM_ID_FOR_TESTING = "openai_gpt4o_mini"
# 要测试的服务器在 config.json 中的 key
SERVER_KEY_TO_TEST = "fetch_via_uvx"
# 要测试的工具名称
TOOL_NAME_TO_TEST = "fetch"
# 要测试的工具的正确 Schema
CORRECT_SCHEMA_FOR_TOOL = FetchInputSchema
# 要测试的工具的描述
TOOL_DESCRIPTION = "Fetches web content as markdown. Input requires 'url' (string) and optional 'max_length', 'start_index', 'raw'."

# --- Everything MCP 服务器设置 ---
EVERYTHING_SERVER_KEY = "everything"
EVERYTHING_ECHO_TOOL = "echo"
EVERYTHING_ADD_TOOL = "add"

# --- Everything MCP 工具 Schema 定义 ---
ECHO_SCHEMA_AVAILABLE = False
EchoInputSchema = None
try:
    class EchoInputSchema(BaseModel):
        message: str = Field(..., description="Message to echo back")
    ECHO_SCHEMA_AVAILABLE = True
except Exception as e_pyd_echo: print(f"ERROR defining EchoInputSchema: {e_pyd_echo}")

ADD_SCHEMA_AVAILABLE = False
AddInputSchema = None
try:
    class AddInputSchema(BaseModel):
        a: float = Field(..., description="First number")
        b: float = Field(..., description="Second number")
    ADD_SCHEMA_AVAILABLE = True
except Exception as e_pyd_add: print(f"ERROR defining AddInputSchema: {e_pyd_add}")

llm_manager = LLMManager()

# --- 标准 BaseTool 子类定义，用于桥接 MCP 调用 ---
class MCPToolRunner(BaseTool):
    """
    通过 MCP 调用服务器上工具的标准 BaseTool 实现。
    """
    # --- 类属性 (将在实例化时被覆盖) ---
    name: str = "mcp_tool_runner" # Default name
    description: str = "Runs a tool via MCP"
    args_schema: Optional[Type[BaseModel]] = None

    # --- 实例属性 ---
    client: MCPClient = Field(exclude=True) # 存储客户端引用

    # Pydantic 配置 (根据你使用的 BaseModel 版本)
    class Config: arbitrary_types_allowed = True

    async def _arun(self, **kwargs) -> str:
        """异步执行：构造 MCP 请求并调用 client.session.call_tool"""
        if not self.client or not self.client.session: return f"ERROR: MCP Client session inactive for {self.name}."
        if not CALL_TOOL_REQ_AVAILABLE: return "ERROR: CallToolRequest unavailable."

        try:
            # kwargs 应该是 LangChain 根据 args_schema 验证和准备好的参数
            print(f"    [_arun:{self.name}] Preparing MCP request with args: {kwargs}")
            # 不再需要构造CallToolRequest对象，直接传递工具名称和参数
            print(f"    [_arun:{self.name}] Calling tool '{self.name}' with args: {kwargs}")

            # 调用 MCP session - 直接传递工具名称和参数
            result_message = await asyncio.wait_for(
                self.client.session.call_tool(self.name, kwargs),
                timeout=120.0 # 给予足够的网络和执行超时
            )

            # 处理结果 - 简化处理逻辑，直接检查content属性
            print(f"    [_arun:{self.name}] MCP Response received, type: {type(result_message)}")
            
            # 直接检查是否有content属性（根据日志显示的响应结构）
            if hasattr(result_message, 'content'):
                content = result_message.content
                print(f"    [_arun:{self.name}] Found content attribute, type: {type(content)}")
                
                # 如果content是列表且不为空
                if isinstance(content, list) and len(content) > 0:
                    first_item = content[0]
                    print(f"    [_arun:{self.name}] Content is a list, first item type: {type(first_item)}")
                    
                    # 尝试获取text属性
                    if hasattr(first_item, 'text'):
                        print(f"    [_arun:{self.name}] First item has text attribute, returning text")
                        return first_item.text
                    else:
                        print(f"    [_arun:{self.name}] First item has no text attribute, converting to string")
                        return str(first_item)
                elif hasattr(content, 'text'):
                    print(f"    [_arun:{self.name}] Content has text attribute, returning text")
                    return content.text
                else:
                    print(f"    [_arun:{self.name}] Content has no text attribute, converting to string")
                    return str(content)
            # 如果没有content属性，回退到检查result属性
            elif hasattr(result_message, 'result'):
                res_val = result_message.result
                print(f"    [_arun:{self.name}] Found result attribute: {str(res_val)[:500]}...")
                return str(res_val) if not isinstance(res_val, str) else res_val
            elif hasattr(result_message, 'error'):
                err_msg = result_message.error.message
                print(f"    [_arun:{self.name}] MCP Tool Error: {err_msg}")
                # 对于 Agent，返回错误通常比抛出异常更好处理
                return f"Tool Error: {err_msg}"
            else:
                # 打印完整的响应对象，帮助诊断问题
                print(f"    [_arun:{self.name}] Unknown MCP response format. Full response object: {result_message}")
                print(f"    [_arun:{self.name}] Response type: {type(result_message)}")
                print(f"    [_arun:{self.name}] Response dir: {dir(result_message)}")
                
                # 尝试处理特殊的响应格式
                if hasattr(result_message, 'content'):
                    content = result_message.content
                    print(f"    [_arun:{self.name}] Found content attribute in response")
                    
                    # 处理content是列表的情况
                    if isinstance(content, list) and len(content) > 0:
                        print(f"    [_arun:{self.name}] Content is a list with {len(content)} items")
                        first_item = content[0]
                        if hasattr(first_item, 'text'):
                            print(f"    [_arun:{self.name}] First item has text attribute, returning text")
                            return first_item.text
                        elif hasattr(first_item, 'type') and hasattr(first_item, 'text'):
                            print(f"    [_arun:{self.name}] First item has type and text attributes, returning text")
                            return first_item.text
                        else:
                            print(f"    [_arun:{self.name}] First item has no text attribute, converting to string")
                            return str(first_item)
                    # 处理content是单个对象的情况
                    elif hasattr(content, 'text'):
                        print(f"    [_arun:{self.name}] Content has text attribute, returning text")
                        return content.text
                    else:
                        print(f"    [_arun:{self.name}] Content has no text attribute, converting to string")
                        return str(content)
                
                # 尝试提取更多信息
                response_details = ""
                for attr in dir(result_message):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(result_message, attr)
                            if not callable(value):
                                response_details += f"\n    - {attr}: {value}"
                        except Exception as attr_err:
                            response_details += f"\n    - {attr}: [Error accessing: {attr_err}]"
                print(f"    [_arun:{self.name}] Response details: {response_details}")
                return f"Unknown response from MCP tool {self.name}. Details: {response_details}"
        except asyncio.TimeoutError:
            print(f"    [_arun:{self.name}] MCP call timeout.")
            return f"Error: Timeout calling MCP tool {self.name}."
        except Exception as e:
            print(f"    [_arun:{self.name}] Unexpected error during MCP call: {e}")
            print(traceback.format_exc())
            # 返回包含 Traceback 的错误，方便调试
            return f"Unexpected Error calling {self.name}: {e}\n{traceback.format_exc()}"

    def _run(self, **kwargs) -> str:
        """同步执行 (简单实现，通过运行异步方法)"""
        print(f"    [_run:{self.name}] Running async method via asyncio.run()...")
        try:
            # 注意: 在已运行的事件循环中调用 asyncio.run 会报错
            # 更好的方法是检查当前循环或使用 anyio/nest_asyncio
            # 但为了满足 BaseTool 要求，先用简单方式，如果 Agent 只用 async 就没问题
            # 如果 Agent 强制用 sync，可能需要更复杂的处理
            # return asyncio.run(self._arun(**kwargs))
            # 更安全的方式是提示不支持或使用更复杂的同步转异步
             return "Synchronous execution not fully supported, please use async."
        except Exception as e:
             print(f"    [_run:{self.name}] Error: {e}")
             return f"Error in sync wrapper: {e}"
# ---

# --- 主要测试逻辑 ---
async def run_fetch_test():
    """运行 Fetch Server 测试 (使用 BaseTool 子类)"""
    print(f"\n=== Running Fetch Server Test (BaseTool Subclass Method) ===")

    # 检查依赖和 Schema 定义
    if not FETCH_SCHEMA_AVAILABLE: print("ERROR: FetchInputSchema not available."); return False
    if not CALL_TOOL_REQ_AVAILABLE: print("ERROR: CallToolRequest unavailable."); return False

    # 加载配置
    config: Optional[MCPConfig] = None
    try:
        all_configs = load_config(CENTRAL_CONFIG_PATH)
        config = all_configs.get(SERVER_KEY_TO_TEST)
        if not config: print(f"ERROR: Config key '{SERVER_KEY_TO_TEST}' not found in '{CENTRAL_CONFIG_PATH}'."); return False
        if not isinstance(config.connection, StdioConfig): print("ERROR: Config connection is not STDIO."); return False
        print(f"Successfully loaded config for '{SERVER_KEY_TO_TEST}'.")
    except Exception as e_load: print(f"ERROR loading config: {e_load}"); return False

    # 获取 LLM
    try: model = llm_manager.get_model(LLM_ID_FOR_TESTING); print(f"Using LLM: {getattr(model, 'model_name', LLM_ID_FOR_TESTING)}")
    except ValueError as e: print(f"获取 LLM 出错: {e}."); return False

    test_success = False
    # 使用 MCPClient 连接 (它会根据 config 启动服务器)
    async with MCPClient(config) as client:
        print("\nMCPClient context entered.")
        if not client.session: print("ERROR: MCP session not established!"); return False

        # --- 实例化我们定义的 MCPToolRunner ---
        try:
            print(f"Instantiating MCPToolRunner for '{TOOL_NAME_TO_TEST}'...")
            mcp_tool_instance = MCPToolRunner(
                client=client, # 注入 client
                name=TOOL_NAME_TO_TEST,
                description=TOOL_DESCRIPTION,
                args_schema=CORRECT_SCHEMA_FOR_TOOL
            )
            tools = [mcp_tool_instance]
            print(f"Tool instance created successfully.")
        except Exception as e_inst: print(f"ERROR instantiating MCPToolRunner: {e_inst}"); return False
        # ---

        # --- Agent 执行 ---
        agent = create_react_agent(model, tools) # Agent 使用这个标准工具
        query = "Use the fetch tool to get the main content (first 2000 chars) from https://developer.mozilla.org/en-US/docs/Web/HTML"
        print(f"\nRunning Agent Query...")
        print(f"Query: {query}")
        print("--- NOTE: Enable LangSmith for detailed tracing! ---")
        try:
            response = await asyncio.wait_for( agent.ainvoke({"messages": [{"role": "user","content": query}]}), timeout=180.0 )
            print(f"\nAgent Final Response:")
            if response and "messages" in response and response["messages"]:
                 response_content = response["messages"][-1].content; print(response_content)
                 # 检查是否成功获取内容且无报错
                 contains_error = "error" in response_content.lower() or "fail" in response_content.lower() or "issue" in response_content.lower() or "apologi" in response_content.lower() or "unable" in response_content.lower() or "tool error" in response_content.lower()
                 contains_expected = "HTML" in response_content

                 if not contains_error and contains_expected:
                      print(f"\n✅ Test PASS: Agent successfully used tool and got expected content.")
                      test_success = True
                 else: print(f"\n❌ Test FAIL: Agent reported error or didn't get expected content."); test_success = False
            else: print("Agent returned no valid response."); test_success = False
        except asyncio.TimeoutError: print(f"Agent execution timed out"); test_success = False
        except Exception as e: print(f"Agent execution failed: {e}"); print(f"Traceback:\n{traceback.format_exc()}"); test_success = False
        # ---

    # async with 会自动调用 client.close()
    print(f"\n--- Fetch Server Test Result: {'PASS' if test_success else 'FAIL'} ---")
    return test_success

async def run_everything_test():
    """运行 Everything MCP Server 测试 (使用 BaseTool 子类)"""
    print(f"\n=== Running Everything MCP Server Test (BaseTool Subclass Method) ===")

    # 检查依赖和 Schema 定义
    if not ECHO_SCHEMA_AVAILABLE: print("ERROR: EchoInputSchema not available."); return False
    if not ADD_SCHEMA_AVAILABLE: print("ERROR: AddInputSchema not available."); return False
    if not CALL_TOOL_REQ_AVAILABLE: print("ERROR: CallToolRequest unavailable."); return False

    # 加载配置
    config: Optional[MCPConfig] = None
    try:
        all_configs = load_config(CENTRAL_CONFIG_PATH)
        config = all_configs.get(EVERYTHING_SERVER_KEY)
        if not config: print(f"ERROR: Config key '{EVERYTHING_SERVER_KEY}' not found in '{CENTRAL_CONFIG_PATH}'."); return False
        if not isinstance(config.connection, StdioConfig): print("ERROR: Config connection is not STDIO."); return False
        print(f"Successfully loaded config for '{EVERYTHING_SERVER_KEY}'.")
    except Exception as e_load: print(f"ERROR loading config: {e_load}"); return False

    # 获取 LLM
    try: model = llm_manager.get_model(LLM_ID_FOR_TESTING); print(f"Using LLM: {getattr(model, 'model_name', LLM_ID_FOR_TESTING)}")
    except ValueError as e: print(f"获取 LLM 出错: {e}."); return False

    test_success = False
    # 使用 MCPClient 连接 (它会根据 config 启动服务器)
    async with MCPClient(config) as client:
        print("\nMCPClient context entered for Everything MCP.")
        if not client.session: print("ERROR: MCP session not established!"); return False

        # --- 实例化我们定义的 MCPToolRunner 用于 echo 工具 ---
        try:
            print(f"Instantiating MCPToolRunner for '{EVERYTHING_ECHO_TOOL}'...")
            echo_tool = MCPToolRunner(
                client=client, # 注入 client
                name=EVERYTHING_ECHO_TOOL,
                description="Echoes back the input message",
                args_schema=EchoInputSchema
            )
            
            print(f"Instantiating MCPToolRunner for '{EVERYTHING_ADD_TOOL}'...")
            add_tool = MCPToolRunner(
                client=client, # 注入 client
                name=EVERYTHING_ADD_TOOL,
                description="Adds two numbers together",
                args_schema=AddInputSchema
            )
            
            tools = [echo_tool, add_tool]
            print(f"Tool instances created successfully.")
        except Exception as e_inst: print(f"ERROR instantiating MCPToolRunner: {e_inst}"); return False
        # ---

        # --- Agent 执行 ---
        agent = create_react_agent(model, tools) # Agent 使用这些工具
        query = "First, use the echo tool to echo back the message 'Hello from Everything MCP!'. Then, use the add tool to calculate 42 + 58."
        print(f"\nRunning Agent Query...")
        print(f"Query: {query}")
        print("--- NOTE: Enable LangSmith for detailed tracing! ---")
        try:
            response = await asyncio.wait_for(agent.ainvoke({"messages": [{"role": "user","content": query}]}), timeout=180.0)
            print(f"\nAgent Final Response:")
            if response and "messages" in response and response["messages"]:
                response_content = response["messages"][-1].content; print(response_content)
                # 检查是否成功获取内容且无报错
                contains_error = "error" in response_content.lower() or "fail" in response_content.lower() or "issue" in response_content.lower() or "apologi" in response_content.lower() or "unable" in response_content.lower() or "tool error" in response_content.lower()
                contains_echo = "Hello from Everything MCP!" in response_content
                contains_add = "100" in response_content

                if not contains_error and contains_echo and contains_add:
                    print(f"\n✅ Test PASS: Agent successfully used both tools and got expected content.")
                    test_success = True
                else: 
                    print(f"\n❌ Test FAIL: Agent reported error or didn't get expected content.")
                    print(f"  - Contains error: {contains_error}")
                    print(f"  - Contains echo response: {contains_echo}")
                    print(f"  - Contains add result: {contains_add}")
                    test_success = False
            else: print("Agent returned no valid response."); test_success = False
        except asyncio.TimeoutError: print(f"Agent execution timed out"); test_success = False
        except Exception as e: print(f"Agent execution failed: {e}"); print(f"Traceback:\n{traceback.format_exc()}"); test_success = False
        # ---

    # async with 会自动调用 client.close()
    print(f"\n--- Everything MCP Server Test Result: {'PASS' if test_success else 'FAIL'} ---")
    return test_success

async def main():
    """主函数 - 运行所有测试"""
    print("Starting MCP Integration Tests...")
    
    # 运行 Fetch 测试
    fetch_success = await run_fetch_test()
    
    # 运行 Everything MCP 测试
    everything_success = await run_everything_test()
    
    print("\n" + "="*20 + " FINAL TEST SUMMARY " + "="*20);
    print(f"  Fetch Server Test: {'PASS' if fetch_success else 'FAIL'}")
    print(f"  Everything MCP Test: {'PASS' if everything_success else 'FAIL'}")
    print("="*20 + " MCP Integration Test Finished " + "="*20)

if __name__ == "__main__":
    # 简化依赖检查
    print("--- Dependency Check ---")
    deps_ok = True
    try: import mcp; print("mcp available: True")
    except ImportError: print("mcp available: False"); deps_ok = False
    if CALL_TOOL_REQ_AVAILABLE: print("CallToolRequest available: True")
    else: print("CallToolRequest available: False"); deps_ok = False # 需要它
    try: import langgraph; print("langgraph available: True")
    except ImportError: print("langgraph available: False"); deps_ok = False
    try: import langchain_openai; print("langchain_openai available: True")
    except ImportError: print("langchain_openai available: False"); deps_ok = False
    try: import dotenv; print("dotenv available: True")
    except ImportError: print("dotenv available: False"); deps_ok = False
    try: import pydantic; print("pydantic available: True")
    except ImportError: print("pydantic available: False"); deps_ok = False
    try: from core.mcp.client import MCPClient; print("MCPClient available: True")
    except ImportError: print("MCPClient available: False"); deps_ok = False
    try: from core.mcp.config_loader import load_config; print("config_loader available: True")
    except ImportError: print("config_loader available: False"); deps_ok = False
    if not FETCH_SCHEMA_AVAILABLE: print("FetchInputSchema available: False"); deps_ok=False
    else: print("FetchInputSchema available: True")
    if not ECHO_SCHEMA_AVAILABLE: print("EchoInputSchema available: False"); deps_ok=False
    else: print("EchoInputSchema available: True")
    if not ADD_SCHEMA_AVAILABLE: print("AddInputSchema available: False"); deps_ok=False
    else: print("AddInputSchema available: True")
    print(f"------------------------")

    if not deps_ok:
        print("CRITICAL ERROR: Necessary dependencies missing.")
        sys.exit(1)

    asyncio.run(main())