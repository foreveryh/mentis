# reason_graph/handoff.py
# (Paste the code user provided for handoff.py here)
import re
import uuid
from typing import List, Tuple # Import Tuple

from langchain_core.messages import AIMessage, ToolCall, ToolMessage, BaseMessage # Import BaseMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import Annotated

WHITESPACE_RE = re.compile(r"\s+")

def _normalize_agent_name(agent_name: str) -> str:
    """Normalize an agent name to be used inside the tool name."""
    if not agent_name: return "unknown_agent"
    return WHITESPACE_RE.sub("_", agent_name.strip()).lower()

# Note: The original code uses @tool decorator which requires function arguments.
# To inject state, the decorated function needs the Annotated state argument.
# Let's define the function first and then apply the decorator, or use functools.partial.
# Using the function approach first for clarity.

def _handoff_to_agent_implementation(
    state: Annotated[dict, InjectedState], # Inject state here
    tool_call_id: Annotated[str, InjectedToolCallId], # Inject tool_call_id
    target_agent_name: str, # Pass the target agent name
    tool_name: str # Pass the specific tool name for the ToolMessage
) -> Command:
    """Ask another agent for help. This is the core logic."""
    # Create the ToolMessage confirming the handoff BEFORE generating the Command
    """Handoff 核心逻辑，添加日志"""
    print(f"\n--- DEBUG: Entering _handoff_to_agent_implementation ---")
    print(f"  - Target Agent: {target_agent_name}")
    print(f"  - Tool Name: {tool_name}")
    print(f"  - Tool Call ID: {tool_call_id}")
    # print(f"  - Current State Keys: {list(state.keys())}") # 可选：打印状态键
    tool_message = ToolMessage(
        content=f"Okay, handing off to {target_agent_name}. The current state and task context have been passed.",
        name=tool_name,
        tool_call_id=tool_call_id,
    )
    print(f"  - Created ToolMessage: ID={tool_message.tool_call_id}, Name={tool_message.name}")
    # The Command tells LangGraph to route to the target agent node
    # It also includes the ToolMessage in the state update for the next step
    command_obj = Command(
        goto=target_agent_name,
        # graph=Command.PARENT, # PARENT is default, usually not needed unless nested graphs
        update={"messages": [tool_message]}, # Return only the NEW message to be added
    )
    print(f"  - Created Command: goto='{command_obj.goto}', update contains {len(command_obj.update.get('messages',[]))} message(s)")
    print(f"--- DEBUG: Exiting _handoff_to_agent_implementation ---")
    return command_obj

def create_handoff_tool(*, agent_name: str) -> BaseTool:
    """Create a tool that can handoff control to the requested agent."""
    if not agent_name:
         raise ValueError("agent_name cannot be empty for create_handoff_tool")

    normalized_name = _normalize_agent_name(agent_name)
    tool_name = f"transfer_to_{normalized_name}"

    # Use functools.partial to fix the target_agent_name and tool_name arguments
    import functools
    specific_handoff_logic = functools.partial(
        _handoff_to_agent_implementation,
        target_agent_name=agent_name,
        tool_name=tool_name
    )

    # Decorate the partial function
    # The arguments 'state' and 'tool_call_id' will be automatically injected by LangGraph
    # when the tool is called due to the Annotations used in _handoff_to_agent_implementation
    @tool(tool_name)
    def handoff_tool_wrapper(
         state: Annotated[dict, InjectedState],
         tool_call_id: Annotated[str, InjectedToolCallId]
     ) -> Command:
        """Dynamically generated tool description: Ask the '{agent_name}' agent for help with the current task or question."""
        # --- 添加 Debug 日志 ---
        print(f"\n--- DEBUG: Handoff Tool '{tool_name}' (wrapper) CALLED ---")
        # ---
        return specific_handoff_logic(state=state, tool_call_id=tool_call_id) # type: ignore

    # Set a more descriptive description
    handoff_tool_wrapper.description = f"Use this tool to delegate the current task or ask a question to the '{agent_name}' agent. Pass the necessary context or instructions in your reasoning before calling this tool."

    return handoff_tool_wrapper


def create_handoff_back_messages(
    agent_name: str, supervisor_name: str
) -> Tuple[AIMessage, ToolMessage]:
    """Create a pair of (AIMessage, ToolMessage) to add to the message history when returning control to the supervisor."""
    tool_call_id = str(uuid.uuid4())
    # Although no tool exists for transferring back, we simulate the pattern
    # The AIMessage signals intent, the ToolMessage confirms the transition occurred in the graph logic
    simulated_tool_name = f"transfer_back_to_{_normalize_agent_name(supervisor_name)}"

    # The AIMessage contains the *final output* of the sub-agent in its content field
    # It should also indicate the intent to hand back, though the graph logic forces this anyway.
    # The content here is just a placeholder - the actual content comes from the agent's final response.
    ai_message_content = f"Task completed. Transferring back to {supervisor_name}."

    # We still generate a ToolCall structure for consistency in the AIMessage, even if no real tool is called on supervisor side for hand-back.
    tool_calls = [ToolCall(name=simulated_tool_name, args={}, id=tool_call_id)]

    # Create the AIMessage - crucial to include the sub-agent's name
    ai_message = AIMessage(
            content=ai_message_content, # Placeholder - see note below
            tool_calls=tool_calls,
            name=agent_name, # Identify which agent is responding
        )

    # The ToolMessage confirms the transition happened from the graph's perspective
    tool_message = ToolMessage(
            content=f"Successfully transferred back to {supervisor_name} from {agent_name}.",
            name=simulated_tool_name,
            tool_call_id=tool_call_id,
        )

    # IMPORTANT NOTE: The `_make_call_agent` helper function should populate the
    # `ai_message.content` with the *actual* final response message(s) from the sub-agent,
    # replacing the placeholder content above. It keeps the tool_calls structure.
    # The code provided for `_make_call_agent` seems to handle extracting `output['messages']`.
    # We need to ensure it correctly structures the AIMessage part of the tuple returned here.
    # Let's refine create_handoff_back_messages to just create the ToolMessage,
    # as the AIMessage content comes from the sub-agent's actual final output.

    # Refined approach: _make_call_agent gets the final AI response, we only need the ToolMessage here?
    # No, the pattern expects both. Let's assume _make_call_agent takes the *last* message from the
    # sub-agent's output and packages it into this AIMessage structure.

    return ai_message, tool_message # Return both for the standard pattern