import os
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Type, Literal, TypedDict, cast
from types import TracebackType
import re
import sys
import json
import traceback
from contextlib import asynccontextmanager, AsyncExitStack

# --- MCP Imports ---
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
# --- Adapter Import ---
try:
     from langchain_mcp_adapters.tools import load_mcp_tools
     LOAD_MCP_TOOLS_AVAILABLE = True
except ImportError:
     print("警告: 未找到 langchain-mcp-adapters。 load_mcp_tools 将不可用。")
     async def load_mcp_tools(session: ClientSession) -> list: return []
     LOAD_MCP_TOOLS_AVAILABLE = False
# --- LangChain / Pydantic Imports ---
from langchain_core.tools import BaseTool
try: from pydantic.v1 import BaseModel as BaseModelV1
except ImportError: from pydantic import BaseModel as BaseModelV1 # Fallback
# --- Config Loader Import ---
try: from .config_loader import MCPConfig, StdioConfig, SSEConfig
except ImportError: print("WARNING: Could not import config models from .config_loader."); MCPConfig=Any; StdioConfig=Any; SSEConfig=Any # Placeholders

print("--- DEBUG: Loading FINAL client.py (Config-Driven + AsyncExitStack) ---")

class MCPClient:
    """Config-driven MCP Client using AsyncExitStack."""
    def __init__(self, config: MCPConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools: List[BaseTool] = []
        self._stack: AsyncExitStack = AsyncExitStack()
        self._server_process: Optional[asyncio.subprocess.Process] = None

    async def __aenter__(self) -> "MCPClient":
        print(f"DEBUG: MCPClient entering context for config ID: {getattr(self.config, 'id', 'N/A')}")
        try:
            connection_config = self.config.connection
            transport_ctx = None
            reader = None
            writer = None

            if isinstance(connection_config, SSEConfig) and connection_config.url:
                # --- Direct SSE ---
                print(f"DEBUG: Connecting via SSE to {connection_config.url}")
                transport_ctx = sse_client(
                    connection_config.url, getattr(connection_config,'headers', None),
                    getattr(connection_config,'timeout', 5.0), getattr(connection_config,'sse_read_timeout', 300.0)
                )
                reader, writer = await self._stack.enter_async_context(transport_ctx)
                print("DEBUG: SSE transport context entered.")

            elif isinstance(connection_config, StdioConfig) and connection_config.command:
                # --- Launch via Command + STDIO ---
                print(f"DEBUG: Launching command via STDIO: {connection_config.command} {' '.join(connection_config.args)}")
                merged_env = os.environ.copy();
                if connection_config.env: merged_env.update(connection_config.env)
                server_params = StdioServerParameters(
                    command=connection_config.command, args=connection_config.args, env=merged_env,
                    cwd=connection_config.cwd, encoding=connection_config.encoding,
                    encoding_error_handler=connection_config.encoding_error_handler,
                    startup_timeout=connection_config.timeout
                )
                transport_ctx = stdio_client(server_params)
                reader, writer = await self._stack.enter_async_context(transport_ctx)
                print("DEBUG: STDIO transport context entered.")

            else: # Fallback/Error - Handle case where config might be wrong or transport missing
                 # Added check for command presence before assuming SSE launch
                 if hasattr(connection_config, 'command') and connection_config.command:
                      # This is the complex "launch then connect SSE" case from the guide
                      # Keeping it simple for now - if transport isn't 'stdio', it must be 'sse' with a URL
                      raise NotImplementedError("Launching command for SSE connection (URL capture) not implemented in this client version. Use direct SSE URL or STDIO command.")
                 else:
                      raise ValueError("Invalid configuration: must have 'url' for SSE or 'command' for STDIO.")


            # --- Establish ClientSession ---
            session_kwargs = getattr(connection_config, 'session_kwargs', None) or {}
            session_ctx = ClientSession(reader, writer, **session_kwargs)
            self.session = await self._stack.enter_async_context(session_ctx)
            print("DEBUG: ClientSession context entered.")

            # --- Initialize and Load Tools (with Schema Check) ---
            print("Initializing MCP session...")
            await asyncio.wait_for(self.session.initialize(), timeout=30.0)
            print("MCP session initialized.")

            if LOAD_MCP_TOOLS_AVAILABLE:
                print("Loading MCP tools (via langchain-mcp-adapters)...")
                loaded_tools_from_mcp = await load_mcp_tools(self.session)
                print(f"Successfully loaded {len(loaded_tools_from_mcp)} tool descriptions.")
                print("--- Loaded Tools & Args Schema (Diagnostic) ---")
                self.tools = []
                for i, tool in enumerate(loaded_tools_from_mcp):
                     schema = getattr(tool, 'args_schema', 'N/A'); tool_name = getattr(tool, 'name', f'Tool_{i+1}')
                     print(f"{i+1}. Tool Name: {tool_name}")
                     schema_detail = "N/A"
                     is_correct = None # Undetermined
                     if schema != 'N/A': # Schema printing and basic check
                          schema_dict = None
                          if isinstance(schema, type) and issubclass(schema, BaseModelV1):
                               try: schema_dict = schema.schema(); schema_detail = f"(PydanticV1): {json.dumps(schema_dict, indent=2)}"
                               except Exception as e_schema: schema_detail = f"(PydanticV1): Error - {e_schema}"
                          elif hasattr(schema, 'model_json_schema'):
                               try: schema_dict = schema.model_json_schema(); schema_detail = f"(PydanticV2): {json.dumps(schema_dict, indent=2)}"
                               except Exception as e_schema: schema_detail = f"(PydanticV2): Error - {e_schema}"
                          else: schema_detail = f"(Unknown Type): {schema}"
                          # Basic check: does it look like the faulty kwargs schema?
                          if isinstance(schema_dict, dict):
                               props = schema_dict.get('properties', {})
                               if list(props.keys()) == ['kwargs'] and props['kwargs'].get('type') == 'string':
                                    is_correct = False
                                    schema_detail += " <-- LOOKS WRONG (kwargs only!)"
                               elif props:
                                    is_correct = True # Has properties other than just kwargs
                                    schema_detail += " <-- Looks structured correctly"
                               else:
                                     is_correct = True # No properties, might be simple input
                                     schema_detail += " <-- No properties defined"
                     else: is_correct = False # No schema is usually wrong
                     print(f"   Args Schema: {schema_detail}")
                     print("-" * 15); self.tools.append(tool)
                print(f"Schema Check Result: {'All schemas look structured correctly.' if all(s is not False for s in [getattr(t, 'args_schema', None) != 'N/A' and 'kwargs' not in str(getattr(t, 'args_schema', '')).lower() for t in self.tools]) else 'One or more schemas look incorrect (kwargs only or missing)!'}")
                print("-------------------------------------------")
            else: print("Warning: load_mcp_tools unavailable."); self.tools = []
            print(f"MCPClient ready. Loaded {len(self.tools)} tools via adapter.")
            return self
        except Exception as enter_err:
            print(f"ERROR: Failed during MCPClient __aenter__: {type(enter_err).__name__}: {enter_err}")
            await self.close(); raise

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]):
        print("DEBUG: MCPClient exiting context..."); await self.close(); print("DEBUG: MCPClient context exited.")

    async def close(self):
        """Closes connections and resets state using AsyncExitStack."""
        print("Closing MCP Client...");
        if hasattr(self, '_stack') and self._stack:
            print("  Closing managed async contexts (via AsyncExitStack)...")
            try: await self._stack.aclose(); print("  AsyncExitStack closed.")
            except Exception as e: print(f"WARNING: Error closing AsyncExitStack: {type(e).__name__}: {e}")
            finally: self._stack = None
        else: print("  No active AsyncExitStack.")
        self.session = None; self.tools = []; self._transport_ctx = None; self._server_process = None
        print("MCP Client state reset.")

    def get_tools(self) -> List[BaseTool]:
        """Returns the list of tools loaded by load_mcp_tools."""
        return self.tools