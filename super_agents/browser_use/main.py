# super_agents/browser_use/main.py
import asyncio
import argparse
import logging
import os
from typing import Dict
from dotenv import load_dotenv

# Import components
from .agent.graph import create_graph_app
from .agent.state import AgentState
# Import CORRECT Browser and BrowserConfig from browser.browser
from .browser.browser import Browser, BrowserConfig
# Import LLM initializer and type hint
from .llm import initialize_llms, RunnableSerializable

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Main Execution Logic ---
async def run_agent(task: str, config: Dict):
    """Initializes components and runs the agent graph."""

    load_dotenv()

    # 1. Initialize Browser Configuration (Removed CV/Sheets endpoints)
    browser_config = BrowserConfig( # <--- Uses CORRECT imported BrowserConfig
        viewport_size=config.get("viewport"),
        cdp_url=config.get("cdp_url"),
        storage_state=config.get("storage_state"), # Keep if storage_state is still in your BrowserConfig
        # cv_model_endpoint=config.get("cv_model_endpoint"), # <--- REMOVED
        # sheets_model_endpoint=config.get("sheets_model_endpoint"), # <--- REMOVED
    )

    # 2. Initialize ONLY the Planning LLM Provider
    llm, _ = initialize_llms() # Use _ to ignore creative llm if not needed
    if llm is None:
        logger.error("Failed to initialize planning LLM. Exiting.")
        return {"error": "Planning LLM Initialization failed."}

    # 3. Initialize Browser Tool (No longer needs vlm passed)
    browser_tool = None
    try:
        # Detector is now initialized internally by Browser using env vars
        browser_tool = Browser(config=browser_config)
        await browser_tool.initialize()

        # 4. Create the LangGraph App
        app = create_graph_app(browser=browser_tool, llm=llm)

        # 5. Define the initial state
        initial_state: AgentState = {
            "task": task, "browser_content": "", "parsed_action": {}, "history": [], "error": None,
        }

        # 6. Run the graph
        final_state = None
        logger.info(f"Starting agent execution for task: {task}")
        final_state = await app.ainvoke(initial_state, config={"recursion_limit": config.get("max_steps", 50)})
        logger.info("Agent execution finished.")

    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        # Ensure error is propagated
        return {"error": f"Agent execution failed: {e}"}
    finally:
        # 7. Clean up browser instance
        if browser_tool:
            await browser_tool.close()

    # 8. Process and return the result
    if final_state:
         if final_state.get("error"):
             logger.error(f"Agent finished with error: {final_state['error']}")
             return {"error": final_state['error']}
         elif final_state.get("parsed_action", {}).get("type") == "finish":
             result = final_state["parsed_action"].get("result", "Task finished.")
             logger.info(f"Agent finished successfully. Result: {result}")
             return {"result": result}
         else:
             logger.warning("Agent finished without a 'finish' action or error.")
             final_action = final_state.get("parsed_action", {}).get("type", "N/A")
             return {"result": f"Agent stopped unexpectedly after action: {final_action}.", "final_state": final_state}
    else:
         # This case typically means an exception occurred before final state was reached
         # The error should have been returned from the except block
         return {"error": "Agent execution failed to produce a final state (likely due to earlier exception)."}


# --- Command Line Interface ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the LangGraph Browser Agent.")
    parser.add_argument("task", help="The task description for the agent.")
    # Browser args (Align with updated BrowserConfig)
    parser.add_argument("--cdp-url", help="CDP URL.", default=None)
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=900)
    # REMOVED CV/Sheets Endpoint Args
    # parser.add_argument("--cv-endpoint", help="CV Model Endpoint.", default=None)
    # parser.add_argument("--sheets-endpoint", help="Sheets Model Endpoint.", default=None)
    # Add storage state path if needed
    # parser.add_argument("--storage-state-path", help="Path to storage state JSON file.", default=None)

    # Planning LLM args (Optional overrides for .env)
    parser.add_argument("--llm-provider", help="Force planning LLM provider.")
    parser.add_argument("--llm-model", help="Force planning LLM model name.")
    parser.add_argument("--llm-api-key", help="Force planning LLM API key (uses LLM_API_KEY env var).")
    parser.add_argument("--llm-base-url", help="Force planning LLM base URL.")

    # REMOVED VLM specific CLI args

    # Execution args
    parser.add_argument("--max-steps", type=int, default=50)

    args = parser.parse_args()

    # Prepare config dict for run_agent (Browser config + max_steps)
    run_config = {
        "cdp_url": args.cdp_url,
        "viewport": {"width": args.width, "height": args.height},
        "max_steps": args.max_steps,
        # Load storage state from path if implemented
        # "storage_state": load_storage_state(args.storage_state_path) if args.storage_state_path else None,
        # REMOVED cv/sheets endpoints from config passed to run_agent
    }

    # Set environment variables for planning LLM if args provided
    if args.llm_provider: os.environ['LLM_PROVIDER'] = args.llm_provider
    if args.llm_model: os.environ['LLM_MODEL_NAME'] = args.llm_model
    if args.llm_api_key: os.environ['LLM_API_KEY'] = args.llm_api_key # Set generic key
    if args.llm_base_url: os.environ['LLM_BASE_URL'] = args.llm_base_url
    # VLM config now solely relies on VLM_* env vars read by Detector/ChatOpenRouter

    # Run the async function
    result = asyncio.run(run_agent(args.task, run_config))

    # Print result
    print("\n--- Agent Result ---")
    if isinstance(result, dict):
        if "result" in result: print(f"Result: {result['result']}")
        if "error" in result: print(f"Error: {result['error']}")
        if "final_state" in result and "result" not in result and "error" not in result:
             # Limited printing of final state for brevity
             print(f"Final State (Debug): Keys={list(result['final_state'].keys())}")
    else:
         print(f"Output (unexpected format): {result}")