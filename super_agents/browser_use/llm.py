# super_agents/browser_use/llm.py
import os
import json
import asyncio
from typing import Optional, Tuple, Type, Dict

# --- Environment Variable Loading ---
from dotenv import load_dotenv
load_dotenv()

# --- Pydantic & LangChain Core ---
try:
    # Import necessary Pydantic components if needed elsewhere (e.g., for generate_structured_output)
    from pydantic.v1 import BaseModel
except ImportError:
    from pydantic import BaseModel

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.base import RunnableSerializable
# No longer need secret_from_env here if ChatOpenRouter doesn't use Field/SecretStr
# from langchain_core.utils.utils import secret_from_env
from langchain_openai import ChatOpenAI # Use the standard import

# --- API Key Loading (For initialize_llms) ---
LLM_API_KEY_FROM_ENV = os.getenv("LLM_API_KEY")
OPENAI_API_KEY_FROM_ENV = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY_FROM_ENV = os.getenv("GROQ_API_KEY")
# OPENROUTER key will be loaded directly in ChatOpenRouter init
OPENROUTER_API_KEY_DIRECT = os.getenv("OPENROUTER_API_KEY")

# --- ChatOpenRouter Definition (Based on User's Example 1 Logic) ---
class ChatOpenRouter(ChatOpenAI):
    """
    Wrapper for ChatOpenAI configured for OpenRouter.
    Handles API key loading within __init__ using standard strings
    to avoid Pydantic V2 SecretStr issues during class definition.
    """
    # No class-level Field definition for openai_api_key to avoid Pydantic V2 error

    def __init__(self,
                 model_name: str, # Make model_name required
                 openai_api_key: Optional[str] = None, # Accept optional string key
                 openai_api_base: str = "https://openrouter.ai/api/v1", # Default OpenRouter base
                 **kwargs):
        """
        Initializes the ChatOpenRouter client.

        Args:
            model_name: The model identifier on OpenRouter (e.g., "alibaba/qwen-vl-max").
            openai_api_key: Optional OpenRouter API key (string). If None, reads from
                             OPENROUTER_API_KEY environment variable.
            openai_api_base: The API base URL. Defaults to OpenRouter.
            **kwargs: Additional arguments passed to ChatOpenAI.
        """
        # Resolve the API key: use passed argument first, then environment variable
        resolved_key = openai_api_key or OPENROUTER_API_KEY_DIRECT
        if not resolved_key:
            # Log warning or raise error if key is missing, depending on desired strictness
            # Raising an error is safer to prevent unexpected failures later
            raise ValueError("OpenRouter API key not provided directly or via OPENROUTER_API_KEY env var.")

        # Call the parent __init__ method, passing the resolved string key
        # Use openai_api_base argument expected by ChatOpenAI
        super().__init__(
            openai_api_base=openai_api_base,
            openai_api_key=resolved_key, # Pass resolved string key
            model_name=model_name, # Pass model_name
            **kwargs # Pass other arguments like temperature, max_tokens
        )
        # Optional: Log successful initialization
        # logger.info(f"ChatOpenRouter initialized for model {model_name}") # Requires logger setup

# --- Configurable LLM Initialization (For Planning LLM - unchanged) ---
def initialize_llms() -> Tuple[Optional[RunnableSerializable], Optional[RunnableSerializable]]:
    # ... (function remains the same as before) ...
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
    api_key = LLM_API_KEY_FROM_ENV
    base_url = os.getenv("LLM_BASE_URL")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    creative_temperature = float(os.getenv("LLM_CREATIVE_TEMPERATURE", "0.4"))
    print(f"\n--- Initializing Planning LLM ---")
    print(f"Provider: '{provider}'")
    print(f"Model Name: '{model_name}'")
    print(f"Base URL: {base_url if base_url else 'Default'}")
    print(f"Temperatures: Main={temperature}, Creative={creative_temperature}")
    print(f"-----------------------------")
    llm_instance: Optional[RunnableSerializable] = None
    llm_creative_instance: Optional[RunnableSerializable] = None
    try:
        if provider == "openai": # ... (rest of provider logic) ...
             key_to_use = api_key or OPENAI_API_KEY_FROM_ENV
             if not key_to_use: raise ValueError("OpenAI API key not found for planning LLM.")
             llm_instance = ChatOpenAI(model=model_name, temperature=temperature, api_key=key_to_use)
             llm_creative_instance = ChatOpenAI(model=model_name, temperature=creative_temperature, api_key=key_to_use)
        elif provider == "groq": # ...
             key_to_use = api_key or GROQ_API_KEY_FROM_ENV
             if not key_to_use: raise ValueError("Groq API key not found.")
             llm_instance = ChatOpenAI(model=model_name, temperature=temperature, openai_api_key=key_to_use, openai_api_base="https://api.groq.com/openai/v1")
             llm_creative_instance = ChatOpenAI(model=model_name, temperature=creative_temperature, openai_api_key=key_to_use, openai_api_base="https://api.groq.com/openai/v1")
        elif provider == "xai" or provider == "grok": # ...
             key_to_use = api_key
             if not key_to_use: raise ValueError(f"LLM_API_KEY required for '{provider}'.")
             if not base_url: raise ValueError(f"LLM_BASE_URL required for '{provider}'.")
             if not model_name: raise ValueError(f"LLM_MODEL_NAME required for '{provider}'.")
             llm_instance = ChatOpenAI(model=model_name, temperature=temperature, openai_api_key=key_to_use, openai_api_base=base_url)
             llm_creative_instance = ChatOpenAI(model=model_name, temperature=creative_temperature, openai_api_key=key_to_use, openai_api_base=base_url)
        elif provider == "openai_compatible": # ...
             key_to_use = api_key
             if not key_to_use: raise ValueError(f"LLM_API_KEY required for '{provider}'.")
             if not base_url: raise ValueError(f"LLM_BASE_URL required for '{provider}'.")
             if not model_name: raise ValueError(f"LLM_MODEL_NAME required for '{provider}'.")
             llm_instance = ChatOpenAI(model=model_name, temperature=temperature, openai_api_key=key_to_use, openai_api_base=base_url)
             llm_creative_instance = ChatOpenAI(model=model_name, temperature=creative_temperature, openai_api_key=key_to_use, openai_api_base=base_url)
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER for planning LLM: '{provider}'.")
        print("--- Planning LLM Initialization Successful ---")
        return llm_instance, llm_creative_instance
    except Exception as e:
        print(f"!!! ERROR during Planning LLM Initialization: {e}")
        return None, None

# --- generate_structured_output (Helper used by Planning Node - unchanged) ---
async def generate_structured_output(model: Optional[RunnableSerializable], schema: Type[BaseModel], prompt: str, system_message: str = "") -> Optional[BaseModel]:
    # ... (function remains the same as before) ...
    if model is None: return None
    if not isinstance(model, RunnableSerializable): return None
    try:
        # Ensure schema is Pydantic BaseModel (imported from V1 or V2)
        if not issubclass(schema, BaseModel):
             print(f"Error: schema provided to generate_structured_output is not a Pydantic BaseModel (type: {type(schema)})")
             return None
        structured_llm = model.with_structured_output(schema)
        messages = []
        if system_message: messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))
        response = await structured_llm.ainvoke(messages)
        if isinstance(response, schema): return response
        else:
            print(f"Warning: Structured output did not match expected schema {schema.__name__}. Got type: {type(response)}")
            return None
    except Exception as e:
        print(f"Error during structured output generation: {e}")
        # import traceback; traceback.print_exc() # Uncomment for full debug trace
        return None