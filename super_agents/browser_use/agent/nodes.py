# super_agents/browser_use/agent/nodes.py
import asyncio
import logging
from typing import Dict, Any, Optional

# --- LangChain Core Import for Type Hint ---
from langchain_core.runnables.base import RunnableSerializable # <--- Import this

from .state import AgentState
from .schemas import (
    BaseAction, LLMResponse
)
from .prompts import create_agent_prompt
# --- CORRECTED LLM IMPORT ---
# Import only the necessary functions/classes that actually exist in llm.py
from ..llm import generate_structured_output # <--- Removed LLMProvider from import

# Import the correct Browser from the browser subdirectory
from ..browser.browser import Browser

logger = logging.getLogger(__name__)

# --- Class to hold nodes and dependencies ---
class AgentNodes:
    """Encapsulates agent nodes and their dependencies (browser, llm)."""
    # --- CORRECTED TYPE HINT for llm ---
    def __init__(self, browser: Browser, llm: RunnableSerializable): # <--- Use RunnableSerializable
        if not isinstance(llm, RunnableSerializable):
             logger.warning(f"LLM instance provided to AgentNodes is not of type RunnableSerializable (actual type: {type(llm)}).")
        self.browser = browser
        self.llm = llm
        logger.info("AgentNodes initialized with browser and llm instances.")

    # --- Node method implementations remain the same ---
    async def get_browser_state(self, state: AgentState) -> Dict[str, Any]:
        """Node method to get the current state of the browser page."""
        logger.info("Node: get_browser_state")
        try:
            content = await self.browser.get_content()
            return {"browser_content": content, "error": None}
        except Exception as e:
            logger.error(f"Error getting browser state: {e}", exc_info=True)
            return {"error": f"Failed to get browser state: {e}"}

    async def plan_action(self, state: AgentState) -> Dict[str, Any]:
        """Node method to decide the next action using the LLM's structured output."""
        logger.info("Node: plan_action")
        if state.get("error"):
            logger.warning(f"Planning action with existing error: {state['error']}")

        prompt = create_agent_prompt(
            task=state["task"],
            current_browser_content=state["browser_content"],
            history=state.get("history", []),
            error_message=state.get("error")
        )
        system_message = "You are an AI agent controlling a web browser. Respond with the single next action formatted as JSON matching the required schema."

        try:
            llm_response: Optional[LLMResponse] = await generate_structured_output(
                model=self.llm, # Pass the llm instance
                schema=LLMResponse,
                prompt=prompt,
                system_message=system_message
            )

            if llm_response and isinstance(llm_response, LLMResponse):
                parsed_action_model: BaseAction = llm_response.action
                parsed_action_dict = parsed_action_model.dict()
                logger.info(f"LLM proposed action: {parsed_action_dict.get('type', 'unknown')}")
                return {"parsed_action": parsed_action_dict, "error": None}
            else:
                logger.error("Failed to get valid structured output from LLM.")
                error_action_dict = {"type": "error", "message": "Failed to get valid structured output from LLM."}
                return {"parsed_action": error_action_dict, "error": "LLM did not return valid structured output."}

        except Exception as e:
            logger.error(f"Error during structured action planning: {e}", exc_info=True)
            error_action_dict = {"type": "error", "message": f"LLM planning exception: {e}"}
            return {"parsed_action": error_action_dict, "error": f"LLM planning exception: {e}"}


    async def execute_action(self, state: AgentState) -> Dict[str, Any]:
        """Node method to execute the action dictionary from the state."""
        logger.info("Node: execute_action")
        action_dict = state.get("parsed_action")
        history = state.get("history", [])

        if not action_dict or not isinstance(action_dict, dict) or "type" not in action_dict:
            error_msg = "No valid action dictionary provided to execute."
            logger.error(error_msg)
            return {"error": error_msg}

        action_type = action_dict.get("type")
        action_repr = f"Action: {action_type}, Details: { {k:v for k,v in action_dict.items() if k != 'type'} }"
        logger.info(f"Executing {action_repr}")

        new_history = history + [action_repr]

        try:
            if action_type == "navigate":
                await self.browser.navigate_to(action_dict["url"]) # Check if method name/args match Browser class
            elif action_type == "click":
                 await self.browser.click(action_dict["selector"]) # Check Browser class for click method/args
            elif action_type == "type":
                  await self.browser.type(action_dict["selector"], action_dict["text"]) # Check Browser class for type method/args
            elif action_type == "scroll":
                  await self.browser.scroll(action_dict["direction"]) # Check Browser class for scroll method/args
            elif action_type == "wait":
                  await self.browser.wait(action_dict["milliseconds"]) # Check Browser class for wait method/args
            elif action_type == "get_content":
                 logger.info("Action 'get_content' requested (will be handled by next cycle)")
                 pass
            elif action_type == "finish":
                logger.info(f"Action 'finish' received. Result: {action_dict.get('result')}")
                pass
            elif action_type == "error":
                 error_msg = action_dict.get("message", "LLM signaled an error.")
                 logger.error(f"Executing 'error' action from LLM: {error_msg}")
                 return {"error": error_msg, "history": new_history}
            else:
                error_msg = f"Attempted to execute unknown/unhandled action type: {action_type}"
                logger.error(error_msg)
                return {"error": error_msg, "history": new_history}

            return {"error": None, "history": new_history}

        except Exception as e:
            logger.error(f"Error executing action '{action_type}': {e}", exc_info=True)
            return {"error": f"Failed to execute action '{action_type}': {e}", "history": new_history}