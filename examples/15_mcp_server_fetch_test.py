# examples/14_mcp_integration_test.py (最终修复版 - BaseTool 子类)
import os
import sys
import asyncio
import json
from dotenv import load_dotenv
import traceback
from typing import List, Dict, Any, Optional, Type

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

# --- LangChain Imports ---
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import BaseTool # 导入 BaseTool
from langchain_core.messages import HumanMessage
from langchain_core.pydantic_v1 import BaseModel, Field # 使用 v1 或 v2 都可以

# --- MCP 和本地代码 Imports ---
from core.mcp.client import MCPClient # 使用 config-driven client
from core.mcp.config_loader import load_config, MCPConfig, StdioConfig # 导入配置
from core.llm.llm_manager import LLMManager

# --- MCP 数据类型 ---
try: from mcp.types import CallToolRequest; CALL_TOOL_REQ_AVAILABLE = True
except ImportError: CallToolRequest = None; CALL_TOOL_REQ_AVAILABLE = False

# --- Tool Schemas ---
# E2B
try: from core.tools.e2b_tool import E2BCodeInterpreterToolInput; E2B_SCHEMA_AVAILABLE = True
except ImportError: E2BCodeInterpreterToolInput = None; E2B_SCHEMA_AVAILABLE = False
# ExecPython
try:
    class ExecPythonInputSchema(BaseModel): command: str = Field(..., description="The Python command to execute.")
    EXEC_PYTHON_SCHEMA_AVAILABLE = True
except Exception: ExecPythonInputSchema = None; EXEC_PYTHON_SCHEMA_AVAILABLE = False
# Tavily
try:
    class TavilyInputSchema(BaseModel): query: str = Field(..., description="The search query string.")
    TAVILY_SCHEMA_AVAILABLE = True
except Exception: TavilyInputSchema = None; TAVILY_SCHEMA_AVAILABLE = False
# Fetch
try:
    class FetchInputSchema(BaseModel):
         url: str = Field(..., description="URL to fetch")
         max_length: Optional[int] = Field(default=5000); start_index: Optional[int] = Field(default=0); raw: Optional[bool] = Field(default=False)
    FETCH_SCHEMA_AVAILABLE = True
except Exception: FetchInputSchema = None; FETCH_SCHEMA_AVAILABLE = False
# ---

# --- 全局设置 ---
CENTRAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "mcp", "config.json") # 中央配置文件路径
LLM_ID_FOR_TESTING = "openai_gpt4o_mini" # 推荐 OpenAI

llm_manager = LLMManager()

# --- 标准 BaseTool 子类定义 ---
class MCPToolRunner(BaseTool):
    """
    通用的 BaseTool 子类，用于通过 MCP 调用服务器上的工具。
    在实例化时需要传入激活的 MCPClient。
    """
    # --- 类属性 ---
    name: str = "needs_to_be_overridden" # 必须在实例化或子类中覆盖
    description: str = "needs_to_be_overridden"
    args_schema: Optional[Type[BaseModel]] = None # 必须在实例化或子类中覆盖

    # --- 实例属性 ---
    client: MCPClient = Field(exclude=True) # 存储客户端引用, exclude 避免 Pydantic 处理

    # Pydantic V2 配置 (如果使用 V2 Base)
    # model_config = {"arbitrary_types_allowed": True}
    # Pydantic V1 配置 (如果使用 V1 Base)
    class Config:
        arbitrary_types_allowed = True

    async def _arun(self, **kwargs) -> str: # LangChain 会将 Schema 字段作为 kwargs 传入
        """异步执行，内部调用 MCP session"""
        if not self.client or not self.client.session:
            return f"ERROR: MCP Client session inactive for {self.name}."
        if not CALL_TOOL_REQ_AVAILABLE:
             return "ERROR: CallToolRequest type not available."

        try:
            # kwargs 应该是 LangChain 根据 args_schema 处理好的参数字典
            print(f"    [_arun:{self.name}] Sending MCP request with args: {kwargs}")
            request_params = {"name": self.name, "arguments": kwargs}
            request = CallToolRequest(method='tools/call', params=request_params) # 使用正确的构造
            print(f"    [_arun:{self.name}] Sending Request Object: {request}")

            # 调用 MCP session
            result_message = await asyncio.wait_for(
                self.client.session.call_tool(request),
                timeout=120.0 # 给予足够超时时间
            )

            # 处理返回结果
            if hasattr(result_message, 'result'):
                res_val = result_message.result
                print(f"    [_arun:{self.name}] MCP Success, result snippet: {str(res_val)[:500]}...")
                # 确保返回字符串给 Agent
                return str(res_val) if not isinstance(res_val, str) else res_val
            elif hasattr(result_message, 'error'):
                err_msg = result_message.error.message
                stack = result_message.error.stack
                print(f"    [_arun:{self.name}] MCP Tool Error: {err_msg}")
                if stack: print(f"      Stack:\n{stack}")
                # 返回明确错误给 Agent
                return f"Tool Error for {self.name}: {err_msg}"
            else:
                print(f"    [_arun:{self.name}] Unknown MCP response.")
                return f"Unknown response from MCP tool {self.name}."
        except asyncio.TimeoutError:
            print(f"    [_arun:{self.name}] MCP call timeout.")
            return f"Error: Timeout calling MCP tool {self.name}."
        except Exception as e:
            print(f"    [_arun:{self.name}] Unexpected error during MCP call: {e}")
            print(traceback.format_exc())
            return f"Unexpected Error calling {self.name}: {e}"

    # 通常不需要实现 _run， LangChain 会自动处理异步优先
    # def _run(self, **kwargs) -> str:
    #     raise NotImplementedError("This tool only supports async")

# --- 通用测试函数：使用 BaseTool 子类 ---
async def run_stdio_basetool_test(server_config_key: str,
                                  all_configs: Dict[str, MCPConfig],
                                  tool_name: str,
                                  tool_description: str,
                                  tool_args_schema: Optional[Type[BaseModel]], # 可以是 V1 或 V2
                                  query: str,
                                  expected_result_part: Optional[str] = None):
    """使用指定的服务器配置和【手动实例化的 BaseTool 子类】运行 Agent 测试 (STDIO)。"""
    print(f"\n=== Running STDIO BaseTool Test for Server '{server_config_key}' (Tool: '{tool_name}') ===")

    if not tool_args_schema: print(f"ERROR: Schema not provided for '{tool_name}'."); return False
    if not CALL_TOOL_REQ_AVAILABLE: print("ERROR: CallToolRequest not imported."); return False

    server_config = all_configs.get(server_config_key)
    if not server_config: print(f"ERROR: Config for '{server_config_key}' not found."); return False
    if not isinstance(server_config.connection, StdioConfig): print(f"ERROR: Config '{server_config_key}' not STDIO."); return False

    try: model = llm_manager.get_model(LLM_ID_FOR_TESTING); print(f"Using LLM: {getattr(model, 'model_name', LLM_ID_FOR_TESTING)}")
    except ValueError as e: print(f"获取 LLM 出错: {e}."); return False

    test_success = False
    try:
        # 使用配置启动/连接服务器
        async with MCPClient(server_config) as client:
            print(f"MCPClient connected for '{server_config_key}'.")
            if not client.session: print("ERROR: MCP session not established!"); return False

            # --- 关键：实例化 BaseTool 子类 ---
            try:
                print(f"Instantiating MCPToolRunner for '{tool_name}'...")
                # 动态设置工具的特定属性
                mcp_tool_instance = MCPToolRunner(
                    client=client, # 注入 client 实例
                    name=tool_name,
                    description=tool_description,
                    args_schema=tool_args_schema
                )
                tools = [mcp_tool_instance]
                print(f"Tool instance created: Name='{tools[0].name}', Schema={tools[0].args_schema}")
            except Exception as e_inst:
                print(f"ERROR: Failed to instantiate MCPToolRunner for '{tool_name}': {e_inst}")
                return False
            # ---

            # --- Agent 执行部分 ---
            agent = create_react_agent(model, tools) # Agent 使用这个标准工具
            print(f"\nRunning Agent Query...")
            print(f"Query: {query}")
            print("--- NOTE: Enable LangSmith for detailed tracing! ---")
            try:
                response = await asyncio.wait_for( agent.ainvoke({"messages": [{"role": "user","content": query}]}), timeout=180.0 )
                print(f"\nAgent Final Response:")
                if response and "messages" in response and response["messages"]:
                     response_content = response["messages"][-1].content; print(response_content)
                     contains_error = "error" in response_content.lower() or "fail" in response_content.lower() or "issue" in response_content.lower() or "apologi" in response_content.lower() or "unable" in response_content.lower() or "tool error" in response_content.lower()
                     contains_expected = expected_result_part and expected_result_part in response_content
                     if not contains_error and (expected_result_part is None or contains_expected):
                          print(f"\n✅ Test PASS (No errors reported, expected '{expected_result_part}' found if applicable).")
                          test_success = True
                     else: print(f"\n❌ Test FAIL (Agent reported error or expected '{expected_result_part}' not found)."); test_success = False
                else: print("Agent returned no valid response."); test_success = False
            except asyncio.TimeoutError: print(f"Agent execution timed out"); test_success = False
            except Exception as e: print(f"Agent execution failed: {e}"); print(f"Traceback:\n{traceback.format_exc()}"); test_success = False
            # --- Agent 执行结束 ---

    except Exception as e: print(f"Test function failed for '{server_config_key}': {e}"); print(f"Traceback:\n{traceback.format_exc()}"); test_success = False
    # async with 自动调用 client.close()
    print(f"=== Test for '{server_config_key}' (Tool: '{tool_name}') finished. Result: {'PASS' if test_success else 'FAIL'} ===")
    return test_success

async def main():
    """主函数 - 加载中央配置并使用 BaseTool 子类运行测试"""
    print("Starting MCP Integration Test (BaseTool Subclass Focus)...")
    all_tests_passed = True
    results = {}

    # --- 加载中央配置 ---
    try:
         all_configs = load_config(CENTRAL_CONFIG_PATH)
         print(f"Loaded {len(all_configs)} server configurations from {CENTRAL_CONFIG_PATH}")
    except Exception as e: print(f"CRITICAL ERROR loading config '{CENTRAL_CONFIG_PATH}': {e}"); sys.exit(1)

    # --- 定义要测试的工具和服务 ---
    tests_to_run = [
        {
            "server_key": "e2b_stdio", # config.json 中的键
            "tool_name": "e2b_code_interpreter",
            "tool_description": "Executes Python code in a sandbox environment. Input MUST be a JSON object with a 'code' key...", # 真实描述
            "schema": E2BCodeInterpreterToolInput,
            "query": f"Use the e2b_code_interpreter tool to execute: print(111 * 3)",
            "expected": "333",
            "enabled": E2B_SCHEMA_AVAILABLE and CALL_TOOL_REQ_AVAILABLE
        },
        {
            "server_key": "python_repl_stdio",
            "tool_name": "riza_exec_python", # 确认名称
            "tool_description": "Executes Python command.",
            "schema": ExecPythonInputSchema,
            "query": f"Use riza_exec_python tool to calculate 111 * 4.",
            "expected": "444",
            "enabled": EXEC_PYTHON_SCHEMA_AVAILABLE and CALL_TOOL_REQ_AVAILABLE
        },
        {
            "server_key": "fetch_via_uvx",
            "tool_name": "fetch",
            "tool_description": "Fetches URL content as markdown.",
            "schema": FetchInputSchema,
            "query": "Use the fetch tool to get the main H1 title from https://example.com",
            "expected": "Example Domain",
            "enabled": FETCH_SCHEMA_AVAILABLE and CALL_TOOL_REQ_AVAILABLE
        },
        # 可以添加 Tavily 测试
        # {
        #     "server_key": "tavily_stdio",
        #     "tool_name": "tavily_search_results_json",
        #     "tool_description": "Web search using Tavily.",
        #     "schema": TavilyInputSchema,
        #     "query": f"Use tavily_search_results_json to search for 'LangGraph'",
        #     "expected": "LangGraph",
        #     "enabled": TAVILY_SCHEMA_AVAILABLE and CALL_TOOL_REQ_AVAILABLE
        # },
    ]
    # ---

    # --- 依次运行测试 ---
    for test_info in tests_to_run:
         server_key = test_info["server_key"]
         tool_name = test_info["tool_name"]
         print("\n" + "#"*30 + f" Starting Test: {server_key} / {tool_name} " + "#"*30)

         if not test_info["enabled"]:
              print(f"Skipping test for '{tool_name}' (Schema or CallToolRequest unavailable).")
              results[f"{server_key}/{tool_name}"] = None
              continue

         server_config_obj = all_configs.get(server_key)
         if not server_config_obj: print(f"ERROR: Config for '{server_key}' not found. Skipping."); results[f"{server_key}/{tool_name}"] = False; all_tests_passed = False; continue
         if not test_info.get("schema"): print(f"ERROR: Schema missing for '{tool_name}'. Skipping."); results[f"{server_key}/{tool_name}"] = False; all_tests_passed = False; continue

         # 运行测试
         success = await run_stdio_basetool_test(
             server_key, all_configs, tool_name,
             test_info["tool_description"], test_info["schema"],
             test_info["query"], test_info["expected"]
         )
         results[f"{server_key}/{tool_name}"] = success
         if not success: all_tests_passed = False
         await asyncio.sleep(3) # 测试间增加等待，确保进程完全关闭

    # --- Final Summary ---
    print("\n" + "="*20 + " FINAL TEST SUMMARY (BaseTool Subclass) " + "="*20);
    if not results: print("  No tests were run.")
    for test_name, passed in results.items(): print(f"  Test {test_name}: {'PASS' if passed else ('FAIL' if passed is False else 'SKIP')}")
    print("-" * (42 + len(" FINAL TEST SUMMARY (BaseTool Subclass) ")))
    if not results: print("⚪⚪⚪ No tests run. ⚪⚪⚪")
    elif all_tests_passed: print("✅✅✅ All attempted tests PASSED using BaseTool subclass! Problem should be resolved. ✅✅✅")
    else: print("❌❌❌ One or more tests FAILED! Review specific test logs and server logs. ❌❌❌")
    print("="*20 + " MCP Integration Test Finished " + "="*20)


if __name__ == "__main__":
    # if not CALL_TOOL_REQ_AVAILABLE: sys.exit(1)

    asyncio.run(main())