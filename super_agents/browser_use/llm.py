# super_agents/browser_use/llm.py
import os
import json
import asyncio
from typing import Optional, Tuple

# --- Environment Variable Loading ---
from dotenv import load_dotenv
load_dotenv() # Load .env file from the directory where main.py is run (likely super_agents/browser_use/)

# --- Pydantic & LangChain Core ---
# Use Pydantic V2+ if installed, otherwise V1 syntax
try:
    from pydantic.v1 import BaseModel # Try V1 first for wider compatibility if needed
except ImportError:
    from pydantic import BaseModel # Fallback to V2

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.base import RunnableSerializable # Type hint for LLM
from langchain_openai import ChatOpenAI # Use OpenAI client as base

# --- REMOVED UNNECESSARY IMPORT ---
# from .state import AgentState # <--- THIS LINE IS REMOVED

# --- API Key Loading ---
# Prefer specific LLM_API_KEY, fallback to provider-specific or general OPENAI key
LLM_API_KEY_FROM_ENV = os.getenv("LLM_API_KEY")
OPENAI_API_KEY_FROM_ENV = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY_FROM_ENV = os.getenv("GROQ_API_KEY") # For Groq Cloud

# --- Configurable LLM Initialization ---
def initialize_llms() -> Tuple[Optional[RunnableSerializable], Optional[RunnableSerializable]]:
    """
    Initializes and returns the main and creative LLM instances based on environment variables.
    Supports providers: "openai", "groq", "xai"/"grok" (via compatible endpoint), "openai_compatible".
    Returns: (llm, llm_creative) or (None, None) on failure.
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    # Adjust default model if needed, e.g., GPT-4o mini
    model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
    api_key = LLM_API_KEY_FROM_ENV # Use generic key first
    base_url = os.getenv("LLM_BASE_URL") # For compatible APIs

    try:
        # Set reasonable defaults for browser agent
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.1")) # Lower temp for reliability
        creative_temperature = float(os.getenv("LLM_CREATIVE_TEMPERATURE", "0.4")) # Slightly higher if needed elsewhere
    except ValueError:
        print("Warning: Invalid LLM temperature value in .env. Using defaults (0.1 / 0.4).")
        temperature = 0.1
        creative_temperature = 0.4

    print(f"\n--- Initializing LLM for Browser Agent ---")
    print(f"Provider: '{provider}'")
    print(f"Model Name: '{model_name}'")
    print(f"Base URL: {base_url if base_url else 'Default'}")
    print(f"Temperatures: Main={temperature}, Creative={creative_temperature}")
    print(f"------------------------------------------")

    llm_instance = None
    llm_creative_instance = None # Keep creative for potential future use, but may not be used initially

    try:
        # Using ChatOpenAI as the base for compatibility across providers via API Key/Base URL
        if provider == "openai":
            key_to_use = api_key or OPENAI_API_KEY_FROM_ENV
            if not key_to_use:
                raise ValueError("OpenAI API key not found (checked LLM_API_KEY, OPENAI_API_KEY).")
            llm_instance = ChatOpenAI(model=model_name, temperature=temperature, api_key=key_to_use)
            llm_creative_instance = ChatOpenAI(model=model_name, temperature=creative_temperature, api_key=key_to_use)

        elif provider == "groq":
            key_to_use = api_key or GROQ_API_KEY_FROM_ENV
            if not key_to_use:
                raise ValueError("Groq API key not found (checked LLM_API_KEY, GROQ_API_KEY).")
            llm_instance = ChatOpenAI(
                model=model_name, temperature=temperature,
                openai_api_key=key_to_use, # Groq uses openai_api_key param
                openai_api_base="https://api.groq.com/openai/v1", # Groq API base
            )
            llm_creative_instance = ChatOpenAI(
                model=model_name, temperature=creative_temperature,
                openai_api_key=key_to_use,
                openai_api_base="https://api.groq.com/openai/v1",
            )
            print("Note: Using Groq provider. Ensure model name is compatible (e.g., llama3-8b-8192).")

        elif provider == "xai" or provider == "grok":
            print("Info: Configuring provider 'xai'/'grok'. Assuming OpenAI-compatible API endpoint.")
            key_to_use = api_key
            if not key_to_use:
                raise ValueError(f"LLM_API_KEY is required for provider '{provider}' (Your xAI API Key).")
            if not base_url:
                raise ValueError(f"LLM_BASE_URL is required for provider '{provider}' (The xAI Grok API endpoint URL).")
            if not model_name:
                raise ValueError(f"LLM_MODEL_NAME is required for provider '{provider}' (e.g., 'grok-1').")

            llm_instance = ChatOpenAI(
                model=model_name, temperature=temperature,
                openai_api_key=key_to_use, openai_api_base=base_url,
            )
            llm_creative_instance = ChatOpenAI(
                model=model_name, temperature=creative_temperature,
                openai_api_key=key_to_use, openai_api_base=base_url,
            )
            print(f"Note: Ensure '{model_name}' is valid for the xAI API at {base_url}.")

        elif provider == "openai_compatible":
            key_to_use = api_key
            if not key_to_use:
                raise ValueError(f"LLM_API_KEY is required for provider '{provider}'.")
            if not base_url:
                raise ValueError(f"LLM_BASE_URL is required for provider '{provider}'.")
            if not model_name:
                 raise ValueError(f"LLM_MODEL_NAME is required for provider '{provider}'.")

            llm_instance = ChatOpenAI(
                model=model_name, temperature=temperature,
                openai_api_key=key_to_use, openai_api_base=base_url,
            )
            llm_creative_instance = ChatOpenAI(
                model=model_name, temperature=creative_temperature,
                openai_api_key=key_to_use, openai_api_base=base_url,
            )
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: '{provider}'. Check .env file. Supported: 'openai', 'groq', 'xai'/'grok', 'openai_compatible'.")

        print("--- LLM Initialization Successful ---")
        return llm_instance, llm_creative_instance

    except Exception as e:
        print(f"!!! ERROR during LLM Initialization: {e}")
        # Optionally log traceback
        # import traceback
        # traceback.print_exc()
        return None, None

# --- Tool Helper Functions (Adapted) ---

# NOTE: This function is now async to align with potential async LLM calls
# although ChatOpenAI.invoke is typically synchronous.
async def generate_structured_output(model: Optional[RunnableSerializable], schema: type[BaseModel], prompt: str, system_message: str = "") -> Optional[BaseModel]:
    """
    Uses langchain `.with_structured_output` for reliable JSON generation matching the schema.
    Returns the parsed Pydantic object or None on failure.
    """
    if model is None:
        print("Error: LLM instance not available for structured output generation.")
        return None

    try:
        # Using with_structured_output. Method selection handled by LangChain.
        # Add `include_raw=True` if you need the raw response alongside the parsed object
        structured_llm = model.with_structured_output(schema)

        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))

        # Use ainvoke for async compatibility, though underlying call might be sync
        response = await structured_llm.ainvoke(messages)
        # response = structured_llm.invoke(messages) # If using sync graph

        # Add type check for safety before returning
        if isinstance(response, schema):
            return response
        else:
            print(f"Warning: Structured output did not match expected schema {schema.__name__}. Got type: {type(response)}")
            return None

    except Exception as e:
        print(f"Error during structured output generation: {e}")
        # Consider more detailed logging
        return None # Indicate failure