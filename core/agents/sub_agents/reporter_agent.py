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


class ReportSection(TypedDict):
    """Structured report section type"""
    title: str  # Section title
    content: str  # Section content
    sources: List[str]  # Sources for the information
    timestamp: str  # Creation timestamp


class ReporterAgent(ReactAgent):
    """Reporter agent implementation for information gathering and report generation tasks.

    Responsibilities:
    - Gather information from various sources
    - Organize information into structured reports
    - Summarize complex data into digestible formats
    - Create clear and concise narratives
    - Ensure factual accuracy and proper citation

    Design Principles:
    - Maintain separation of prompt template from initialization logic
    - Enable flexible prompt customization through inheritance
    - Follow PEP8 style guidelines for multi-line strings
    - Store report sections in structured format for better organization
    """

    _PROMPT_TEMPLATE = """{current_date}

You are a professional Reporter specialized in gathering information and creating comprehensive, well-structured reports.

## REACT Methodology for Reporting

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
        """Initialize a reporter agent with customizable components.

        Args:
            name: Unique identifier for the agent instance.
            model: Language model for information gathering and report generation.
            tools: Available toolset for reporting tasks (default: None).
            prompt: Custom instruction template (default: use class template).
            max_iterations: Maximum number of iterations (default: 5).
            cache_enabled: Whether to cache report sections (default: True).
            response_format: Optional response format for structured output.
            checkpointer: Optional checkpoint saver for persisting agent state.
            store: Optional storage object for cross-thread data sharing.
            interrupt_before: Optional list of node names to interrupt before execution.
            interrupt_after: Optional list of node names to interrupt after execution.
            debug: Whether to enable debug mode.
            version: LangGraph version ("v1" or "v2").
        """
        # Check if tavily_search is in tools, if not try to import and add it
        from langchain_community.tools.tavily_search import TavilySearchResults
        
        # Initialize tools list if None
        if tools is None:
            tools = []
            
        # Check if tavily_search is already in tools
        has_tavily = any(tool.name == "tavily_search" for tool in tools if hasattr(tool, "name"))
        
        # Add tavily_search if not present
        if not has_tavily:
            try:
                tavily_search = TavilySearchResults()
                tools.append(tavily_search)
            except Exception as e:
                if debug:
                    print(f"[{name}] Failed to initialize Tavily search tool: {str(e)}")
        
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
            tools=tools,
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
        self._report_sections = []  # Initialize report sections list
        self._iteration_count = 0  # Current iteration count

    def add_report_section(self, title: str, content: str, sources: List[str]) -> None:
        """Add a section to the report.

        Args:
            title: The title of the section.
            content: The content of the section.
            sources: List of sources for the information.

        Returns:
            None
        """
        timestamp = datetime.now().isoformat()
        section = ReportSection(
            title=title,
            content=content,
            sources=sources,
            timestamp=timestamp
        )
        self._report_sections.append(section)
        
        # Increment iteration count
        self._iteration_count += 1

    def get_report_sections(self, title: Optional[str] = None) -> List[ReportSection]:
        """Get report sections, optionally filtered by title.

        Args:
            title: Optional title filter.

        Returns:
            List of report sections.
        """
        if title:
            return [section for section in self._report_sections if section["title"] == title]
        return self._report_sections

    def get_latest_section(self) -> Optional[ReportSection]:
        """Get the most recently created report section.

        Returns:
            The latest report section or None if no sections exist.
        """
        if not self._report_sections:
            return None
        return self._report_sections[-1]

    def clear_sections(self) -> None:
        """Clear all stored report sections.

        Returns:
            None
        """
        self._report_sections = []
        self._iteration_count = 0

    def generate_full_report(self, title: str = "Comprehensive Report") -> str:
        """Generate a full report from all stored sections.

        Args:
            title: The title of the full report.

        Returns:
            A formatted report string.
        """
        if not self._report_sections:
            return "No report sections available."
            
        # Create report header
        report = f"# {title}\n\n"
        report += f"*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        
        # Add executive summary if available
        summary_sections = [s for s in self._report_sections if "summary" in s["title"].lower()]
        if summary_sections:
            report += "## Executive Summary\n\n"
            report += summary_sections[0]["content"] + "\n\n"
        
        # Add all other sections
        for section in self._report_sections:
            if "summary" not in section["title"].lower():
                report += f"## {section['title']}\n\n"
                report += section["content"] + "\n\n"
        
        # Add sources/references
        all_sources = []
        for section in self._report_sections:
            all_sources.extend(section["sources"])
        
        # Remove duplicates while preserving order
        unique_sources = []
        for source in all_sources:
            if source not in unique_sources:
                unique_sources.append(source)
        
        if unique_sources:
            report += "## References\n\n"
            for i, source in enumerate(unique_sources, 1):
                report += f"{i}. {source}\n"
        
        return report