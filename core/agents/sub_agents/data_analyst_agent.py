from typing import Any, Dict, List, Optional, Union, Callable, TypedDict, Type

from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from core.agents.base.react_agent import ReactAgent, AgentState
import re
import json
from datetime import datetime


class AnalysisResult(TypedDict):
    """Structured analysis result type"""
    type: str  # Type of analysis (statistical, predictive, exploratory, etc.)
    data: str  # Data description or reference
    result: str  # Analysis result or findings
    methodology: str  # Analysis methodology
    timestamp: str  # Creation timestamp


class DataAnalystAgent(ReactAgent):
    """Data Analyst agent implementation for data analysis and visualization tasks.

    Responsibilities:
    - Analyze data to extract meaningful insights
    - Create data visualizations to communicate findings
    - Perform statistical analysis and hypothesis testing
    - Identify patterns, trends, and anomalies in data
    - Provide data-driven recommendations

    Design Principles:
    - Maintain separation of prompt template from initialization logic
    - Enable flexible prompt customization through inheritance
    - Follow PEP8 style guidelines for multi-line strings
    - Store analysis results in structured format for better organization
    """

    _PROMPT_TEMPLATE = """{current_date}

You are a professional Data Analyst specialized in extracting insights from data and communicating findings through clear analysis and visualization.

## REACT Methodology for Data Analysis

### Response Guidelines:
- Run the appropriate tool first, then provide an in-depth analysis
- No need to ask follow-up questions, just present findings
- For stock analysis, discuss performance and trends in paragraphs
- Avoid showing any code; focus on insights

### Output Guidelines:
- Keep responses succinct unless more detail is requested
- Summarize key findings and recommendations
- Use paragraphs for clarity

Available tools:
{tools}
"""

    def __init__(
        self,
        name: str,
        model: LanguageModelLike,
        tools: Optional[List[BaseTool]] = None,
        prompt: Optional[Union[str, SystemMessage, Callable, Runnable]] = None,
        max_iterations: int = 5,
        cache_enabled: bool = True,
        response_format: Optional[Union[dict, Type[Any]]] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        store: Optional[BaseStore] = None,
        interrupt_before: Optional[List[str]] = None,
        interrupt_after: Optional[List[str]] = None,
        debug: bool = False,
        version: str = "v1",
    ):
        """Initialize a data analyst agent with customizable components.

        Args:
            name: Unique identifier for the agent instance.
            model: Language model for data analysis and insight generation.
            tools: Available toolset for analysis tasks (default: None).
            prompt: Custom instruction template (default: use class template).
            max_iterations: Maximum number of iterations (default: 5).
            cache_enabled: Whether to cache analysis results (default: True).
            response_format: Optional response format for structured output.
            checkpointer: Optional checkpoint saver for persisting agent state.
            store: Optional storage object for cross-thread data sharing.
            interrupt_before: Optional list of node names to interrupt before execution.
            interrupt_after: Optional list of node names to interrupt after execution.
            debug: Whether to enable debug mode.
            version: LangGraph version ("v1" or "v2").
        """
        # Import tools registry to get data analysis tools
        from core.tools.registry import get_tools_by_category, ToolCategory
        
        # Initialize tools list if None
        if tools is None:
            tools = []
            
        # Get all registered data analysis tools from the registry
        try:
            data_tools = get_tools_by_category(ToolCategory.CODE_INTERPRETER)
            
            # Add data analysis tools that aren't already in the tools list
            for data_tool in data_tools:
                if not any(tool.name == data_tool.name for tool in tools if hasattr(tool, "name")):
                    tools.append(data_tool)
                    if debug:
                        print(f"[{name}] Added data analysis tool: {data_tool.name}")
        except Exception as e:
            if debug:
                print(f"[{name}] Failed to get data analysis tools from registry: {str(e)}")
        
        # Get current date
        from core.utils.timezone import get_current_time
        current_date = get_current_time().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format prompt template with tools information
        formatted_prompt = self._PROMPT_TEMPLATE
        if tools:
            tools_str = "\n".join([f"- {tool.name}: {tool.description}" for tool in tools])
            formatted_prompt = formatted_prompt.format(current_date=current_date, tools=tools_str)
        else:
            formatted_prompt = formatted_prompt.format(current_date=current_date, tools="No tools available.")
        
        super().__init__(
            name=name,
            model=model,
            tools=tools or [],
            prompt=prompt or formatted_prompt,
            response_format=response_format,
            checkpointer=checkpointer,
            store=store,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
            debug=debug,
            version=version,
        )
        self.max_iterations = max_iterations
        self.cache_enabled = cache_enabled
        self._analysis_results = []  # Initialize analysis results list
        self._iteration_count = 0  # Current iteration count

    def add_analysis_result(self, type: str, data: str, result: str, methodology: str) -> None:
        """Add an analysis result.

        Args:
            type: The type of analysis (statistical, predictive, exploratory, etc.).
            data: Data description or reference.
            result: Analysis result or findings.
            methodology: Analysis methodology.

        Returns:
            None
        """
        timestamp = datetime.now().isoformat()
        analysis = AnalysisResult(
            type=type,
            data=data,
            result=result,
            methodology=methodology,
            timestamp=timestamp
        )
        self._analysis_results.append(analysis)
        
        # Increment iteration count
        self._iteration_count += 1

    def get_analysis_results(self, type: Optional[str] = None) -> List[AnalysisResult]:
        """Get analysis results, optionally filtered by type.

        Args:
            type: Optional type filter.

        Returns:
            List of analysis results.
        """
        if type:
            return [result for result in self._analysis_results if result["type"] == type]
        return self._analysis_results

    def get_latest_result(self) -> Optional[AnalysisResult]:
        """Get the most recently created analysis result.

        Returns:
            The latest analysis result or None if no results exist.
        """
        if not self._analysis_results:
            return None
        return self._analysis_results[-1]

    def clear_results(self) -> None:
        """Clear all stored analysis results.

        Returns:
            None
        """
        self._analysis_results = []
        self._iteration_count = 0

    def generate_analysis_report(self, title: str = "Data Analysis Report") -> str:
        """Generate a comprehensive report from all analysis results.

        Args:
            title: The title of the analysis report.

        Returns:
            A formatted report string.
        """
        if not self._analysis_results:
            return "No analysis results available."
            
        # Create report header
        report = f"# {title}\n\n"
        report += f"*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        
        # Add executive summary
        report += "## Executive Summary\n\n"
        report += "This report contains the following analyses:\n\n"
        
        # List all analysis types
        analysis_types = set(result["type"] for result in self._analysis_results)
        for analysis_type in analysis_types:
            report += f"- {analysis_type} analysis\n"
        report += "\n"
        
        # Group results by type
        for analysis_type in analysis_types:
            report += f"## {analysis_type.capitalize()} Analysis\n\n"
            
            # Add all results of this type
            type_results = [r for r in self._analysis_results if r["type"] == analysis_type]
            for i, result in enumerate(type_results, 1):
                report += f"### Analysis {i}: {result['data']}\n\n"
                report += f"**Methodology:** {result['methodology']}\n\n"
                report += f"**Findings:** {result['result']}\n\n"
        
        return report