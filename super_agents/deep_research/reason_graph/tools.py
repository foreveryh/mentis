# reason_graph/tools.py

import os
import json
import time
import re
import asyncio
from datetime import datetime
from typing import Optional, List, Literal, Dict, Any, Tuple, Set # <--- 添加 Tuple, Set

# --- Environment Variable Loading ---
from dotenv import load_dotenv
load_dotenv()

# --- Pydantic & LangChain Core ---
from pydantic import BaseModel # Use Pydantic V2
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.base import RunnableSerializable # Type hint for LLM
from langchain_openai import ChatOpenAI # Default

# --- External Service Clients ---
try:
    from tavily import AsyncTavilyClient # Use Async Client
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    # print("Warning: tavily-python not installed. Web searches via Tavily will fail.")

try:
    from exa_py import Exa
    EXA_AVAILABLE = True
except ImportError:
    EXA_AVAILABLE = False
    # print("Warning: exa-py not installed. Academic/X searches via Exa will fail.")


# --- Internal Imports ---
# Assuming these exist in sibling files
try:
    from super_agents.deep_research.reason_graph.schemas import SearchResultItem, SearchQuery, StreamUpdate, StreamUpdateData
    from super_agents.deep_research.reason_graph.state import ResearchState
except ImportError as e:
    print(f"Error importing local schemas/state: {e}")
    # Define dummy classes if needed for script to load partially
    class SearchResultItem(BaseModel): pass
    class SearchQuery(BaseModel): pass
    class StreamUpdate(BaseModel): pass
    class StreamUpdateData(BaseModel): pass
    class ResearchState(dict): pass


# --- API Key Loading ---
# Prefer specific LLM_API_KEY, fallback to provider-specific or general OPENAI key
LLM_API_KEY_FROM_ENV = os.getenv("LLM_API_KEY")
OPENAI_API_KEY_FROM_ENV = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY_FROM_ENV = os.getenv("GROQ_API_KEY") # For Groq Cloud

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

# --- Configurable LLM Initialization ---
def initialize_llms() -> Tuple[Optional[RunnableSerializable], Optional[RunnableSerializable]]:
    """
    Initializes and returns the main and creative LLM instances based on environment variables.
    Supports providers: "openai", "groq", "xai"/"grok" (via compatible endpoint), "openai_compatible".
    Returns: (llm, llm_creative) or (None, None) on failure.
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model_name = os.getenv("LLM_MODEL_NAME", "gpt-4.1-mini") # Sensible default
    api_key = LLM_API_KEY_FROM_ENV # Use generic key first
    base_url = os.getenv("LLM_BASE_URL") # For compatible APIs

    try:
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        creative_temperature = float(os.getenv("LLM_CREATIVE_TEMPERATURE", "0.5"))
    except ValueError:
        print("Warning: Invalid LLM temperature value in .env. Using defaults (0.0 / 0.5).")
        temperature = 0.0
        creative_temperature = 0.5

    print(f"\n--- Initializing LLM ---")
    print(f"Provider: '{provider}'")
    print(f"Model Name: '{model_name}'")
    print(f"Base URL: {base_url if base_url else 'Default'}")
    print(f"Temperatures: Main={temperature}, Creative={creative_temperature}")
    print(f"------------------------")

    llm_instance = None
    llm_creative_instance = None

    try:
        if provider == "openai":
            key_to_use = api_key or OPENAI_API_KEY_FROM_ENV
            if not key_to_use:
                raise ValueError("OpenAI API key not found (checked LLM_API_KEY, OPENAI_API_KEY).")
            llm_instance = ChatOpenAI(model=model_name, temperature=temperature, api_key=key_to_use)
            llm_creative_instance = ChatOpenAI(model=model_name, temperature=creative_temperature, api_key=key_to_use)

        elif provider == "xai" or provider == "grok":
            print("Info: Configuring provider 'xai'/'grok'. Assuming OpenAI-compatible API endpoint.")
            if not api_key:
                raise ValueError(f"LLM_API_KEY is required for provider '{provider}' (Your xAI API Key).")
            if not base_url:
                raise ValueError(f"LLM_BASE_URL is required for provider '{provider}' (The xAI Grok API endpoint URL).")
            if not model_name:
                raise ValueError(f"LLM_MODEL_NAME is required for provider '{provider}' (e.g., 'grok-1').")

            llm_instance = ChatOpenAI(
                model=model_name, temperature=temperature,
                openai_api_key=api_key, openai_api_base=base_url,
            )
            llm_creative_instance = ChatOpenAI(
                model=model_name, temperature=creative_temperature,
                openai_api_key=api_key, openai_api_base=base_url,
            )
            print(f"Note: Ensure '{model_name}' is valid for the xAI API at {base_url}.")

        elif provider == "openai_compatible":
            if not api_key:
                raise ValueError(f"LLM_API_KEY is required for provider '{provider}'.")
            if not base_url:
                raise ValueError(f"LLM_BASE_URL is required for provider '{provider}'.")
            if not model_name:
                 raise ValueError(f"LLM_MODEL_NAME is required for provider '{provider}'.")

            llm_instance = ChatOpenAI(
                model=model_name, temperature=temperature,
                openai_api_key=api_key, openai_api_base=base_url,
            )
            llm_creative_instance = ChatOpenAI(
                model=model_name, temperature=creative_temperature,
                openai_api_key=api_key, openai_api_base=base_url,
            )
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: '{provider}'. Check .env file. Supported: 'openai', 'groq', 'xai'/'grok', 'openai_compatible'.")

        print("--- LLM Initialization Successful ---")
        return llm_instance, llm_creative_instance

    except Exception as e:
        print(f"!!! ERROR during LLM Initialization: {e}")
        return None, None

# --- Initialize LLM instances at module level ---
llm, llm_creative = initialize_llms()

# --- Initialize External Service Clients ---
if not TAVILY_API_KEY:
    print("Warning: TAVILY_API_KEY not found in environment variables. Web search will fail.")
tavily_client = AsyncTavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY and TAVILY_AVAILABLE else None

if not EXA_API_KEY:
    print("Warning: EXA_API_KEY not found in environment variables. Academic/X search will fail.")
exa_client = Exa(api_key=EXA_API_KEY) if EXA_API_KEY and EXA_AVAILABLE else None


# --- Tool Helper Functions ---

def generate_structured_output(model: Optional[RunnableSerializable], schema: BaseModel, prompt: str, system_message: str = "") -> Optional[BaseModel]:
    """
    Uses langchain `.with_structured_output` for reliable JSON generation.
    Returns the parsed Pydantic object or None on failure.
    """
    if model is None:
        print("Error: LLM instance not available for structured output generation.")
        return None # Return None if LLM failed to initialize

    try:
        # Let LangChain handle method selection, but be aware of compatibility warnings.
        # If issues persist with specific models/providers, try method="function_calling".
        structured_llm = model.with_structured_output(schema)
        # structured_llm = model.with_structured_output(schema, method="function_calling") # Fallback

        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))
        
        # .invoke is typically synchronous for ChatModels
        response = structured_llm.invoke(messages)
        return response
    except Exception as e:
        print(f"Error during structured output generation: {e}")
        # Consider logging the full traceback here if needed for debugging
        # import traceback
        # traceback.print_exc()
        return None # Indicate failure

def extract_tweet_id(url: str) -> Optional[str]:
    """Extracts tweet ID from twitter.com or x.com URLs."""
    if not url:
        return None
    match = re.search(r"(?:twitter\.com|x\.com)\/\w+\/status\/(\d+)", url)
    return match.group(1) if match else None

def add_stream_update(state: ResearchState, data_dict: Dict[str, Any]) -> List[StreamUpdate]:
    """Creates and returns a list containing a single StreamUpdate, handling potential errors."""
    # Ensure required fields are present for validation, add timestamp
    data_dict.setdefault('timestamp', time.time())
    # Set other defaults expected by StreamUpdateData if necessary,
    # although Pydantic handles Optional fields.

    try:
        # Validate data against the Pydantic model
        update_data = StreamUpdateData(**data_dict)
        stream_update = StreamUpdate(type='research_update', data=update_data)
        return [stream_update]
    except Exception as e: # Catch Pydantic ValidationError or others
        print(f"Error creating stream update for ID {data_dict.get('id', 'N/A')}: {e}")
        print(f"Data causing error: {json.dumps(data_dict, indent=2, default=str)}") # Print problematic data

        # Create a standardized error update object
        try:
            error_update_data = StreamUpdateData(
                id=data_dict.get('id', 'error-id') + '-validation-error', # Make ID unique
                type='error',
                status='completed', # Treat validation error as 'completed' step for flow
                title='Stream Update Creation Error', # Specific Title
                message=f"Pydantic validation failed: {str(e)}", # Include Pydantic error
                timestamp=time.time()
                # Ensure all *required* fields of StreamUpdateData are present here
            )
            stream_update = StreamUpdate(type='research_update', data=error_update_data)
            return [stream_update]
        except Exception as inner_e:
            # If creating even the error update fails, print and return empty
            print(f"CRITICAL: Failed to create error stream update: {inner_e}")
            return []


# --- Tool Wrappers ---

async def perform_web_search(query: str, depth: Literal['basic', 'advanced'], priority: int) -> List[SearchResultItem]:
    """Performs web search using Tavily."""
    if not tavily_client:
        print(f"Tavily client not available. Skipping web search for: '{query}'")
        return []

    max_results = min(max(1, 6 - priority), 10)
    search_depth = depth if depth in ['basic', 'advanced'] else 'basic'

    try:
        print(f"--- Calling Tavily API for: '{query}' ---")
        response = await tavily_client.search(
            query=query,
            search_depth=search_depth,
            include_answer=False, # Set based on whether you need Tavily's answer
            max_results=max_results
        )
        print(f"--- Tavily API call successful for: '{query}' ---")

        results_list = response.get('results', []) if isinstance(response, dict) else []

        formatted_results = [
            SearchResultItem(
                source='web',
                title=r.get('title', 'N/A'),
                url=r.get('url', '#'),
                content=r.get('content', '')
            ) for r in results_list if isinstance(r, dict) and r.get('url')
        ]
        return formatted_results
    except Exception as e:
        print(f"Error during Tavily search for '{query}': {e}")
        # import traceback # Optional: Uncomment for detailed trace
        # traceback.print_exc()
        return []


async def perform_academic_search(query: str, priority: int) -> List[SearchResultItem]:
    """Performs academic search using Exa."""
    if not exa_client:
        print(f"Exa client not available. Skipping academic search for: '{query}'")
        return []

    num_results = min(max(1, 6 - priority), 5)

    try:
        print(f"--- Calling Exa API (Academic) for: '{query}' ---")
        # Wrap synchronous Exa call in run_in_executor for async context
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, # Use default executor (ThreadPoolExecutor)
            lambda: exa_client.search_and_contents(
                query,
                type='auto',
                num_results=num_results,
                highlights=True, # Request highlights/summary
                use_autoprompt=True # Let Exa optimize query
            )
        )
        print(f"--- Exa API call (Academic) successful for: '{query}' ---")

        formatted_results = [
            SearchResultItem(
                source='academic',
                title=r.title or 'N/A',
                url=r.url or '#',
                # Use highlights as content proxy; fallback to text
                content=(r.highlights[0] if r.highlights else r.text or ''),
                tweetId=None # Explicitly None for academic
            ) for r in response.results if r.url # Ensure URL exists
        ]
        return formatted_results
    except Exception as e:
        print(f"Error during Exa academic search for '{query}': {e}")
        # import traceback
        # traceback.print_exc()
        return []

async def perform_x_search(query_obj: SearchQuery) -> List[SearchResultItem]:
    """Performs X/Twitter search using Exa."""
    if not exa_client:
        print(f"Exa client not available. Skipping X search for: '{query_obj.query}'")
        return []

    # Priority might influence number of results differently for social
    num_results = max(2, min(query_obj.priority * 2, 10)) # Example: Scale priority, cap at 10

    try:
        print(f"--- Calling Exa API (X/Twitter) for: '{query_obj.query}' ---")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: exa_client.search_and_contents(
                query_obj.query,
                type='neural', # Often better for social media queries
                num_results=num_results,
                include_domains=['twitter.com', 'x.com'],
                text=True,
                use_autoprompt=True
            )
        )
        print(f"--- Exa API call (X/Twitter) successful for: '{query_obj.query}' ---")

        processed_tweets = []
        for r in response.results:
            tweet_id = extract_tweet_id(r.url)
            if tweet_id and r.url: # Ensure valid ID and URL
                processed_tweets.append(
                    SearchResultItem(
                        source='x',
                        title=r.title or r.author or 'Tweet',
                        url=r.url,
                        content=r.text or '',
                        tweetId=tweet_id
                    )
                )
        return processed_tweets
    except Exception as e:
        print(f"Error during Exa X search for '{query_obj.query}': {e}")
        # import traceback
        # traceback.print_exc()
        return []