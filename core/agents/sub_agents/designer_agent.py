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


class DesignProposal(TypedDict):
    """Structured design proposal type"""
    title: str  # Proposal title
    description: str  # Proposal description
    elements: List[str]  # Design elements
    rationale: str  # Design rationale
    timestamp: str  # Creation timestamp


class DesignerAgent(ReactAgent):
    """Designer agent implementation for UI/UX design and visual communication tasks.

    Responsibilities:
    - Create user interface designs and mockups
    - Develop visual identity and branding elements
    - Ensure consistent design language across applications
    - Optimize user experience and interface usability
    - Provide design recommendations based on best practices

    Design Principles:
    - Maintain separation of prompt template from initialization logic
    - Enable flexible prompt customization through inheritance
    - Follow PEP8 style guidelines for multi-line strings
    - Store design proposals in structured format for better organization
    """

    _PROMPT_TEMPLATE = """{current_date}

You are a professional UI/UX Designer specialized in creating intuitive, accessible, and visually appealing designs.

## REACT Methodology for Design

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
        """Initialize a designer agent with customizable components.

        Args:
            name: Unique identifier for the agent instance.
            model: Language model for design generation and evaluation.
            tools: Available toolset for design tasks (default: None).
            prompt: Custom instruction template (default: use class template).
            max_iterations: Maximum number of iterations (default: 5).
            cache_enabled: Whether to cache design proposals (default: True).
            response_format: Optional response format for structured output.
            checkpointer: Optional checkpoint saver for persisting agent state.
            store: Optional storage object for cross-thread data sharing.
            interrupt_before: Optional list of node names to interrupt before execution.
            interrupt_after: Optional list of node names to interrupt after execution.
            debug: Whether to enable debug mode.
            version: LangGraph version ("v1" or "v2").
        """
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
        self._design_proposals = []  # Initialize design proposals list
        self._iteration_count = 0  # Current iteration count

    def add_design_proposal(self, title: str, description: str, elements: List[str], rationale: str) -> None:
        """Add a design proposal.

        Args:
            title: The title of the design proposal.
            description: Description of the design proposal.
            elements: List of design elements.
            rationale: Design rationale explaining the choices made.

        Returns:
            None
        """
        timestamp = datetime.now().isoformat()
        proposal = DesignProposal(
            title=title,
            description=description,
            elements=elements,
            rationale=rationale,
            timestamp=timestamp
        )
        self._design_proposals.append(proposal)
        
        # Increment iteration count
        self._iteration_count += 1

    def get_design_proposals(self, title: Optional[str] = None) -> List[DesignProposal]:
        """Get design proposals, optionally filtered by title.

        Args:
            title: Optional title filter.

        Returns:
            List of design proposals.
        """
        if title:
            return [proposal for proposal in self._design_proposals if proposal["title"] == title]
        return self._design_proposals

    def get_latest_proposal(self) -> Optional[DesignProposal]:
        """Get the most recently created design proposal.

        Returns:
            The latest design proposal or None if no proposals exist.
        """
        if not self._design_proposals:
            return None
        return self._design_proposals[-1]

    def clear_proposals(self) -> None:
        """Clear all stored design proposals.

        Returns:
            None
        """
        self._design_proposals = []
        self._iteration_count = 0

    def generate_design_document(self, title: str = "Design Documentation") -> str:
        """Generate a comprehensive design document from all proposals.

        Args:
            title: The title of the design document.

        Returns:
            A formatted design document string.
        """
        if not self._design_proposals:
            return "No design proposals available."
            
        # Create document header
        document = f"# {title}\n\n"
        document += f"*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        
        # Add executive summary
        document += "## Overview\n\n"
        document += "This document contains the following design proposals:\n\n"
        
        # List all proposals
        for i, proposal in enumerate(self._design_proposals, 1):
            document += f"{i}. {proposal['title']}\n"
        document += "\n"
        
        # Add detailed proposals
        for i, proposal in enumerate(self._design_proposals, 1):
            document += f"## {i}. {proposal['title']}\n\n"
            document += f"### Description\n\n{proposal['description']}\n\n"
            
            document += "### Design Elements\n\n"
            for j, element in enumerate(proposal['elements'], 1):
                document += f"{j}. {element}\n"
            document += "\n"
            
            document += f"### Design Rationale\n\n{proposal['rationale']}\n\n"
        
        return document