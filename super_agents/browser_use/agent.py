# super_agents/browser_use/agent.py
"""
Agent API for browser-based task execution.
Provides a simplified interface similar to the original implementation.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from .agent.graph import create_graph_app
from .agent.state import AgentState
from .browser.browser import Browser
from .browser.config import BrowserConfig
from .llm import initialize_llms

logger = logging.getLogger(__name__)

class Agent:
    """
    Agent class that provides a simple interface for browser automation with LLM.
    
    This implementation is similar to the original API but uses the current
    browser automation stack with LangGraph.
    """
    
    def __init__(
        self, 
        llm=None,
        browser_config: Optional[BrowserConfig] = None,
        max_steps: int = 50
    ):
        """
        Initialize the Agent with optional LLM and browser configuration.
        
        Args:
            llm: LLM instance to use (if None, will initialize from environment)
            browser_config: Browser configuration options
            max_steps: Maximum number of steps the agent can take
        """
        self.browser_config = browser_config or BrowserConfig()
        self.llm = llm
        self.max_steps = max_steps
        self.browser = None
        self._app = None
    
    async def _initialize(self):
        """Initialize the browser and LLM if not already initialized."""
        # Initialize LLM if not provided
        if self.llm is None:
            logger.info("Initializing LLM from environment variables")
            self.llm, _ = initialize_llms()
            
        if self.llm is None:
            raise ValueError("Failed to initialize LLM. Check API keys and .env settings.")
        
        # Initialize browser
        self.browser = Browser(config=self.browser_config)
        await self.browser.initialize()
        
        # Initialize LangGraph app
        self._app = create_graph_app(browser=self.browser, llm=self.llm)
    
    async def run(self, prompt: str) -> Dict[str, Any]:
        """
        Run the agent with the given prompt/task.
        
        Args:
            prompt: The task description or prompt for the agent
        
        Returns:
            Dictionary containing the execution result
        """
        # Ensure initialization
        if self.browser is None or self._app is None:
            await self._initialize()
        
        # Define the initial state
        initial_state = AgentState(
            task=prompt,
            browser_content="",
            parsed_action={},
            history=[],
            error=None
        )
        
        # Run the graph
        logger.info(f"Starting agent execution for task: {prompt}")
        try:
            final_state = await self._app.ainvoke(
                initial_state, 
                config={"recursion_limit": self.max_steps}
            )
            
            # Process result
            if final_state.get("error"):
                logger.error(f"Agent finished with error: {final_state['error']}")
                return {"result": f"Error: {final_state['error']}", "success": False}
            elif final_state.get("parsed_action", {}).get("type") == "finish":
                result = final_state["parsed_action"].get("result", "Task finished, but no result extracted.")
                logger.info(f"Agent finished successfully. Result: {result}")
                return {"result": result, "success": True}
            else:
                logger.warning("Agent finished without a 'finish' action or error.")
                return {
                    "result": "Agent stopped without producing a final answer.", 
                    "success": False,
                    "state": final_state
                }
                
        except Exception as e:
            logger.error(f"Agent execution failed: {e}", exc_info=True)
            return {"result": f"Error during execution: {str(e)}", "success": False}
        finally:
            # Clean up resources
            if self.browser:
                await self.browser.close()
                self.browser = None
            self._app = None
    
    def __del__(self):
        """Ensure resources are cleaned up."""
        if self.browser:
            asyncio.create_task(self.browser.close())


# Provider classes for compatibility with original API
class OpenAIProvider:
    """OpenAI provider compatible with the interface"""
    
    def __init__(self, model="gpt-4o-mini", api_key=None, temperature=0.1):
        """
        Initialize OpenAI provider.
        
        Args:
            model: Model name to use
            api_key: OpenAI API key (if None, will use from environment)
            temperature: Temperature for generation
        """
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        
        # These parameters will be used by initialize_llms() internally
        import os
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
        os.environ["LLM_PROVIDER"] = "openai"
        os.environ["LLM_MODEL_NAME"] = model
        os.environ["LLM_TEMPERATURE"] = str(temperature)


class AnthropicProvider:
    """Anthropic provider compatible with the interface"""
    
    def __init__(self, model="claude-3-opus-20240229", api_key=None, temperature=0.1, 
                 enable_thinking=False, thinking_token_budget=None):
        """
        Initialize Anthropic provider.
        
        Args:
            model: Model name to use
            api_key: Anthropic API key (if None, will use from environment)
            temperature: Temperature for generation
            enable_thinking: Enable thinking step (not fully supported in current implementation)
            thinking_token_budget: Tokens for thinking (not fully supported)
        """
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.enable_thinking = enable_thinking
        self.thinking_token_budget = thinking_token_budget
        
        # These parameters will be used by initialize_llms() internally
        import os
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        os.environ["LLM_PROVIDER"] = "anthropic" 
        os.environ["LLM_MODEL_NAME"] = model
        os.environ["LLM_TEMPERATURE"] = str(temperature)


# Add convenience imports to __init__.py
# This will allow: from super_agents.browser_use import Agent, OpenAIProvider, BrowserConfig
