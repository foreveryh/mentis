import os
import json
import time
import re
import logging # Use logging instead of just print for warnings/errors
import asyncio
from datetime import datetime
from typing import Optional, List, Literal, Dict, Any, Tuple, Set, Type

# --- Environment Variable Loading ---
from dotenv import load_dotenv
load_dotenv()
import yfinance as yf
import pandas as pd

# --- Pydantic & LangChain Core ---
from pydantic import BaseModel, ValidationError, Field # Import Field for schema descriptions
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables.base import RunnableSerializable # Type hint for LLM
# Use specific import for ChatOpenAI or other providers as needed
from langchain_openai import ChatOpenAI

# --- Internal Imports ---
# Assuming schemas.py and state.py exist in the same directory or path is correctly set
try:
    from .schemas import SearchResultItem, SearchQuery, StreamUpdate, StreamUpdateData # Relative import
    from .state import ResearchState, YFinanceData # Relative import
except ImportError as e:
    print(f"Error importing local schemas/state within tools.py: {e}")
    # Define dummy classes if needed for script loading without full context
    class BaseModel: pass # Basic placeholder
    class SearchResultItem(BaseModel): title: str = ""; url: Optional[str] = None; snippet: str = ""
    class SearchQuery(BaseModel): query: str = ""; tool_hint: str = "web_search"
    class StreamUpdateData(BaseModel): id: str = ""; type: str = ""; status: str = ""
    class StreamUpdate(BaseModel): data: Optional[StreamUpdateData] = None; timestamp: float = 0.0
    class ResearchState(dict): pass
    class YFinanceData(dict): pass

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- API Key Loading ---
LLM_API_KEY_FROM_ENV = os.getenv("LLM_API_KEY")
OPENAI_API_KEY_FROM_ENV = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY_FROM_ENV = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
# EXA_API_KEY = os.getenv("EXA_API_KEY") # Keep commented unless Exa tools are re-enabled

# --- Configurable LLM Initialization ---
def initialize_llms() -> Tuple[Optional[RunnableSerializable], Optional[RunnableSerializable]]:
    """
    Initializes and returns the main and creative LLM instances based on environment variables.
    Supports providers: "openai", "groq", "xai"/"grok", "openai_compatible".
    Returns: (llm, llm_creative) or (None, None) on failure.
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model_name = os.getenv("LLM_MODEL_NAME") # Get model name from env
    api_key = LLM_API_KEY_FROM_ENV
    base_url = os.getenv("LLM_BASE_URL")

    # Validate essential config based on provider
    if not model_name:
         logger.error("LLM_MODEL_NAME environment variable is not set.")
         return None, None

    try:
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        creative_temperature = float(os.getenv("LLM_CREATIVE_TEMPERATURE", "0.5"))
    except ValueError:
        logger.warning("Invalid LLM temperature value in .env. Using defaults (0.0 / 0.5).")
        temperature = 0.0
        creative_temperature = 0.5

    logger.info("--- Initializing LLM ---")
    logger.info(f"Provider: '{provider}'")
    logger.info(f"Model Name: '{model_name}'")
    logger.info(f"Base URL: {base_url if base_url else 'Default'}")
    logger.info(f"Temperatures: Main={temperature}, Creative={creative_temperature}")
    logger.info("------------------------")

    llm_instance = None
    llm_creative_instance = None

    try:
        # Consolidate key logic
        key_to_use = None
        if provider == "openai":
            key_to_use = api_key or OPENAI_API_KEY_FROM_ENV
            if not key_to_use: raise ValueError("OpenAI API key not found (checked LLM_API_KEY, OPENAI_API_KEY).")
            # Use default base_url for OpenAI if not provided
            if not base_url: base_url = None # Let ChatOpenAI use default
        elif provider in ["xai", "grok", "openai_compatible"]:
            provider_name = "xAI/Grok" if provider in ["xai", "grok"] else "OpenAI Compatible"
            logger.info(f"Configuring provider '{provider_name}'. Assuming OpenAI-compatible API endpoint.")
            key_to_use = api_key # Must use LLM_API_KEY
            if not key_to_use: raise ValueError(f"LLM_API_KEY is required for provider '{provider}'.")
            if not base_url: raise ValueError(f"LLM_BASE_URL is required for provider '{provider}'.")
            logger.info(f"Note: Ensure '{model_name}' is valid for the API at {base_url}.")
        elif provider == "groq":
            key_to_use = api_key or GROQ_API_KEY_FROM_ENV
            if not key_to_use: raise ValueError("Groq API key not found (checked LLM_API_KEY, GROQ_API_KEY).")
            # Groq uses ChatGroq class, needs separate import if used.
            # For simplicity, let's assume it behaves like ChatOpenAI for now,
            # but ideally, use the specific Groq class.
            # from langchain_groq import ChatGroq
            # llm_instance = ChatGroq(...)
            # For now, treat as openai_compatible requires user to ensure compatibility
            logger.warning("Groq provider selected, using ChatOpenAI assuming compatibility. Consider using ChatGroq.")
            if not base_url: base_url = "https://api.groq.com/openai/v1" # Default Groq compatible endpoint
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: '{provider}'. Check .env. Supported: 'openai', 'groq', 'xai'/'grok', 'openai_compatible'.")

        # Instantiate LLMs using ChatOpenAI (or specific provider class if needed)
        common_params = {
             "model": model_name,
             "api_key": key_to_use,
             "base_url": base_url, # Pass None if using default OpenAI URL
        }
        # Filter out None values for base_url if using default OpenAI
        if provider == "openai" and base_url is None:
            del common_params["base_url"]

        llm_instance = ChatOpenAI(**common_params, temperature=temperature)
        llm_creative_instance = ChatOpenAI(**common_params, temperature=creative_temperature)

        logger.info("--- LLM Initialization Successful ---")
        return llm_instance, llm_creative_instance

    except ImportError as e:
        logger.error(f"!!! ERROR: Missing required LangChain provider package for '{provider}': {e}")
        logger.error("Please install the necessary package (e.g., 'pip install langchain-openai', 'pip install langchain-groq').")
        return None, None
    except Exception as e:
        logger.error(f"!!! ERROR during LLM Initialization: {e}")
        import traceback
        traceback.print_exc() # Print traceback for debugging init errors
        return None, None

# --- Initialize LLM instances at module level ---
llm, llm_creative = initialize_llms()

# --- Initialize External Service Clients ---
# Tavily Client (for web search)
tavily_client = None
if TAVILY_API_KEY:
    try:
        from tavily import AsyncTavilyClient
        tavily_client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
        logger.info("Tavily client initialized.")
    except ImportError:
        logger.warning("tavily-python not installed, Tavily web search will not be available.")
    except Exception as e:
        logger.error(f"Failed to initialize Tavily client: {e}")
else:
    logger.warning("TAVILY_API_KEY not found in environment variables. Tavily web search will fail.")

# Exa Client (Commented out as per simplified plan)
# exa_client = None
# if EXA_API_KEY:
#     try:
#         from exa_py import Exa
#         exa_client = Exa(api_key=EXA_API_KEY)
#         logger.info("Exa client initialized.")
#     except ImportError:
#         logger.warning("exa-py not installed, Exa searches will not be available.")
#     except Exception as e:
#         logger.error(f"Failed to initialize Exa client: {e}")
# else:
#     logger.warning("EXA_API_KEY not found in environment variables. Exa searches will fail.")


# --- Tool Helper Functions ---

async def generate_structured_output(
    model: Optional[RunnableSerializable],
    schema: Type[BaseModel], # Use Type[BaseModel] for typing Pydantic models
    prompt: str,
    system_message: str = ""
) -> Optional[BaseModel]:
    """
    Uses langchain's `.with_structured_output` for reliable JSON generation
    conforming to the provided Pydantic schema.

    Args:
        model: The LangChain LLM runnable instance (e.g., llm_creative).
        schema: The Pydantic model class to structure the output.
        prompt: The main user prompt for the LLM.
        system_message: Optional system message to guide the LLM.

    Returns:
        An instance of the Pydantic schema if successful, otherwise None.
    """
    if model is None:
        logger.error("LLM instance is None, cannot generate structured output.")
        return None # Return None if LLM failed to initialize

    logger.info(f"[Tool] Attempting structured output generation for schema: {schema.__name__}")
    try:
        # Use with_structured_output - method='function_calling' is often reliable
        # method='json_mode' might be available/preferable for newer models/versions
        structured_llm = model.with_structured_output(schema, method="function_calling")
        # structured_llm = model.with_structured_output(schema, method="json_mode") # Alternative

        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))

        # Use asynchronous invoke if the model supports it (most ChatModels do)
        response = await structured_llm.ainvoke(messages)

        # Check if the response is of the correct Pydantic type
        if isinstance(response, schema):
             logger.info(f"[Tool] Successfully generated structured output for {schema.__name__}.")
             return response
        else:
             # This case might happen if parsing fails within the LangChain method
             logger.error(f"[Tool] Structured output generation returned unexpected type: {type(response)}. Expected {schema.__name__}.")
             # Log the raw response if possible for debugging
             logger.error(f"Raw response: {response}")
             return None

    except NotImplementedError as nie:
        # Handle cases where the model/method combination isn't supported
        logger.error(f"Structured output method not implemented for this LLM/schema combination: {nie}")
        logger.error("Try switching the 'method' argument in with_structured_output (e.g., 'json_mode').")
        return None
    except ValidationError as ve:
        # Catch Pydantic validation errors if LangChain parsing returns data that doesn't fit the schema
        logger.error(f"Pydantic validation failed for structured output: {ve}")
        # Log the prompt or relevant context if helpful for debugging schema mismatches
        # logger.error(f"Prompt leading to validation error: {prompt[:500]}...")
        return None
    except Exception as e:
        logger.error(f"Error during structured output generation for {schema.__name__}: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for unexpected errors
        return None


def create_update(state: Dict[str, Any], update_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Helper to create stream update dictionaries adhering to StreamUpdate schema.
    Ensures required keys for StreamUpdateData are present based on schema definition.
    """
    # Define REQUIRED fields for StreamUpdateData based on your schemas.py
    # Assuming 'id', 'type', 'status' are always required
    required_keys = {'id', 'type', 'status'}

    # Set defaults for optional fields if not provided in update_data
    defaults = {
        'title': None,
        'message': None,
        'payload': None,
        'overwrite': False,
        'isComplete': None,
        'completedSteps': None,
        'totalSteps': None,
    }
    # Merge defaults with provided data
    data_payload = {**defaults, **update_data}

    # Validate required keys
    missing_keys = required_keys - data_payload.keys()
    if missing_keys:
        logger.warning(f"create_update missing required keys {missing_keys} in data: {data_payload}")
        # Decide how to handle: fill with defaults, raise error, or just log?
        # Let's fill with defaults for robustness, but log clearly.
        for key in missing_keys:
            data_payload[key] = f"MISSING_{key.upper()}" # Make missing value obvious

    # Construct the final update object matching StreamUpdate structure
    timestamp = time.time()
    stream_update_obj = {
        # Assuming StreamUpdate is {'data': StreamUpdateData, 'timestamp': float}
        # If StreamUpdate IS StreamUpdateData + timestamp, adjust structure
        "data": data_payload,
        "timestamp": timestamp
    }

    # Validate against Pydantic models if desired (adds overhead but ensures correctness)
    # try:
    #     StreamUpdate(**stream_update_obj) # Validate structure
    # except ValidationError as ve:
    #     logger.error(f"Validation failed for created StreamUpdate object: {ve}")
    #     logger.error(f"Object causing error: {stream_update_obj}")
    #     return [] # Return empty list on validation failure

    # Return a list containing the single update dictionary
    return [stream_update_obj]

# --- Tool Wrappers ---

async def perform_web_search(query: str, max_results: int = 5) -> List[SearchResultItem]:
    """Performs web search using Tavily async client."""
    if not tavily_client:
        logger.warning(f"Tavily client not available. Skipping web search for: '{query}'")
        return []

    # Ensure max_results is reasonable
    max_results = max(1, min(max_results, 10)) # Clamp between 1 and 10

    try:
        logger.info(f"[Tool] Calling Tavily API for: '{query}' (Max results: {max_results})")
        # Use include_raw_content=False unless you need the full webpage content
        response = await tavily_client.search(
            query=query,
            search_depth="advanced", # Use advanced for potentially better M&A context
            include_answer=False, # Typically don't need Tavily's generated answer
            max_results=max_results,
            include_raw_content=False,
            # include_images=False, # Don't need images
        )
        logger.info(f"[Tool] Tavily API call successful for: '{query}'")

        results_list = response.get('results', []) if isinstance(response, dict) else []

        # Convert Tavily results to our internal SearchResultItem schema
        formatted_results = []
        for r in results_list:
             if isinstance(r, dict) and r.get('url'):
                 formatted_results.append(
                     SearchResultItem(
                         # source='tavily_web', # Optional: track source tool
                         title=r.get('title', 'N/A'),
                         url=r.get('url'),
                         snippet=r.get('content', '') # Tavily 'content' is the snippet
                     )
                 )
        logger.info(f"Formatted {len(formatted_results)} results from Tavily.")
        return formatted_results
    except Exception as e:
        logger.error(f"Error during Tavily search for '{query}': {e}")
        return []


# --- NEW yfinance Data Fetching Tool ---
async def fetch_yfinance_data(ticker_symbol: str) -> YFinanceData:
    """
    Fetches comprehensive financial data for a given ticker using yfinance.
    Handles potential errors during data retrieval. Returns YFinanceData dict.
    """
    if not ticker_symbol or not isinstance(ticker_symbol, str):
        msg = "Invalid or missing ticker symbol provided for yfinance."
        logger.warning(f"[Tool] {msg}")
        return {"error": msg} # Return error in expected structure

    logger.info(f"[Tool] Fetching yfinance data for Ticker: {ticker_symbol}")
    # Initialize with None or empty structures matching YFinanceData TypedDict
    data: YFinanceData = {
        "info": None, "financials": None, "quarterly_financials": None,
        "balance_sheet": None, "quarterly_balance_sheet": None,
        "cashflow": None, "quarterly_cashflow": None,
        "major_holders": None, "institutional_holders": None,
        "recommendations": None, "news": [], "error": None # Default news to empty list
    }
    fetched_items_count = 0
    total_items_to_fetch = 11 # info, fin*2, bs*2, cf*2, holders*2, recs, news

    try:
        # Instantiate Ticker object
        ticker = yf.Ticker(ticker_symbol)

        # Fetch data points individually with error handling
        # Use asyncio.gather to fetch some potentially slow items concurrently?
        # Example: Fetch info first, then others concurrently if info looks valid.

        # 1. Fetch Info (Critical)
        try:
            info_data = ticker.info
            # Basic validation: Check if info dict is not empty and has a common key like 'symbol' or 'longName'
            if info_data and ('symbol' in info_data or 'longName' in info_data):
                 data['info'] = info_data
                 fetched_items_count += 1
                 logger.info(f"  Fetched .info for {ticker_symbol}")
            else:
                 raise ValueError(f"ticker.info for {ticker_symbol} is empty or invalid.")
        except Exception as e:
            logger.error(f"  Error fetching critical .info for {ticker_symbol}: {e}")
            data['error'] = f"Failed to fetch core info for ticker '{ticker_symbol}'. It might be invalid or delisted. Error: {e}"
            # If core info fails, maybe don't bother fetching others? Return early.
            logger.warning(f"[Tool] Aborting yfinance fetch for {ticker_symbol} due to critical info error.")
            return data # Return immediately with error

        # 2. Fetch other data points (can potentially be concurrent)
        async def _fetch_yf(attr_name):
             try:
                 # Use getattr to call the property/method on the ticker object
                 result = getattr(ticker, attr_name)
                 # Basic check for empty DataFrames
                 if isinstance(result, pd.DataFrame) and result.empty:
                     logger.warning(f"  yfinance returned empty DataFrame for .{attr_name}")
                     return attr_name, None # Return None for empty df? Or empty df itself? Let's return None.
                 elif isinstance(result, list) and not result:
                      logger.warning(f"  yfinance returned empty list for .{attr_name}")
                      return attr_name, [] # Return empty list for news
                 logger.info(f"  Successfully fetched .{attr_name}")
                 return attr_name, result
             except Exception as e:
                 logger.warning(f"  Error fetching .{attr_name} for {ticker_symbol}: {e}")
                 return attr_name, None # Return None on error

        attributes_to_fetch = [
             'financials', 'quarterly_financials', 'balance_sheet', 'quarterly_balance_sheet',
             'cashflow', 'quarterly_cashflow', 'major_holders', 'institutional_holders',
             'recommendations', 'news'
        ]
        # Run fetches concurrently
        results = await asyncio.gather(*[_fetch_yf(attr) for attr in attributes_to_fetch])

        # Populate the data dictionary from results
        for attr_name, result_value in results:
            if result_value is not None:
                data[attr_name] = result_value # Assign fetched data
                fetched_items_count += 1

        logger.info(f"[Tool] Fetched {fetched_items_count}/{total_items_to_fetch} data items total from yfinance for {ticker_symbol}")

    except Exception as e:
        # Catch errors during Ticker instantiation or other critical issues
        error_message = f"Critical error initializing yfinance.Ticker or during fetch process for {ticker_symbol}: {str(e)}"
        logger.error(f"[Tool] {error_message}")
        # Ensure error key exists and is updated, avoid overwriting previous specific errors if possible
        if data.get('error') is None:
             data['error'] = error_message

    # --- NEW: Convert DataFrames to serializable dict format ---
    serializable_data = {}
    for key, value in data.items():
        if isinstance(value, pd.DataFrame):
            try:
                # 'split' orientation is often good for preserving structure
                # Handle potential Timestamp conversion issues in index/columns here if necessary before to_dict
                # Example: Convert index to string if it's Timestamp
                if pd.api.types.is_datetime64_any_dtype(value.index):
                    value.index = value.index.strftime('%Y-%m-%d') # Or another suitable string format
                # Example: Convert columns to string if they are Timestamps (less common for yfinance columns)
                if any(isinstance(col, pd.Timestamp) for col in value.columns):
                    value.columns = [str(col) for col in value.columns]

                serializable_data[key] = value.to_dict(orient='split')
                logger.debug(f"  Converted DataFrame '{key}' to dict.")
            except Exception as convert_e:
                logger.error(f"  Error converting DataFrame '{key}' to dict: {convert_e}")
                serializable_data[key] = {"error": f"Failed to serialize DataFrame: {convert_e}"}
        else:
            # Keep non-DataFrame items (like info dict, news list, error string) as they are
            serializable_data[key] = value

    if data.get('error'):
        logger.warning(f"Returning yfinance data for {ticker_symbol} with error: {data['error']}")
    else:
        logger.info(f"[Tool] Completed yfinance fetch and serialization for {ticker_symbol} successfully.")

    # Return the dictionary with serialized DataFrames
    return serializable_data # Return the modified dictionary


# --- Commented out Exa Tools (Keep if desired, ensure EXA_API_KEY is set) ---
# async def perform_academic_search(query: str, max_results: int = 3) -> List[SearchResultItem]:
#      if not exa_client:
#          logger.warning(f"Exa client not available. Skipping academic search for: '{query}'")
#          return []
#      logger.info(f"[Tool] Performing Academic Search for: {query} (Using Exa - Requires EXA_API_KEY)")
#      # ... Implementation using exa_client ...
#      return []

# async def perform_x_search(query: str, max_results: int = 5) -> List[SearchResultItem]:
#      if not exa_client:
#          logger.warning(f"Exa client not available. Skipping X search for: '{query}'")
#          return []
#      logger.info(f"[Tool] Performing X Search for: {query} (Using Exa - Requires EXA_API_KEY)")
#      # ... Implementation using exa_client ...
#      return []