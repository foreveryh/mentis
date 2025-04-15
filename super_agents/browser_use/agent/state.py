# super_agents/browser_use/agent/state.py
from typing import Dict, List, Optional, Any, TypedDict

# Define the state structure using TypedDict for type hinting
class AgentState(TypedDict, total=False):
    """
    TypedDict representing the state of the browser agent during execution.
    
    Attributes:
        task: The user task description
        browser_content: The current HTML content of the browser
        parsed_action: The last action parsed from LLM response
        history: List of previous actions taken
        error: Any error message from the last operation
    """
    task: str
    browser_content: str
    parsed_action: Dict[str, Any]
    history: List[str]
    error: Optional[str]
