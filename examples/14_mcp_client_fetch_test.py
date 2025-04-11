import os
import sys
import asyncio
import traceback
from typing import Dict, Optional, Type

from dotenv import load_dotenv

# 在这里添加项目根目录到路径，方便导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage

try:
    from pydantic.v1 import BaseModel, Field
except ImportError:
    from pydantic import BaseModel, Field  # type: ignore

from core.mcp.client import MCPClient
from core.mcp.config_loader import load_config, MCPConfig, StdioConfig
from core.llm.llm_manager import LLMManager

try:
    from mcp.types import CallToolRequest
    CALL_TOOL_REQ_AVAILABLE = True
except ImportError:
    CallToolRequest = None
    CALL_TOOL_REQ_AVAILABLE = False

# 这是唯一保留的 fetch schema
try:
    class FetchInputSchema(BaseModel):
        url: str = Field(..., description="URL to fetch")
        max_length: Optional[int] = Field(default=5000)
        start_index: Optional[int] = Field(default=0)
        raw: Optional[bool] = Field(default=False)
    FETCH_SCHEMA_AVAILABLE = True
except Exception:
    FetchInputSchema = None
    FETCH_SCHEMA_AVAILABLE = False

CENTRAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "mcp", "mcp_server_config.json")
LLM_ID_FOR_TESTING = "openai_gpt4o_mini"
llm_manager = LLMManager()

class MCPToolRunner(BaseTool):
    name: str = "needs_override"
    description: str = "needs_override"
    args_schema: Optional[Type[BaseModel]] = None

    client: MCPClient = Field(exclude=True)

    class Config:
        arbitrary_types_allowed = True

    async def _arun(self, **kwargs) -> str:
        if not self.client or not self.client.session:
            return f"ERROR: MCP Client session inactive for {self.name}."
        if not CALL_TOOL_REQ_AVAILABLE:
            return "ERROR: CallToolRequest unavailable."

        try:
            print(f"    [_arun:{self.name}] Sending MCP request with args: {kwargs}")
            result_message = await asyncio.wait_for(
                self.client.session.call_tool(self.name, kwargs),
                timeout=120.0
            )
            # 简化: 只检查 result 和 error
            if hasattr(result_message, "result"):
                return str(result_message.result)
            elif hasattr(result_message, "error"):
                return f"Tool Error: {result_message.error.message}"
            else:
                return "Unknown response"
        except asyncio.TimeoutError:
            return "Error: Timeout."
        except Exception as e:
            return f"Error: {e}\n{traceback.format_exc()}"

    def _run(self, **kwargs) -> str:
        print(f"    [_run:{self.name}] Running async method via asyncio.run()...")
        try:
            return asyncio.run(self._arun(**kwargs))
        except Exception as e:
            return f"Error in sync wrapper: {e}"

async def run_fetch_test(server_config_key: str, all_configs: Dict[str, MCPConfig]):
    print(f"\n=== Running STDIO BaseTool Test for Server '{server_config_key}' (Tool: 'fetch') ===")
    if not FETCH_SCHEMA_AVAILABLE:
        print("ERROR: Fetch Schema missing.")
        return False
    if not CALL_TOOL_REQ_AVAILABLE:
        print("ERROR: CallToolRequest unavailable.")
        return False

    server_config = all_configs.get(server_config_key)
    if not server_config:
        print(f"ERROR: Config for '{server_config_key}' not found.")
        return False
    if not isinstance(server_config.connection, StdioConfig):
        print(f"ERROR: Config '{server_config_key}' not STDIO.")
        return False

    try:
        model = llm_manager.get_model(LLM_ID_FOR_TESTING)
        print(f"Using LLM: {getattr(model, 'model_name', LLM_ID_FOR_TESTING)}")
    except ValueError as e:
        print(f"获取 LLM 出错: {e}.")
        return False

    test_success = False
    async with MCPClient(server_config) as client:
        if not client.session:
            print("ERROR: MCP session not established!")
            return False

        try:
            runner = MCPToolRunner(
                client=client,
                name="fetch",
                description="Fetches URL content as markdown.",
                args_schema=FetchInputSchema
            )
            tools = [runner]
        except Exception as e_inst:
            print(f"ERROR: Failed to instantiate MCPToolRunner: {e_inst}")
            return False

        agent = create_react_agent(model, tools)
        query = (
            "Use the fetch tool to get the content of https://www.google.com "
            "and tell me its title (first 50 chars)."
        )
        print(f"\nQuery: {query}")

        try:
            response = await asyncio.wait_for(
                agent.ainvoke({"messages": [{"role": "user", "content": query}]}),
                timeout=180.0
            )
            print(f"\nAgent Final Response:")
            if response and "messages" in response and response["messages"]:
                response_content = response["messages"][-1].content
                print(response_content)
                if "google" in response_content.lower():
                    print("\n✅ Test PASS")
                    test_success = True
                else:
                    print("\n❌ Test FAIL (title not found)")
                    test_success = False
            else:
                print("No valid response from agent.")
                test_success = False
        except Exception as e:
            print(f"Exception: {e}")
            test_success = False

    return test_success

async def main():
    print("Starting a simplified MCP Integration Test for 'fetch_via_uvx' only...")
    try:
        all_configs = load_config(CENTRAL_CONFIG_PATH)
        print(f"Loaded {len(all_configs)} server configs.")
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    # 只测试 fetch_via_uvx
    result = await run_fetch_test("fetch_via_uvx", all_configs)
    if result:
        print("\nALL GOOD: 'fetch' test passed.")
    else:
        print("\nTEST FAILED: 'fetch' test didn't pass.")
    print("Done.")

if __name__ == "__main__":
    asyncio.run(main())