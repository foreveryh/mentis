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


class SearchResult(TypedDict):
    """Structured search result type"""
    query: str  # Search query
    result: str  # Search result
    timestamp: str  # Search timestamp
    source: str  # Search source/tool


class ResearchAgent(ReactAgent):
    """Research agent implementation for complex information gathering tasks.

    Responsibilities:
    - Execute multi-round search queries with context awareness
    - Track search history to avoid repetitive searches
    - Cache search results for efficient information retrieval
    - Synthesize information from multiple sources
    - Limit API calls through intelligent query planning

    Design Principles:
    - Maintain separation of prompt template from initialization logic
    - Enable flexible prompt customization through inheritance
    - Follow PEP8 style guidelines for multi-line strings
    - Store search history in structured format for better tracking
    """

    _PROMPT_TEMPLATE = """{current_date}

You are a professional Research Analyst specialized in analyzing complex problems and providing in-depth insights. Your primary focus is on conducting thorough research with proper citations and evidence-based analysis.

## REACT Methodology for Research

Key Responsibilities:
- Conduct comprehensive research using available tools
- Support findings with credible citations and sources
- Provide detailed analysis with evidence-based reasoning
- Structure responses with clear sections and logical flow
- Synthesize information from multiple sources
- Evaluate source reliability and research limitations
- Make the response as long as possible, do not skip any important details

Guidelines for Research Output:
- Begin with a clear introduction of the research topic
- Organize findings into well-structured sections
- Include 2-4 detailed paragraphs per section
- Support key claims with multiple sources
- Use proper citation format: [Source](URL)
- Place citations immediately after relevant statements
- Conclude with synthesis and key insights
- Consider both academic and contemporary sources
- CITATIONS SHOULD BE ON EVERYTHING YOU SAY

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
        """Initialize a research agent with customizable components.

        Args:
            name: Unique identifier for the agent instance.
            model: Language model for decision making and analysis.
            tools: Available toolset for research tasks (default: None).
            prompt: Custom instruction template (default: use class template).
            max_iterations: Maximum number of search iterations (default: 5).
            cache_enabled: Whether to cache search results (default: True).
            response_format: Optional response format for structured output.
            checkpointer: Optional checkpoint saver for persisting agent state.
            store: Optional storage object for cross-thread data sharing.
            interrupt_before: Optional list of node names to interrupt before execution.
            interrupt_after: Optional list of node names to interrupt after execution.
            debug: Whether to enable debug mode.
            version: LangGraph version ("v1" or "v2").
        """
        # Import tools registry to get search tools
        from core.tools.registry import get_tools_by_category, ToolCategory
        
        # Initialize tools list if None
        if tools is None:
            tools = []
            
        # Get all registered search tools from the registry
        try:
            search_tools = get_tools_by_category(ToolCategory.SEARCH)
            
            # Add search tools that aren't already in the tools list
            for search_tool in search_tools:
                if not any(tool.name == search_tool.name for tool in tools if hasattr(tool, "name")):
                    tools.append(search_tool)
                    if debug:
                        print(f"[{name}] Added search tool: {search_tool.name}")
        except Exception as e:
            if debug:
                print(f"[{name}] Failed to get search tools from registry: {str(e)}")
        
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
        self._search_history = []  # Initialize search history list
        self._iteration_count = 0  # Current iteration count
        self._search_cache = {}  # Search cache dictionary

    def record_search(self, query: str, result: str, source: str) -> None:
        """Record a search query and its result in the search history.

        Args:
            query: The search query.
            result: The search result.
            source: The source or tool used for the search.

        Returns:
            None
        """
        timestamp = datetime.now().isoformat()
        search_record = SearchResult(
            query=query,
            result=result,
            timestamp=timestamp,
            source=source
        )
        self._search_history.append(search_record)
        
        # If caching is enabled, add the result to the cache
        if self.cache_enabled:
            self._search_cache[query] = result
        
        # Increment iteration count
        self._iteration_count += 1

    def get_search_history(self, format_type: str = "text") -> str:
        """Get the search history in the specified format.

        Args:
            format_type: The format type, either "text" or "json" (default: "text").

        Returns:
            The search history in the specified format.
        """
        if not self._search_history:
            return "No search history available."

        if format_type.lower() == "json":
            return json.dumps(self._search_history, indent=2)
        else:
            # Text format
            history_text = "Search History:\n"
            for i, record in enumerate(self._search_history):
                history_text += f"\n{i+1}. Query: {record['query']}\n"
                history_text += f"   Source: {record['source']}\n"
                history_text += f"   Time: {record['timestamp']}\n"
                # Limit result length to avoid excessively long output
                result_preview = record['result'][:200] + "..." if len(record['result']) > 200 else record['result']
                history_text += f"   Result: {result_preview}\n"
            return history_text

    def get_cached_result(self, query: str) -> Optional[str]:
        """Get a cached search result for a query if available.

        Args:
            query: The search query.

        Returns:
            The cached result or None if not found.
        """
        if not self.cache_enabled:
            return None
            
        # Try exact match
        if query in self._search_cache:
            return self._search_cache[query]
            
        # Try fuzzy matching (if query is a subset of another query)
        for cached_query, result in self._search_cache.items():
            if query.lower() in cached_query.lower() or cached_query.lower() in query.lower():
                return result
                
        return None

    def clear_history(self) -> None:
        """Clear the search history and reset the iteration count.

        Returns:
            None
        """
        self._search_history = []
        self._iteration_count = 0

    def clear_cache(self) -> None:
        """Clear the search cache.

        Returns:
            None
        """
        self._search_cache = {}

    def has_reached_limit(self) -> bool:
        """Check if the agent has reached the maximum number of iterations.

        Returns:
            True if the maximum number of iterations has been reached, False otherwise.
        """
        return self._iteration_count >= self.max_iterations

    def reset(self) -> None:
        """Reset the agent's state, including search history and cache.

        Returns:
            None
        """
        super().reset()
        self.clear_history()
        self.clear_cache()
        
    # def invoke(self, state: AgentState, config: Optional[Dict[str, Any]] = None) -> AgentState:
    #     """Override invoke method to add iteration limit check and auto-reset.
        
    #     Args:
    #         state: The current state of the agent.
    #         config: Optional configuration for the agent.
            
    #     Returns:
    #         The updated state after agent execution.
    #     """
    #     # Check if iteration limit has been reached
    #     if self.has_reached_limit():
    #         if self.debug:
    #             print(f"[{self.name}] Maximum iterations {self.max_iterations} reached, automatically resetting state")
    #         self.reset()
            
    #     try:
    #         return self._agent.invoke(state, config)
    #     except RecursionError as e:
    #         error_msg = f"[{self.name}] Recursion depth exceeded error: {str(e)}. State automatically reset."
    #         print(error_msg)
    #         self.reset()
    #         return {"error": error_msg, "messages": state.get("messages", [])}
    #     except Exception as e:
    #         error_msg = f"[{self.name}] Execution error: {str(e)}"
    #         print(error_msg)
    #         return {"error": error_msg, "messages": state.get("messages", [])}
            
    # async def ainvoke(self, state: AgentState, config: Optional[Dict[str, Any]] = None) -> AgentState:
    #     """Override ainvoke method to add iteration limit check and auto-reset.
        
    #     Args:
    #         state: The current state of the agent.
    #         config: Optional configuration for the agent.
            
    #     Returns:
    #         The updated state after agent execution.
    #     """
    #     # Check if iteration limit has been reached
    #     if self.has_reached_limit():
    #         if self.debug:
    #             print(f"[{self.name}] Maximum iterations {self.max_iterations} reached, automatically resetting state")
    #         self.reset()
            
    #     try:
    #         return await self._agent.ainvoke(state, config)
    #     except RecursionError as e:
    #         error_msg = f"[{self.name}] Recursion depth exceeded error: {str(e)}. State automatically reset."
    #         print(error_msg)
    #         self.reset()
    #         return {"error": error_msg, "messages": state.get("messages", [])}
    #     except Exception as e:
    #         error_msg = f"[{self.name}] Execution error: {str(e)}"
    #         print(error_msg)
    #         return {"error": error_msg, "messages": state.get("messages", [])}