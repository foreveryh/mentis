# super_agents/browser_use/agent/graph.py
import logging
from typing import Dict, Any

from langchain_core.runnables.base import RunnableSerializable
from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import AgentNodes
from ..browser.browser import Browser

logger = logging.getLogger(__name__)

NODE_GET_BROWSER_STATE = "get_browser_state"
NODE_PLAN_ACTION = "plan_action"
NODE_EXECUTE_ACTION = "execute_action"

# --- UPDATED Conditional Edge Logic ---
def should_end(state: AgentState) -> bool:
    """Determines if the graph should end."""
    action = state.get("parsed_action", {})
    action_type = action.get("type")
    error_occurred = state.get("error") is not None # Check if execute_action reported an error

    # End if the LLM planned action is 'finish' or 'error'
    if action_type == "finish":
        logger.info("Graph execution: 'finish' action planned. Ending.")
        return True
    if action_type == "error":
        # Log the error message from the action payload
        logger.error(f"Graph execution: 'error' action planned by LLM: {action.get('message', 'Unknown error')}. Ending.")
        return True

    # End if the execute_action node reported an error in the state
    # Note: Depending on desired behavior, you might want to retry instead of ending on execution errors
    # if error_occurred:
    #     logger.error(f"Graph execution: Error occurred during execution: {state['error']}. Ending.")
    #     return True # Uncomment this line if ANY execution error should terminate the graph

    return False # Continue otherwise

def create_graph_app(browser: Browser, llm: RunnableSerializable):
    """
    Creates the LangGraph application using class-based nodes.
    """
    agent_nodes = AgentNodes(browser=browser, llm=llm)
    workflow = StateGraph(AgentState)

    workflow.add_node(NODE_GET_BROWSER_STATE, agent_nodes.get_browser_state)
    workflow.add_node(NODE_PLAN_ACTION, agent_nodes.plan_action)
    workflow.add_node(NODE_EXECUTE_ACTION, agent_nodes.execute_action)

    workflow.set_entry_point(NODE_GET_BROWSER_STATE)
    workflow.add_edge(NODE_GET_BROWSER_STATE, NODE_PLAN_ACTION)
    workflow.add_edge(NODE_PLAN_ACTION, NODE_EXECUTE_ACTION)

    # After executing action, decide whether to end or loop back
    workflow.add_conditional_edges(
        NODE_EXECUTE_ACTION,
        # Function to decide the next step based on the state *after* execution
        lambda state: END if should_end(state) else NODE_GET_BROWSER_STATE,
        {
            END: END,
            NODE_GET_BROWSER_STATE: NODE_GET_BROWSER_STATE
        }
    )

    logger.info("Compiling LangGraph workflow...")
    app = workflow.compile()
    logger.info("LangGraph workflow compiled successfully.")
    return app