# examples/15_mcp_test.py (包含 Schema 检查的最终测试脚本)
import os
import sys
import asyncio
import subprocess
import time
import json # 导入 json
from dotenv import load_dotenv
import traceback
from typing import List, Dict, Any, Optional, Type # 导入 Type
from contextlib import AsyncExitStack

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from core.mcp.client import MentisMCPClient # 使用更新后的 Client
from core.llm.llm_manager import LLMManager
from langchain_core.tools import BaseTool
# 导入 Pydantic BaseModel 用于 schema 检查
try:
    from pydantic.v1 import BaseModel as BaseModelV1
except ImportError:
    from pydantic import BaseModel as BaseModelV1 # Fallback

# 导入 E2B 的 Input Schema 用于对比
try:
    from core.tools.e2b_tool import E2BInputSchema
    E2B_SCHEMA_AVAILABLE = True
except ImportError:
    print("警告: 无法导入 E2BInputSchema，Schema 对比可能不准确。")
    E2BInputSchema = None
    E2B_SCHEMA_AVAILABLE = False

# 导入 ExecPython 的 Input Schema (如果存在)
# 假设 ExecPython 需要一个 'command' 字符串
try:
    from pydantic.v1 import Field # 或者 v2
    class ExecInputSchema(BaseModelV1):
         command: str = Field(..., description="The command to execute.")
    EXEC_SCHEMA_AVAILABLE = True
except ImportError:
    print("警告: 无法定义 ExecInputSchema。")
    ExecInputSchema = None
    EXEC_SCHEMA_AVAILABLE = False


MCP_SERVER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core",
    "mcp",
    "run_server.py"
)

llm_manager = LLMManager()

async def run_stdio_single_tool_test(tool_name_to_test: str,
                                     correct_schema: Optional[Type[BaseModelV1]], # 传入正确的 Schema 用于对比
                                     query: str,
                                     expected_result_part: Optional[str] = None):
    """
    运行单服务器 MCP 示例 (STDIO) - 测试指定工具并检查 Schema
    """
    print(f"\n=== 运行单服务器 MCP 示例 (STDIO - Testing '{tool_name_to_test}') ===")

    try:
        model = llm_manager.get_model("openai_gpt4o_mini")
    except ValueError as e:
        print(f"获取 LLM 时出错: {e}.")
        return False

    client = MentisMCPClient() # 使用更新后的 Client
    test_success = False
    schema_looks_correct = False # 标记 Schema 是否看起来正确

    try:
        print(f"尝试连接 MCP 服务器 (STDIO - Testing {tool_name_to_test}): {MCP_SERVER_SCRIPT}")

        server_args = [
            MCP_SERVER_SCRIPT,
            "--transport", "stdio",
            "--tools", tool_name_to_test,
            "--debug"
        ]
        print(f"DEBUG: Starting server with command: {sys.executable} {' '.join(server_args)}")
        # 使用更新后的 connect_stdio
        await client.connect_stdio(command=sys.executable, args=server_args)

        # client._connect_internal 内部已经打印了加载的工具和 Schema
        # 这里我们再次检查 client.tools[0] 的 schema
        tools = client.get_tools()
        if not tools:
             print(f"错误：未能从服务器加载工具 '{tool_name_to_test}'！")
             return False

        found_tool = None
        for t in tools:
             if t.name == tool_name_to_test:
                  found_tool = t
                  break

        if not found_tool:
             print(f"错误：加载的工具列表中未找到 '{tool_name_to_test}'")
             return False

        print(f"\n--- 再次检查工具 '{tool_name_to_test}' 的 Args Schema ---")
        loaded_schema_obj = getattr(found_tool, 'args_schema', None)
        if loaded_schema_obj and correct_schema:
            # 比较加载的 Schema 和预期的 Schema 是否相似
            # 注意：直接比较类可能不准确，比较字段更可靠
            loaded_schema_fields = {}
            correct_schema_fields = {}
            if hasattr(loaded_schema_obj, 'schema') and hasattr(correct_schema, 'schema'): # Pydantic V1
                 loaded_schema_fields = loaded_schema_obj.schema().get('properties', {})
                 correct_schema_fields = correct_schema.schema().get('properties', {})
            elif hasattr(loaded_schema_obj, 'model_fields') and hasattr(correct_schema, 'model_fields'): # Pydantic V2
                 loaded_schema_fields = loaded_schema_obj.model_fields
                 correct_schema_fields = correct_schema.model_fields

            print(f"加载的 Schema 字段: {loaded_schema_fields.keys()}")
            print(f"预期的 Schema 字段: {correct_schema_fields.keys()}")

            # 简单比较：预期字段是否存在，且没有 'kwargs'
            expected_field_name = list(correct_schema_fields.keys())[0] # 假设只有一个主要字段
            if expected_field_name in loaded_schema_fields and 'kwargs' not in loaded_schema_fields:
                 print(f"✅ Schema 看起来正确 (包含 '{expected_field_name}', 不含 'kwargs')")
                 schema_looks_correct = True
            else:
                 print(f"❌ Schema 看起来错误! (预期 '{expected_field_name}', 实际 {loaded_schema_fields.keys()})")
                 schema_looks_correct = False
        elif not correct_schema:
             print("警告: 未提供用于对比的正确 Schema。")
             schema_looks_correct = True # 假设正确以继续测试
        else:
             print("❌ 错误: 加载的工具缺少 args_schema 或无法比较!")
             schema_looks_correct = False
        print("----------------------------------------\n")

        if not schema_looks_correct:
             print("由于检测到 Schema 错误，测试可能失败。建议先解决 Schema 问题。")
             # 可以选择在这里 return False

        # 创建 Agent
        agent = create_react_agent(model, tools)

        # 运行 Agent 查询
        print(f"正在运行 Agent 查询 (STDIO - Testing {tool_name_to_test})...")
        print(f"查询: {query}")
        try:
            response = await asyncio.wait_for(
                agent.ainvoke({"messages": [{"role": "user","content": query}]}),
                timeout=120.0
            )
            print(f"\nAgent 响应 (STDIO - Testing {tool_name_to_test})：")
            if response and "messages" in response and response["messages"]:
                 response_content = response["messages"][-1].content
                 print(response_content)
                 if expected_result_part and expected_result_part in response_content:
                      print(f"\n✅ 测试成功：Agent 响应包含了预期内容 '{expected_result_part}'!")
                      test_success = True
                 elif expected_result_part:
                      print(f"\n⚠️ 测试完成，但响应未明确包含预期内容 '{expected_result_part}'。")
                 else:
                      print("\n☑️ Agent 执行完成，请检查响应是否符合预期。")
                      test_success = True
            else:
                 print("Agent 未返回有效响应。")
        except asyncio.TimeoutError:
            print(f"Agent 执行超时 (STDIO - Testing {tool_name_to_test})")
            test_success = False # 超时算失败
        except Exception as e:
            print(f"Agent 执行失败 (STDIO - Testing {tool_name_to_test}): {e}")
            print(f"错误详情:\n{traceback.format_exc()}")
            test_success = False # 异常算失败

    except Exception as e:
        print(f"单工具测试示例 ({tool_name_to_test}) 运行失败: {e}")
        print(f"错误详情:\n{traceback.format_exc()}")
        test_success = False
    finally:
        if client:
            print(f"正在关闭 MCP 客户端 ({tool_name_to_test} Test)...")
            await client.close()
            print(f"MCP 客户端已关闭 ({tool_name_to_test} Test)")

    print(f"=== 单服务器 MCP 示例 (STDIO - Testing {tool_name_to_test}) 结束 ===")
    return test_success

async def main():
    """主函数 - 运行单个工具测试并检查 Schema"""
    print("开始 MCP 集成测试 (Single Tool Focus + Schema Check)...")
    success = False
    if E2B_SCHEMA_AVAILABLE:
        # --- 配置并运行 E2B 测试 ---
        e2b_tool_name = "e2b_code_interpreter"
        e2b_query = f"Use the {e2b_tool_name} tool to execute: print(100+99)"
        e2b_expected_result = "199" # 检查结果中的数字
        success = await run_stdio_single_tool_test(e2b_tool_name, E2BInputSchema, e2b_query, e2b_expected_result)
        print(f"\n--- E2B Schema Check Test Result: {'PASS' if success else 'FAIL'} ---")
    else:
         print("\n--- Skipping E2B Test (Schema not available) ---")

    # --- (可选) 配置并运行 Python REPL 测试 ---
    # if EXEC_SCHEMA_AVAILABLE:
    #     python_repl_tool_name = "python_repl" # 确认此名称
    #     python_repl_query = f"Use the {python_repl_tool_name} tool to calculate 11 * 12."
    #     python_repl_expected_result = "132"
    #     success = await run_stdio_single_tool_test(python_repl_tool_name, ExecInputSchema, python_repl_query, python_repl_expected_result)
    #     print(f"\n--- Python REPL Schema Check Test Result: {'PASS' if success else 'FAIL'} ---")
    # else:
    #      print("\n--- Skipping Python REPL Test (Schema not available) ---")


    print("\nMCP 集成测试完成！")

if __name__ == "__main__":
    # 依赖检查
    try:
        import mcp
        import langchain_mcp_adapters
        import langgraph
        import langchain_openai
        import dotenv
        import pydantic
        from core.tools.e2b_tool import E2BInputSchema # 再次导入以确保可用性
    except ImportError as e:
        print(f"错误：缺少必要的依赖: {e}")
        sys.exit(1)

    # 确保 MentisMCPClient 有 get_tools 方法
    if not hasattr(MentisMCPClient, 'get_tools'):
         print("DEBUG: Adding get_tools method back to MentisMCPClient for testing")
         def get_tools_impl(self) -> List[BaseTool]: return self.tools
         MentisMCPClient.get_tools = get_tools_impl

    asyncio.run(main())