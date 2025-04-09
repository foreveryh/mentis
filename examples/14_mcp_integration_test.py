# examples/14_mcp_integration_test.py (Pure Client Test - Checks Loaded Schema)
import os
import sys
import asyncio
import json # For schema printing
from dotenv import load_dotenv
import traceback
from typing import List, Dict, Any, Optional, Type

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv() # Load .env file for API Keys and LangSmith config

# --- LangChain/LangGraph Imports ---
from langchain_openai import ChatOpenAI # Using OpenAI for agent reliability
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage, AIMessage

# --- MCP and Local Code Imports ---
# Use the client version with AsyncExitStack and fixed imports
from core.mcp.client import MentisMCPClient
from core.llm.llm_manager import LLMManager
# Import Pydantic for schema checking
try: from pydantic.v1 import BaseModel as BaseModelV1
except ImportError: from pydantic import BaseModel as BaseModelV1

# --- Configuration ---
# !! 重要：确保这个 URL 和端口与你手动启动的服务器匹配 !!
MCP_SERVER_SSE_URL = "http://localhost:8000/sse"
# 选用一个在工具调用格式方面比较可靠的 LLM
# (确保你的 .env 文件中有对应的 API Key 并且 Quota 正常)
LLM_ID_FOR_TESTING = "deepseek_v3"
# ---

llm_manager = LLMManager()

async def run_agent_query(agent: Any, query: str, test_name: str, expected_result_part: Optional[str] = None) -> bool:
    """Helper function to run a query with the agent and report result."""
    print(f"\n--- Running Query for Test: '{test_name}' ---")
    print(f"Query: {query}")
    test_passed = False
    try:
        response = await asyncio.wait_for(
            agent.ainvoke({"messages": [{"role": "user", "content": query}]}),
            timeout=180.0 # Give more time for complex tasks/LLM calls
        )
        print(f"\nAgent Final Response ({test_name}):")
        if response and "messages" in response and response["messages"]:
             response_content = response["messages"][-1].content; print(response_content)
             # Check for common error phrases from the agent or underlying tools
             contains_error = ("error" in response_content.lower() or
                             "fail" in response_content.lower() or
                             "issue" in response_content.lower() or
                             "apologi" in response_content.lower() or
                             "unable" in response_content.lower() or
                             "cannot" in response_content.lower() or
                             "sorry" in response_content.lower())
             contains_expected = expected_result_part and expected_result_part in response_content

             if not contains_error and (expected_result_part is None or contains_expected):
                  print(f"✅ Test '{test_name}': PASS (No errors reported, expected result '{expected_result_part}' found if applicable).")
                  test_passed = True
             else:
                  print(f"❌ Test '{test_name}': FAIL (Agent reported error or expected result '{expected_result_part}' not found).")
                  test_passed = False
        else: print("Agent returned no valid response."); test_passed = False
    except asyncio.TimeoutError: print(f"Agent execution timed out for '{test_name}'"); test_passed = False
    except Exception as e: print(f"Agent execution failed for '{test_name}': {e}"); print(f"Traceback:\n{traceback.format_exc()}"); test_passed = False
    print(f"--- Test '{test_name}' finished. ---")
    return test_passed


async def main():
    """Main test function"""
    print("Starting MCP Client Test Script...")
    print("="*30)
    print("!!! IMPORTANT !!!")
    print("Please ensure the MCP server is already running.")
    print("Example command (run in a separate terminal):")
    print(f"  python core/mcp/run_server.py --transport sse --host 0.0.0.0 --port {MCP_SERVER_SSE_URL.split(':')[-1].split('/')[0]} --debug")
    print(f"Client will connect to: {MCP_SERVER_SSE_URL}")
    print("Make sure necessary API keys (OpenAI, E2B, Tavily, etc.) are set in the server's environment.")
    print("Enable LangSmith environment variables for detailed agent tracing.")
    print("="*30 + "\n")

    # --- Initialize LLM ---
    try:
        model = llm_manager.get_model(LLM_ID_FOR_TESTING)
        print(f"Using LLM: {getattr(model, 'model_name', LLM_ID_FOR_TESTING)}")
    except ValueError as e:
        print(f"FATAL: Error getting LLM '{LLM_ID_FOR_TESTING}': {e}. Cannot proceed."); return

    client = MentisMCPClient()
    all_tests_passed = True
    results = {}

    try:
        # --- Connect and Load Tools (Using the potentially faulty adapter) ---
        print(f"Attempting to connect to server at {MCP_SERVER_SSE_URL}...")
        # connect_sse internally calls load_mcp_tools and prints schema diagnostics
        loaded_tools = await client.connect_sse(url=MCP_SERVER_SSE_URL)

        if not loaded_tools:
             print("\n❌ CRITICAL FAIL: Failed to load any tools from the server via load_mcp_tools.")
             print("   This likely means the server isn't running, the URL is wrong, OR")
             print("   the server failed to advertise any tools via ListToolsRequest.")
             print("   (Check the server's terminal output for errors during startup/registration)")
             return # Cannot proceed without tools

        print(f"\nSuccessfully loaded {len(loaded_tools)} tools using load_mcp_tools.")
        print("Review the 'Args Schema' printed above for each tool carefully.")
        print("If they show {'kwargs': ...} instead of the tool's real arguments,")
        print("then the langchain-mcp-adapters library is the problem.")
        print("-" * 30)

        # --- Create Agent using loaded (potentially faulty schema) tools ---
        # We proceed with the agent test even if schemas look wrong,
        # to see if the agent fails as expected.
        print("\nCreating Agent with loaded tools...")
        # Using create_react_agent. If issues persist, try create_openai_tools_agent
        agent = create_react_agent(model, loaded_tools)
        print("Agent created.")
        print("-" * 30)

        # --- Run Test Queries ---

        # Test 1: Simple Calculation (Try Python REPL)
        py_repl_name = "riza_exec_python" # Confirm this name is registered
        py_repl_query = f"Calculate 19 + 53 using the {py_repl_name} tool."
        py_repl_expected = "72"
        results['Python REPL'] = await run_agent_query(agent, py_repl_query, "Python REPL", py_repl_expected)
        if not results['Python REPL']: all_tests_passed = False

        # Test 2: Web Search (Try Tavily)
        tavily_name = "tavily_search_results_json" # Confirm this name
        tavily_query = f"What is the main purpose of the MCP protocol? Use the {tavily_name} tool."
        tavily_expected = "protocol" # Check for keyword
        print("\nINFO: Running Tavily test - Ensure TAVILY_API_KEY is set.")
        results['Tavily Search'] = await run_agent_query(agent, tavily_query, "Tavily Search", tavily_expected)
        if not results['Tavily Search']: all_tests_passed = False

        # Test 3: Code Execution (Try E2B)
        e2b_name = "e2b_code_interpreter" # Confirm this name
        e2b_query = f"Execute this python code using {e2b_name}: print('Hello from E2B!')"
        e2b_expected = "Hello from E2B!"
        print("\nINFO: Running E2B test - Ensure E2B_API_KEY is set.")
        results['E2B Code Exec'] = await run_agent_query(agent, e2b_query, "E2B Code Exec", e2b_expected)
        if not results['E2B Code Exec']: all_tests_passed = False

        # Add more tests for other tools if desired...

    except Exception as e:
        print(f"\nFATAL ERROR during client connection or testing: {e}")
        print(traceback.format_exc())
        all_tests_passed = False # Mark failure
    finally:
        # Ensure client is closed even on error
        if client:
            print("\nClosing MCP Client...")
            await client.close()
            print("MCP Client Closed.")

    # --- Final Summary ---
    print("\n" + "="*20 + " FINAL TEST SUMMARY (Using load_mcp_tools) " + "="*20);
    for test_name, passed in results.items(): print(f"  {test_name}: {'PASS' if passed else 'FAIL'}")
    print("-" * (42 + len(" FINAL TEST SUMMARY (Using load_mcp_tools) ")))
    if all_tests_passed: print("✅✅✅ All attempted tests PASSED! The issue might be resolved or wasn't triggered. ✅✅✅")
    else: print("❌❌❌ One or more tests FAILED! Review Agent responses and server logs. Check printed Args Schemas above - if they show {'kwargs':...}, the adapter is likely the cause. ❌❌❌")
    print("="*20 + " MCP Integration Test Finished " + "="*20)


if __name__ == "__main__":
    # Dependency checks
    print("--- Dependency Check ---")
    # ... (keep checks, ensure CallToolRequest check added if needed elsewhere) ...
    print("------------------------")
    asyncio.run(main())