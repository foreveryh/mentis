# super_agents/browser_use/agent/schemas.py
from typing import Literal, Optional, Union, List, Dict, Any, Type
# Use Pydantic V2+ if installed, otherwise V1 syntax
try:
    from pydantic.v1 import BaseModel, Field
except ImportError:
    from pydantic import BaseModel, Field # Fallback to V2

# --- Action Type ---
ActionTypeLiteral = Literal[
    "navigate",
    "click",
    "type",
    "scroll",
    "wait",
    "get_content",
    "finish",
    "error"
]

# --- Pydantic Schemas for Actions ---
# Using Pydantic allows for better validation and compatibility
# with LangChain's structured output features.

class BaseAction(BaseModel):
    """Base schema for all actions, containing the type."""
    type: ActionTypeLiteral = Field(..., description="The type of action to perform.")

class NavigateAction(BaseAction):
    type: Literal["navigate"] = "navigate"
    url: str = Field(..., description="The URL to navigate to.")

class ClickAction(BaseAction):
    type: Literal["click"] = "click"
    selector: str = Field(..., description="CSS selector for the element to click.")
    description: Optional[str] = Field(None, description="Optional description of the element being clicked.")

class TypeAction(BaseAction):
    type: Literal["type"] = "type"
    selector: str = Field(..., description="CSS selector for the input field.")
    text: str = Field(..., description="The text to type into the field.")
    description: Optional[str] = Field(None, description="Optional description of the element being typed into.")

class ScrollAction(BaseAction):
    type: Literal["scroll"] = "scroll"
    direction: Literal["up", "down", "left", "right"] = Field(..., description="The direction to scroll the page.")
    # selector: Optional[str] = Field(None, description="Optional CSS selector of element to scroll within.") # Add if needed

class WaitAction(BaseAction):
    type: Literal["wait"] = "wait"
    milliseconds: int = Field(..., description="Duration to wait in milliseconds.")

class GetContentAction(BaseAction):
    type: Literal["get_content"] = "get_content"
    # No extra fields needed, just signifies intent to refresh state
    description: Optional[str] = Field("Requesting updated browser content", description="Reason for requesting content.")

class FinishAction(BaseAction):
    type: Literal["finish"] = "finish"
    result: str = Field(..., description="The final answer or summary of the completed task.")

class ErrorAction(BaseAction):
    type: Literal["error"] = "error"
    message: str = Field(..., description="Description of the error encountered or signaled by the LLM.")

# --- Union for Parsing ---
# LangChain's with_structured_output often works best when targeting a single Pydantic model
# that uses discriminated unions (if available in your Pydantic version) or by prompting
# the LLM clearly to only output ONE type of action JSON matching the base structure.
# For simplicity here, we define the *expected output structure* the LLM should generate.
# The parsing function might need refinement based on how the LLM structures the output.

# Define the overall structure the LLM should output, which includes one of the actions.
# This structure helps `with_structured_output`.
class LLMResponse(BaseModel):
    action: Union[
        NavigateAction,
        ClickAction,
        TypeAction,
        ScrollAction,
        WaitAction,
        GetContentAction,
        FinishAction,
        ErrorAction
    ] = Field(..., description="The specific action determined by the LLM.")

# --- Parsing Function (Placeholder/Example) ---
# The `generate_structured_output` function in llm.py now handles the parsing
# directly into the Pydantic schema (LLMResponse).
# So, we might not need a separate manual parsing function here if using that.

# If you need manual parsing from raw text (less reliable):
# def parse_llm_response_manual(response: str) -> Optional[BaseAction]:
#     # ... (complex logic using regex or JSON parsing as in previous example)
#     # This would return one of the action models (NavigateAction, ClickAction, etc.)
#     pass
