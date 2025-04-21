# /Users/peng/Dev/AI_AGENTS/mentis/super_agents/company_deep_research/main.py
# (Optimized Version - Accepts JSON Input)

import sys
from pathlib import Path
import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import Literal, List, Dict, Any, Optional # Ensure Optional is imported

# --- OpenAI RateLimitError Handling ---
try:
    from openai import RateLimitError
except ImportError:
    print("Warning: 'openai' package not installed. RateLimitError handling will use a basic Exception.")
    class RateLimitError(Exception):
        pass

# --- Dynamic Path Setup (Keep as is) ---
try:
    # ... (keep existing dynamic path setup code) ...
    current_script_path = Path(__file__).resolve()
    project_root = current_script_path.parent
    while not (project_root / '.git').exists() and project_root.parent != project_root:
        project_root = project_root.parent
    if not (project_root / '.git').exists():
        print("Warning: Could not automatically determine project root based on '.git'. Adding script's directory parent.")
        project_root = current_script_path.parent.parent
    path_to_add = project_root
    if str(path_to_add) not in sys.path:
        sys.path.insert(0, str(path_to_add))
    print(f"Dynamically added project root to sys.path: {path_to_add}")
except Exception as e:
    print(f"Error during dynamic path setup: {e}. Please ensure script is run from correct location or manually set PYTHONPATH.")
    exit(1)


# --- LangGraph and Internal Module Imports ---
try:
    from super_agents.company_deep_research.reason_graph.graph import get_mna_app_yfinance
    from super_agents.company_deep_research.reason_graph.state import ResearchState # Import updated state
    from super_agents.company_deep_research.reason_graph.schemas import StreamUpdate
except ImportError as e:
    print(f"Error importing graph components: {e}")
    print(f"Please ensure all required files exist in 'reason_graph' and dependencies are installed.")
    exit(1)
except Exception as e:
    print(f"An unexpected error occurred during imports: {e}")
    exit(1)


# --- Helper Function for Filenames (Keep as is) ---
def slugify(text: str) -> str:
    """Converts text into a safe filename component."""
    if not text:
        return "no_topic_provided"
    core_text = text.split(" (")[0].split(" ")[0]
    if not core_text: core_text = text
    core_text = core_text.lower()
    core_text = re.sub(r'\s+', '_', core_text)
    core_text = re.sub(r'[^\w\-\.]+', '', core_text)
    core_text = core_text.strip('_.- ')
    return core_text[:50] if core_text else "sanitized_topic"

# --- **NEW**: Function to create initial state from JSON ---
def create_initial_state_from_json(input_data: Dict[str, Any], depth: Literal['basic', 'detailed']) -> ResearchState:
    """Creates the initial ResearchState dictionary from the input JSON data."""
    if not input_data.get("identifier_ric") or not input_data.get("company_name"):
        raise ValueError("Input JSON must contain non-empty 'identifier_ric' and 'company_name'.")

    # Use .get with appropriate defaults (e.g., None or specific like 'N/A', 0.0)
    # Storing None is okay if subsequent nodes handle it correctly.
    state: ResearchState = {
        "identifier_ric": input_data["identifier_ric"],
        "company_name": input_data["company_name"],
        "country_of_exchange": input_data.get("country_of_exchange"), # Default is None if not present
        "market_cap_usd": input_data.get("market_cap_usd"), # Default is None
        "input_business_description": input_data.get("business_description"), # Default is None
        "input_pe_ratio": input_data.get("pe_timeseries_ratio"), # Default is None
        "input_ebitda_usd": input_data.get("ebitda_fy0_usd"), # Default is None
        "input_query_date": input_data.get("query_date"), # Default is None

        # Initialize other fields
        "topic": f"M&A Research for {input_data['company_name']} ({input_data['identifier_ric']})",
        "ticker": input_data["identifier_ric"],
        "max_search_iterations": 3,
        "max_analysis_steps": 5,
        "analysis_depth": depth,
        "research_plan": None,
        "search_steps_planned": [],
        "financial_web_search_steps": [],
        "analysis_steps_planned": [],
        "current_analysis_step_index": 0,
        "completed_web_search_count": 0, # Initialize counter
        "yfinance_data": None,
        "yfinance_fetch_failed": False,
        "search_results": [],
        "financial_web_search_results": [],
        "analysis_results": [],
        "financial_analysis": None,
        "competitive_analysis": None,
        "management_governance_assessment": None,
        "gaps_identified": None,
        "gap_search_results": [],
        "final_synthesis": None,
        "final_report_markdown": None,
        "structured_summary_table": None,
        "stream_updates": [],
        "completed_steps_count": 0.0,
        "total_steps": None,
        "error_message": None
    }
    return state

# --- Main Research Execution Function ---
async def run_research(initial_state: ResearchState): # Takes pre-filled state
    """
    Runs the M&A research graph using the provided initial state,
    handling streaming output and errors. Saves the final report.
    """
    company_name = initial_state['company_name']
    ticker = initial_state['ticker']
    depth = initial_state['analysis_depth']

    print("\n--- Starting M&A Research Graph (Optimized - JSON Input) ---")
    print(f"Company Name: '{company_name}'")
    print(f"Ticker/RIC: '{ticker}'")
    print(f"Analysis Depth: '{depth}'")
    print("-" * 30)

    processed_updates_count = 0
    config = {"recursion_limit": 150}
    final_state: Optional[ResearchState] = None
    error_occurred: Optional[Exception] = None

    # --- Streaming Execution ---
    try:
        research_app = get_mna_app_yfinance(for_web=False)
        async for state_update_chunk in research_app.astream(initial_state, config=config, stream_mode="values"):
            final_state = state_update_chunk
            all_current_updates: List[Dict] = final_state.get("stream_updates", [])
            new_updates_count = len(all_current_updates) - processed_updates_count

            if new_updates_count > 0:
                newly_added_updates = all_current_updates[processed_updates_count:]
                print(f"--- Processing {new_updates_count} New Stream Update(s) ---")
                for update_dict in newly_added_updates:
                    update_data = update_dict.get('data', {})
                    status = update_data.get('status', 'N/A')
                    step_id = update_data.get('id', 'N/A')
                    msg = update_data.get('message', '')
                    update_type = update_data.get('type', 'N/A')
                    title = update_data.get('title', '')
                    print(f"[{datetime.fromtimestamp(update_dict.get('timestamp', time.time())):%H:%M:%S}] "
                          f"[{update_type.upper()}|{status.upper()}|ID:{step_id}] "
                          f"{title+': ' if title else ''}{msg}")
                    payload = update_data.get('payload')
                    # (Keep payload preview logic as before)
                    if payload:
                         try:
                             payload_preview = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
                             if len(payload_preview) > 500: payload_preview = payload_preview[:500] + "..."
                             print(f"  Payload Preview: {payload_preview}")
                         except Exception as json_e: print(f"  Payload Preview: [Could not serialize: {json_e}]")

                print("-" * 30)
                processed_updates_count = len(all_current_updates)

    except RateLimitError as e:
        error_occurred = e
        print("\n" + "="*40 + "\n!!! OpenAI API Error: Insufficient Quota !!!\n" + "="*40 + "\n")
        # (Keep detailed error message)
        print("The research process was stopped due to OpenAI quota limits.")
        print("Please check your OpenAI plan and billing details.")
        print(f"Original error: {e}")
    except ImportError as e:
        error_occurred = e
        print("\n" + "="*40 + "\n!!! Python Import Error !!!\n" + "="*40 + "\n")
        # (Keep detailed error message)
        print(f"Could not import necessary modules: {e}")
        print("Please ensure all dependencies are installed and the project structure is correct.")
    except Exception as e:
        error_occurred = e
        print("\n" + "="*40 + "\n!!! An Unexpected Error Occurred During Graph Execution !!!\n" + "="*40 + "\n")
        # (Keep detailed error message)
        print(f"Error type: {type(e).__name__}")
        print(f"Error details: {e}")
        import traceback
        traceback.print_exc()


    # --- Process Final State ---
    if error_occurred:
         print("\n--- Graph Execution INTERRUPTED by Error ---")
         print("Attempting to process the last known state (may be incomplete).")
    else:
         print("\n--- Graph Execution Finished ---")

    # Check if final_state is valid before proceeding
    if not final_state or not isinstance(final_state, dict):
         print("Error: Final state is invalid or unavailable after execution.")
         error_report = f"# Research Failed\n\nCompany: {initial_state['company_name']} ({initial_state['ticker']})\nReason: Workflow execution failed to produce a valid final state."
         if error_occurred: error_report += f"\nError Details: {type(error_occurred).__name__}: {error_occurred}"
         # (Keep minimal error report saving logic)
         try:
             topic_slug = slugify(initial_state['ticker']) # Use ticker for filename slug
             timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
             filename = f"research_ERROR_{topic_slug}_{timestamp}.md"
             script_dir = Path(__file__).parent
             output_dir = script_dir / "Output"
             output_dir.mkdir(parents=True, exist_ok=True)
             filepath = output_dir / filename
             with open(filepath, "w", encoding="utf-8") as f: f.write(error_report)
             print(f"Saved error summary to: {filepath}")
         except Exception as save_e: print(f"Could not save error summary report: {save_e}")
         return None # Indicate failure

    # --- Print Final State Summary ---
    print("\n--- FINAL STATE SUMMARY (May be partial if error occurred) ---")
    print(f"Company Name: {final_state.get('company_name', 'N/A')}")
    print(f"Ticker/RIC: {final_state.get('ticker', 'N/A')}")
    print(f"Depth: {final_state.get('analysis_depth', 'N/A')}")
    print(f"Completed Steps Count: {final_state.get('completed_steps_count', 'N/A')}")
    print(f"Total Steps Estimated: {final_state.get('total_steps', 'N/A')}")
    yf_failed = final_state.get('yfinance_fetch_failed', False)
    yf_data = final_state.get('yfinance_data')
    yf_error_msg = "Fetch Failed/Skipped" if yf_failed else (yf_data.get('error', 'None') if isinstance(yf_data, dict) else 'N/A')
    print(f"Yahoo Finance Fetch Status: {'FAILED (Used Web Fallback)' if yf_failed else 'OK'}")
    if yf_error_msg != 'None': print(f"  YF Error Message: {yf_error_msg}")
    print(f"General Web Searches Planned/Executed: {len(final_state.get('search_steps_planned', []))} / {final_state.get('current_search_step_index', 0)}")
    print(f"Financial Web Searches (Fallback) Planned/Executed: {len(final_state.get('financial_web_search_steps', []))} / {final_state.get('current_financial_web_search_index', 0) if yf_failed else 'N/A'}") # Adjust index key maybe
    print(f"Analysis Steps Performed: {final_state.get('current_analysis_step_index', 0)}")
    print(f"Total Web Results Collected (All): {len(final_state.get('search_results', []) + final_state.get('financial_web_search_results', []) + final_state.get('gap_search_results', []))}")
    print(f"Final Synthesis Generated: {'Yes' if final_state.get('final_synthesis') else 'No'}")
    print(f"Summary Table Generated: {'Yes' if final_state.get('structured_summary_table') else 'No'}")


    # --- Save Final Report ---
    final_markdown = final_state.get('final_report_markdown')

    if final_markdown and isinstance(final_markdown, str):
        if "Report Generation Failed" in final_markdown and not error_occurred:
             print("\n--- Final Report Generation Node Failed ---")
             print(final_markdown.split('\n\n', 1)[-1])
             print("Report not saved.")
        elif not error_occurred:
             print("\n--- Saving Final Report to Markdown ---")
             try:
                 filename_base = final_state['ticker'] # Use ticker for filename
                 topic_slug = slugify(filename_base)
                 timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                 filename = f"research_report_{topic_slug}_{timestamp}.md"
                 script_dir = Path(__file__).parent
                 output_dir = script_dir / "Output"
                 output_dir.mkdir(parents=True, exist_ok=True)
                 filepath = output_dir / filename
                 with open(filepath, "w", encoding="utf-8") as f: f.write(final_markdown)
                 print(f"Successfully saved report to: {filepath}")
             except Exception as e:
                 print(f"\nError saving final report to Markdown: {e}")
                 print("Report content was:\n" + final_markdown[:1000] + "...")
        else:
             # Error occurred, but report might exist (e.g., from finalize node)
             print("\nFinal Report: Not saved due to earlier execution error.")
             print("Partial/Fallback report content (if available):\n" + str(final_markdown)[:1000] + "...")

    elif error_occurred:
         print("\nFinal Report: Not generated or incomplete due to execution error.")
    else:
         print("\nFinal Report: Not found in final state.")

    print("\n--- END OF RESEARCH ---")
    return final_state


# --- Main Execution Block ---
async def main():
     # **MODIFIED: Accept JSON file path or JSON string as argument**
     if len(sys.argv) < 2:
         print("Usage: python main.py <path_to_json_file_or_json_string>")
         print("Example (File): python main.py input_data/9417.T.json")
         print("Example (String): python main.py '{\"identifier_ric\": \"AAPL\", \"company_name\": \"Apple Inc.\"}'")
         return

     input_arg = sys.argv[1]
     input_json_data = None

     try:
         # Try to load as file path first
         input_path = Path(input_arg)
         if input_path.is_file():
             print(f"Loading input data from file: {input_path}")
             with open(input_path, 'r', encoding='utf-8') as f:
                 input_json_data = json.load(f)
         else:
             # Try to load as JSON string
             print("Input is not a file path, attempting to parse as JSON string.")
             input_json_data = json.loads(input_arg)
     except json.JSONDecodeError:
         print(f"Error: Input argument '{input_arg}' is neither a valid file path nor a valid JSON string.")
         return
     except FileNotFoundError:
         print(f"Error: Input file not found at '{input_arg}'")
         return
     except Exception as e:
         print(f"Error processing input argument: {e}")
         return

     if not input_json_data or not isinstance(input_json_data, dict):
         print("Error: Parsed input data is not a valid JSON object.")
         return

     # Get analysis depth (optional second argument or default)
     depth_input = sys.argv[2].strip().lower() if len(sys.argv) > 2 else 'detailed'
     depth: Literal['basic', 'detailed'] = 'basic' if depth_input == 'basic' else 'detailed'

     # Create initial state from JSON
     try:
          initial_research_state = create_initial_state_from_json(input_json_data, depth)
     except ValueError as ve:
          print(f"Error creating initial state: {ve}")
          return
     except Exception as state_e:
          print(f"Unexpected error creating initial state: {state_e}")
          return


     # Run the research process
     await run_research(initial_research_state)

if __name__ == "__main__":
    try:
        print("Starting M&A Deep Research Runner (Optimized)...")
        if sys.version_info < (3, 8): # Asyncio.run needs 3.7+, some async features better in 3.8+
             print("Warning: Python 3.8+ recommended for best asyncio performance.")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nResearch process interrupted by user (Ctrl+C).")
    except Exception as e:
        print(f"\nA critical error occurred in the main execution block: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nProgram finished.")