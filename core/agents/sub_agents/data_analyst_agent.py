# data_analyst_agent.py (or in main.py)

from typing import Any, List, Optional, Union, Callable, Type
from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_core.messages import SystemMessage
from langgraph.types import Checkpointer

# Internal imports - ensure paths are correct
from core.agents.base.react_agent import ReactAgent
from core.tools.registry import get_tools_by_category, ToolCategory, get_tool_instance # Import necessary functions

import logging
logger = logging.getLogger(__name__)

# Assume ToolCategory.CODE_INTERPRETER exists
# Assume ToolCategory.FILE_SYSTEM exists if needed

class DataAnalystAgent(ReactAgent):
    """
    Data Analyst Agent (Refactored)
    - Focuses on analyzing structured data using code execution sandbox.
    - Generates insights and saves visualizations to files.
    """

    def __init__(
        self,
        name: str = "data_analyst_expert",
        model: LanguageModelLike = None,
        tools: Optional[List[Union[BaseTool, Callable]]] = None,
        checkpointer: Optional[Checkpointer] = None,
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = 120000, # Analysis might need decent context
        debug: bool = False,
        **kwargs
    ):
        # 1. Define Description for Supervisor
        description = "Analyzes structured data (provided in context or potentially read from sandbox files) using Python (Pandas, NumPy, Matplotlib, Seaborn) within a secure code execution environment. Performs statistical analysis, identifies trends, generates insights, and creates data visualizations (saved as files in the sandbox)."

        # 2. Get Tools from Registry
        agent_tools = []
        default_tool_name = "e2b_code_interpreter" # Tool needed for execution
        try:
            # Primarily needs Code Interpreter
            code_tools = get_tools_by_category(ToolCategory.CODE_INTERPRETER) + get_tools_by_category(ToolCategory.FILE_SYSTEM) # 需要代码和文件工具

            agent_tools.extend(code_tools)
            # Optionally, add File System tools if needed to read data files
            # fs_tools = get_tools_by_category(ToolCategory.FILE_SYSTEM)
            # agent_tools.extend(fs_tools)
            print(f"[{name}] Loaded tools from registry: {[t.name for t in agent_tools if hasattr(t,'name')]}")
            # Verify the main execution tool is present
            if not any(getattr(t,'name', None) == default_tool_name for t in agent_tools):
                 print(f"CRITICAL Warning: DataAnalystAgent '{name}' is missing the primary '{default_tool_name}' tool!")
                 specific_tool = get_tool_instance(default_tool_name)
                 if specific_tool: agent_tools.append(specific_tool)

        except Exception as e:
             print(f"Warning: Failed to get tools from registry for {name}: {e}")

        if tools: # Merge extra tools
             existing_names = {t.name for t in agent_tools if hasattr(t,'name')}
             agent_tools.extend([t for t in tools if getattr(t, 'name', None) not in existing_names])

        if not agent_tools:
             print(f"CRITICAL Warning: DataAnalystAgent '{name}' initialized with NO execution tools!")

        # 3. Define System Prompt
        tool_name_for_prompt = next((t.name for t in agent_tools if hasattr(t, 'name') and 'code' in t.name.lower()), default_tool_name)

        base_prompt = f"""You are an expert Data Analyst. Your task is to analyze data using Python code within a secure sandbox environment accessed via the '{tool_name_for_prompt}' tool. Libraries like Pandas, NumPy, Matplotlib, and Seaborn are available (install if needed using pip in your code).

Available Tools:
{self._format_tools_for_prompt(agent_tools)}
- **{tool_name_for_prompt}**: Executes Python code in the sandbox. Returns stdout, stderr, errors, and potentially structured results.

Key Instructions:
1.  **Understand Data & Goal**: Identify the data source (likely provided in previous messages or mentioned as a sandbox file path like '/home/user/data.csv') and the specific analysis question or goal.
2.  **Plan Analysis**: Briefly outline the Python code steps (e.g., load data into Pandas DataFrame, clean/transform data, perform calculations, generate plot).
3.  **Write Python Code**: Generate the necessary Python code. Use libraries effectively. Import necessary libraries (e.g., `import pandas as pd`, `import matplotlib.pyplot as plt`).
4.  **Handle Files (If Needed)**: If reading/writing files within the sandbox, use standard Python file I/O within your code (e.g., `pd.read_csv('/home/user/data.csv')`, `df.to_csv('/home/user/output.csv')`).
5.  **Handle Visualizations**: If asked to create plots:
    * Generate the plot using Matplotlib/Seaborn.
    * **MUST save the plot to a file** inside the sandbox (e.g., `/home/user/plots/my_plot.png`). Use `plt.savefig('/home/user/plots/my_plot.png')`. Create directories if necessary (`os.makedirs('/home/user/plots', exist_ok=True)`).
    * Use `plt.show()` or `plt.close()` after saving to clear the plot buffer.
    * **DO NOT attempt to return image data directly.** Images cannot be displayed in the response.
    * In your response, **state that the plot was generated and provide the full path** where it was saved in the sandbox (e.g., "I have generated a scatter plot and saved it to /home/user/plots/scatter_plot.png").
6.  **Execute Code**: Use the '{tool_name_for_prompt}' tool to run your complete Python script.
7.  **Analyze Results**: Interpret the output (stdout, numerical results, errors) from the tool execution.
8.  **Present Findings**: Summarize your analysis and findings clearly. Use Markdown tables for structured data if helpful. Mention any plots saved and their paths. If errors occurred, explain them.
9.  **Focus**: Concentrate on data analysis using code execution. Do not perform web searches unless specifically instructed and given tools for it.
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
            debug=debug,
            **kwargs
        )
        print(f"DataAnalystAgent '{self.name}' initialized.")

    # Inherits _format_tools_for_prompt and other methods