# Refactored coder_agent.py
from typing import Any, List, Optional, Union, Callable, Type
from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import SystemMessage
from langgraph.types import Checkpointer

from core.agents.base.react_agent import ReactAgent
from core.tools.registry import get_tools_by_category, ToolCategory, get_tool_instance # Import get_tool_instance

import logging
logger = logging.getLogger(__name__)

class CoderAgent(ReactAgent):
    """
    Coder Agent (Refactored)
    - Interacts with a sandboxed Linux environment via code execution tools.
    """

    def __init__(
        self,
        name: str = "coder_expert",
        model: LanguageModelLike = None,
        tools: Optional[List[Union[BaseTool, Callable]]] = None,
        checkpointer: Optional[Checkpointer] = None,
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = 100000, # Coding might need more context
        **kwargs
    ):
        # 1. Define Description
        description = "Writes, executes, tests, and debugs Python code and Linux shell commands within a secure sandboxed environment. Can install packages, manage files, and interact with the network."

        # 2. Get Tools from Registry
        agent_tools = []
        default_tool_name = "e2b_code_interpreter" # Expected tool name
        try:
            code_tools = get_tools_by_category(ToolCategory.CODE_INTERPRETER) + get_tools_by_category(ToolCategory.FILE_SYSTEM)

            agent_tools.extend(code_tools)
            # Optionally add file system tools if not included in interpreter tool
            # fs_tools = get_tools_by_category(ToolCategory.FILE_SYSTEM)
            # agent_tools.extend(fs_tools)
            print(f"[{name}] Loaded tools from registry: {[t.name for t in agent_tools if hasattr(t,'name')]}")
            # Verify the main execution tool is present
            if not any(getattr(t,'name', None) == default_tool_name for t in agent_tools):
                 print(f"CRITICAL Warning: CoderAgent '{name}' is missing the primary '{default_tool_name}' tool!")
                 # Attempt to get it specifically if missing?
                 specific_tool = get_tool_instance(default_tool_name)
                 if specific_tool: agent_tools.append(specific_tool)

        except Exception as e:
             print(f"Warning: Failed to get tools from registry for {name}: {e}")

        if tools: # Merge extra tools
             existing_names = {t.name for t in agent_tools if hasattr(t,'name')}
             agent_tools.extend([t for t in tools if getattr(t, 'name', None) not in existing_names])

        if not agent_tools:
             print(f"CRITICAL Warning: CoderAgent '{name}' initialized with NO tools!")

        # 3. Define System Prompt (using the capabilities)
        tool_name_for_prompt = next((t.name for t in agent_tools if hasattr(t, 'name') and 'code' in t.name.lower()), default_tool_name) # Try to get actual tool name

        base_prompt = f"""You are an expert Coder Agent interacting with a secure, sandboxed Linux environment provided by the '{tool_name_for_prompt}' tool. Your goal is to fulfill coding, file manipulation, or shell command requests by generating and executing appropriate code or commands within this sandbox.

Available Tools:
{self._format_tools_for_prompt(agent_tools)}
- **{tool_name_for_prompt}**: Executes Python code or shell commands within the sandboxed Linux environment. Returns stdout, stderr, execution errors, and potentially file outputs or structured results (like image data). To run shell commands, generate Python code that uses the 'subprocess' module OR if the tool directly supports it, prefix the command with '!'. Always prefer generating Python code for complex shell operations or when needing output capture.

Key Capabilities of the Sandbox Environment (via the tool):
- Execute Python 3 code.
- Install Python packages using pip (generate code like `import subprocess; subprocess.run(['pip', 'install', 'requests'], check=True)`).
- Run standard Linux shell commands (e.g., `ls`, `pwd`, `mkdir`, `curl`, `git`, etc. using Python's subprocess).
- Access and manipulate a persistent filesystem within the sandbox (typically starting in `/home/user/` or `/`). Create, read, write, delete files and directories.
- Access the internet from within the sandbox for tasks like cloning repos or fetching data.

Workflow & Instructions:
1.  **Analyze Request**: Understand the goal, constraints, and required inputs/outputs.
2.  **Plan Steps**: Outline the necessary code or commands. Consider file paths, dependencies, and error handling.
3.  **Generate Code/Command**: Write the Python code or shell command sequence needed. For non-trivial Python, include comments.
4.  **Execute using Tool**: Prepare the arguments for the '{tool_name_for_prompt}' tool (usually the code string or command string) and invoke the tool.
5.  **Analyze Output**: Carefully review the stdout, stderr, errors, and any results returned by the tool.
6.  **Debug/Iterate**: If errors occurred or the output is not as expected, analyze the error, revise the code/command, and execute again using the tool.
7.  **Final Output**: Once the task is successfully completed, provide the final working code (if relevant), a summary of the execution results (stdout/stderr highlights), confirmation of file operations, and any requested explanation. If the task cannot be completed, explain why.
8.  **File Handling**: If generating files (code, data, images), clearly state the full path within the sandbox where the file was saved (e.g., `/home/user/my_script.py`, `/home/user/output.csv`). Do not attempt to display images directly in your response.

Focus strictly on tasks achievable within the sandboxed environment using the provided tool. Be precise and careful with file paths and commands.
"""

        # 4. Call super().__init__
        super().__init__(
            name=name,
            model=model,
            tools=agent_tools,
            prompt=base_prompt,
            description=description,
            checkpointer=checkpointer,
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            **kwargs
        )
        print(f"CoderAgent '{self.name}' initialized with tools: {[t.name for t in self.tools if hasattr(t,'name')]}")

    # Inherits _format_tools_for_prompt and other methods from BaseAgent/ReactAgent