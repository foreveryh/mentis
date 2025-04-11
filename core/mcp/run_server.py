# core/mcp/run_server.py (FINAL - Direct FastMCP Registration)
import os
import sys
import argparse
import traceback
import logging
from typing import List, Dict, Any, Optional, Type

# --- Standard Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_server_direct")

current_dir = os.path.dirname(os.path.abspath(__file__)); 
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir))); sys.path.insert(0, project_root)

# --- Imports ---
from mcp.server.fastmcp import FastMCP # Import FastMCP directly
# Assume registry is populated correctly by preregister_core_tools
from core.tools.registry import get_registered_tools, get_tool_instance
try: 
    from core.tools import preregister_core_tools; 
    PREREGISTER_AVAILABLE = True
except ImportError: 
    print("WARNING: preregister_core_tools not found"); 
    def preregister_core_tools(): pass; 
    PREREGISTER_AVAILABLE = False
from langchain_core.tools import BaseTool
import asyncio
import time
import json
import functools
import inspect # Needed for func_metadata potentially

print("--- DEBUG: Loading FINAL run_server.py (Direct FastMCP Registration) ---")

# --- Tool Wrapper Creation Logic (as a standalone function) ---
def create_tool_wrapper(tool_instance: BaseTool):
    """
    Creates the async wrapper function for a given tool instance.
    This function will be decorated LATER by the mcp_instance.
    """
    tool_name = getattr(tool_instance, 'name', 'unknown_tool')
    print(f"    DEBUG: Defining wrapper function for tool: '{tool_name}'")

    # Define the actual wrapper coroutine
    async def dynamic_tool_wrapper(tool_to_run=tool_instance, **kwargs): # Bind instance
        _tool_name = tool_to_run.name
        log_file = "/tmp/mcp_wrapper.log"; 
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S"); 
        log_prefix = f"--- {timestamp} WRAPPER for '{_tool_name}' ---"
        log_lines = [f"{log_prefix} START", f"Received kwargs: {kwargs}"]
        try: # Main execution block
            result = None
            if hasattr(tool_to_run, '_arun'):
                log_lines.append(f"Calling await tool_to_run._arun(**kwargs)")
                result = await tool_to_run._arun(**kwargs)
                log_lines.append(f"Await _arun completed.")
            elif hasattr(tool_to_run, '_run'):
                log_lines.append(f"Calling tool_to_run._run(**kwargs) via run_in_executor")
                loop = asyncio.get_running_loop()
                sync_func_with_args = functools.partial(tool_to_run._run, **kwargs)
                result = await loop.run_in_executor(None, sync_func_with_args)
                log_lines.append(f"Executor _run completed.")
            else: log_lines.append("ERROR: Tool no _arun/_run!"); raise NotImplementedError(f"Tool {_tool_name} no method.")

            log_lines.append(f"Raw result type: {type(result)}"); log_lines.append(f"Raw value snippet: {str(result)[:500]}...")
            final_result = result
            try: json.dumps(result); log_lines.append("Result JSON serializable.")
            except TypeError: log_lines.append(f"WARN: Non-JSON type {type(result)}.->str."); final_result = str(result)
            log_lines.append(f"Returning final (type {type(final_result)})."); log_lines.append(f"{log_prefix} END (Success)")
            return {"result": final_result}
        except Exception as e: # Catch execution errors
            log_lines.append(f"!!! EXCEPTION in tool exec for '{_tool_name}': {e} !!!"); tb_lines = traceback.format_exc().splitlines(); log_lines.append("--- Traceback ---"); log_lines.extend(tb_lines); log_lines.append("-----------------"); log_lines.append(f"{log_prefix} END (Exception)")
            return f"ERROR_EXECUTING_TOOL_{_tool_name}: {str(e)}" # Return error string
        finally: # Ensure logging
            try:
                for line in log_lines: print(line, flush=True, file=sys.stderr)
                with open(log_file, "a") as f: f.write("\n".join(log_lines) + "\n\n")
            except Exception as log_e: print(f"!!! Logging Error for tool {_tool_name}: {log_e} !!!", flush=True, file=sys.stderr)

    # Return the created wrapper function AND the original tool's metadata
    return dynamic_tool_wrapper, tool_name, getattr(tool_instance, 'description', f"Tool {tool_name}")

# --- Main Execution Logic ---
def main():
    parser = argparse.ArgumentParser(description='Start Mentis MCP Server (Direct Registration)')
    parser.add_argument('--transport', type=str, choices=['stdio', 'sse'], default='stdio'); parser.add_argument('--host', type=str, default='0.0.0.0'); parser.add_argument('--port', type=int, default=8000); parser.add_argument('--name', type=str, default='MentisMCP'); parser.add_argument('--tools', nargs='+'); parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    if args.debug: logger.setLevel(logging.DEBUG); print("DEBUG Logging Enabled")

    try:
        # --- 1. Preregister tools into the central registry ---
        if PREREGISTER_AVAILABLE:
             print("DEBUG: Calling preregister_core_tools...")
             preregister_core_tools() # This populates the registry
             print("DEBUG: preregister_core_tools finished.")
        else: print("DEBUG: Skipping preregister_core_tools (unavailable).")

        # --- 2. Create FastMCP instance ---
        print(f"DEBUG: Creating FastMCP instance: name='{args.name}'")
        fastmcp_kwargs = {}
        if args.transport == 'sse':
            if args.host: fastmcp_kwargs['host'] = args.host
            if args.port: fastmcp_kwargs['port'] = args.port
        mcp_instance = FastMCP(args.name, **fastmcp_kwargs) # Create instance directly
        print(f"DEBUG: FastMCP instance created.")

        # --- 3. Load tools from registry and register wrappers with FastMCP ---
        registered_count = 0
        target_tools = args.tools # List of names, or None for all

        # Get all tools first if needed
        all_tools_dict = get_registered_tools(as_dict=True)

        tools_to_register = {}
        if target_tools: # Filter if specific tools requested
             print(f"DEBUG: Filtering for specific tools: {target_tools}")
             for name in target_tools:
                  if name in all_tools_dict:
                       tools_to_register[name] = all_tools_dict[name]
                  else:
                       print(f"ERROR: Requested tool '{name}' not found in registry.")
        else: # Register all tools found in registry
             print("DEBUG: Registering all tools found in registry...")
             tools_to_register = all_tools_dict

        # Iterate and register the selected tools
        print(f"DEBUG: Attempting to register {len(tools_to_register)} tools with FastMCP...")
        for tool_name, tool_info in tools_to_register.items():
            tool_instance = tool_info.get("tool")
            if isinstance(tool_instance, BaseTool):
                 try:
                      # Create the wrapper function and get metadata
                      wrapper_func, name, description = create_tool_wrapper(tool_instance)
                      # Register the wrapper directly using the mcp_instance decorator method
                      mcp_instance.tool(name=name, description=description)(wrapper_func)
                      print(f"DEBUG: Successfully registered '{name}' with FastMCP.")
                      registered_count += 1
                 except Exception as e_register:
                      print(f"ERROR: Failed to register wrapper for tool '{tool_name}': {e_register}")
                      traceback.print_exc()
            else:
                 print(f"WARNING: Item '{tool_name}' not a BaseTool, skipping.")

        print(f"DEBUG: Tool registration complete. {registered_count} tools registered with FastMCP.")
        if registered_count == 0: print("WARNING: No tools were registered!")

        # --- 4. Run the FastMCP server ---
        print(f"Starting MCP Server '{args.name}' (Transport: {args.transport})...")
        mcp_instance.run(transport=args.transport)

    except KeyboardInterrupt: print("Server shutting down..."); sys.exit(0)
    except Exception as e: print(f"Error starting server: {e}"); traceback.print_exc(); sys.exit(1)

if __name__ == "__main__":
    main()