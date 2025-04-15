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
# --- CORRECTED IMPORTS ---
# Import both Browser and the correct BrowserConfig from browser.py
from .browser.browser import Browser, BrowserConfig # <--- Import BOTH from the same place
# Remove the import from .browser.config if it exists

# Import LLM initializer
from .llm import initialize_llms

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Main Execution Logic ---
async def run_agent(task: str, config: Dict):
    """Initializes components and runs the agent graph."""

    load_dotenv() # Load environment variables from .env file

    # 1. Initialize Browser Configuration using the CORRECT dataclass BrowserConfig
    #    Pass only arguments defined in the dataclass version
    browser_config = BrowserConfig( # <--- Uses CORRECT imported BrowserConfig (dataclass)
        viewport_size=config.get("viewport"), # Viewport uses {"width": ..., "height": ...} dict
        cdp_url=config.get("cdp_url"),
        # Pass other relevant fields from the dataclass BrowserConfig if provided via config dict
        cv_model_endpoint=config.get("cv_model_endpoint"),
        sheets_model_endpoint=config.get("sheets_model_endpoint"),
        storage_state=config.get("storage_state"), # Add if needed/configurable
        # Note: headless is handled within Browser logic based on cdp_url
    )

    # 2. Initialize LLM Provider
    llm, llm_creative = initialize_llms()
    if llm is None:
        logger.error("Failed to initialize LLM. Exiting.")
        return {"error": "LLM Initialization failed. Check API keys, .env settings, and logs."}

    # 3. Initialize Browser Tool using the CORRECT Browser class
    #    Use async context manager for robust cleanup if Browser supports it, otherwise explicit init/close
    browser_tool = None
    try:
        browser_tool = Browser(config=browser_config) # <--- Uses CORRECT imported Browser
        # Call initialize explicitly as Browser class seems designed for it
        await browser_tool.initialize() # Ensure browser is ready

        # 4. Create the LangGraph App
        app = create_graph_app(browser=browser_tool, llm=llm)

        # 5. Define the initial state
        initial_state: AgentState = {
            "task": task,
            "browser_content": "", # Will be filled by the first node run
            "parsed_action": {},
            "history": [],
            "error": None,
        }

        # 6. Run the graph
        final_state = None
        logger.info(f"Starting agent execution for task: {task}")
        final_state = await app.ainvoke(initial_state, config={"recursion_limit": config.get("max_steps", 50)})
        logger.info("Agent execution finished.")

    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        return {"error": f"Agent execution failed: {e}"}
    finally:
        # 7. Clean up browser instance if it was initialized
        if browser_tool:
            await browser_tool.close()

    # 8. Process and return the result
    if final_state:
        if final_state.get("error"):
            logger.error(f"Agent finished with error: {final_state['error']}")
            return {"error": final_state['error']}
        elif final_state.get("parsed_action", {}).get("type") == "finish":
            result = final_state["parsed_action"].get("result", "Task finished, but no result extracted.")
            logger.info(f"Agent finished successfully. Result: {result}")
            return {"result": result}
        else:
            logger.warning("Agent finished without a 'finish' action or error.")
            final_action = final_state.get("parsed_action", {}).get("type", "N/A")
            return {"result": f"Agent stopped unexpectedly after action: {final_action}.", "final_state": final_state} # Provide more context
    else:
        return {"error": "Agent execution failed to produce a final state (likely due to earlier exception)."}


# --- Command Line Interface ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the LangGraph Browser Agent.")
    parser.add_argument("task", help="The task description for the agent.")
    # Browser args - should align with the DATACLASS BrowserConfig fields
    parser.add_argument("--cdp-url", help="CDP URL to connect to an existing browser.", default=None)
    parser.add_argument("--width", type=int, default=1200, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=900, help="Browser viewport height.")
    parser.add_argument("--cv-endpoint", help="CV Model Endpoint.", default=None)
    parser.add_argument("--sheets-endpoint", help="Sheets Model Endpoint.", default=None)
    # Add arg for storage_state if needed, might be complex via CLI (e.g., path to file)
    # parser.add_argument("--storage-state-path", help="Path to storage state JSON file.", default=None)

    # LLM args
    parser.add_argument("--llm-provider", help="Force LLM provider (e.g., openai, groq). Overrides .env LLM_PROVIDER.")
    parser.add_argument("--llm-model", help="Force LLM model name. Overrides .env LLM_MODEL_NAME.")
    parser.add_argument("--llm-base-url", help="Force LLM base URL for compatible APIs. Overrides .env LLM_BASE_URL.")
    parser.add_argument("--llm-api-key", help="Force LLM API key. Overrides .env LLM_API_KEY.")
    # Execution args
    parser.add_argument("--max-steps", type=int, default=50, help="Maximum number of steps (graph recursions).")

    args = parser.parse_args()

    # Prepare config dict for run_agent, matching BrowserConfig dataclass fields
    run_config = {
        "cdp_url": args.cdp_url,
        "viewport": {"width": args.width, "height": args.height},
        "max_steps": args.max_steps,
        "cv_model_endpoint": args.cv_endpoint,
        "sheets_model_endpoint": args.sheets_endpoint,
        # Add storage_state loading from path if implemented:
        # "storage_state": load_storage_state(args.storage_state_path) if args.storage_state_path else None,
    }

    # Set environment variables from args to override .env for LLM init
    if args.llm_provider: os.environ['LLM_PROVIDER'] = args.llm_provider
    if args.llm_model: os.environ['LLM_MODEL_NAME'] = args.llm_model
    if args.llm_base_url: os.environ['LLM_BASE_URL'] = args.llm_base_url
    if args.llm_api_key: os.environ['LLM_API_KEY'] = args.llm_api_key

    # Run the async function
    result = asyncio.run(run_agent(args.task, run_config))

    print("\n--- Agent Result ---")
    # (Result printing logic remains the same)
    if isinstance(result, dict):
        if "result" in result:
            print(f"Result: {result['result']}")
        if "error" in result:
             print(f"Error: {result['error']}")
        if "final_state" in result and "result" not in result and "error" not in result:
             # Limited printing of final state for brevity
             print(f"Final State (Debug): Keys={list(result['final_state'].keys())}")
             # print(f"Final State (debug): {result['final_state']}") # Uncomment for full state
    else:
         print(f"Output (unexpected format): {result}")