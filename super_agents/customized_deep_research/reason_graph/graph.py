# /Users/peng/Dev/AI_AGENTS/mentis/super_agents/company_deep_research/reason_graph/graph.py
# (Optimized Version v2 - Adjusted Conditional Logic)

from typing import Literal, Optional, Dict, Any
from langgraph.graph import StateGraph, END, START

# Use updated state definition
from .state import ResearchState
# Import updated node functions
from .nodes import (
    initialize_research,
    plan_research,
    prepare_steps,
    fetch_financial_data,
    execute_search, # Handles both financial and general web searches now
    perform_analysis,
    analyze_gaps,
    execute_gap_search,
    synthesize_final_report,
    finalize_basic_research,
    generate_final_markdown_report
)

# --- Conditional Edge Functions (Revised) ---

def check_initialization(state: ResearchState) -> Literal["plan_research", "finalize_basic_research"]:
    """Decides whether to proceed after initialization."""
    # Initialization now primarily uses guaranteed JSON input
    if state.get('ticker') and state.get('company_name'):
        print("[Graph Condition] Initialization successful (used JSON input), proceeding to plan.")
        # Initialize web search count here
        state['completed_web_search_count'] = 0
        return "plan_research"
    else:
        # This path should ideally not be hit if main.py enforces JSON input
        print("[Graph Condition] Initialization failed (missing core data from state), finalizing.")
        state['error_message'] = "Initialization failed: Missing core company info."
        return "finalize_basic_research"

def check_planning(state: ResearchState) -> Literal["prepare_steps", "finalize_basic_research"]:
     """Checks if the research plan was successfully generated."""
     if state.get("research_plan"):
         print("[Graph Condition] Planning successful, proceeding to prepare steps.")
         return "prepare_steps"
     else:
         print("[Graph Condition] Planning failed or plan is empty, finalizing research.")
         return "finalize_basic_research"

# --- REVISED Web Search Continuation Logic ---
def should_continue_web_search(state: ResearchState) -> Literal["execute_search", "perform_analysis", "analyze_gaps"]:
    """Decides whether to continue web searching (financial fallback or general) or move to analysis."""
    completed_count = state.get('completed_web_search_count', 0)
    yfinance_failed = state.get('yfinance_fetch_failed', False)

    # Calculate total web searches needed
    financial_searches_planned = state.get('financial_web_search_steps', [])
    general_searches_planned = state.get('search_steps_planned', [])
    total_web_searches_needed = 0
    if yfinance_failed:
        total_web_searches_needed += len(financial_searches_planned)
    total_web_searches_needed += len(general_searches_planned)

    print(f"[Graph Condition Check] Web Searches: Completed={completed_count}, Total Needed={total_web_searches_needed}")

    if completed_count < total_web_searches_needed:
        # If there are more web searches planned (either type), continue the loop.
        print(f"[Graph Condition] Continue web search ({completed_count + 1}/{total_web_searches_needed}).")
        return "execute_search"
    else:
        # If all planned web searches are done, check if analysis is needed.
        analysis_steps_planned = state.get('analysis_steps_planned', [])
        if analysis_steps_planned and isinstance(analysis_steps_planned, list) and len(analysis_steps_planned) > 0:
             # If analysis steps exist, move to the analysis phase.
             print("[Graph Condition] All applicable web searches complete. Moving to analysis.")
             return "perform_analysis"
        else:
             # If no analysis steps were planned, skip analysis and go directly to gap identification.
             print("[Graph Condition] All applicable web searches complete, no analysis planned. Moving to gap analysis.")
             return "analyze_gaps"


def should_continue_analysis(state: ResearchState) -> Literal["perform_analysis", "analyze_gaps"]:
    """Decides whether to continue executing planned analysis steps or move to gap analysis."""
    current_analysis_index = state.get('current_analysis_step_index', 0)
    analysis_steps_planned = state.get('analysis_steps_planned', [])
    if not isinstance(analysis_steps_planned, list): analysis_steps_planned = [] # Safety check
    max_steps = state.get('max_analysis_steps', 5) # Use configured max steps

    if current_analysis_index < len(analysis_steps_planned) and current_analysis_index < max_steps:
        # If more analysis steps are left within plan and limit, continue the loop.
        print(f"[Graph Condition] Continue analysis ({current_analysis_index + 1}/{len(analysis_steps_planned)}, Max: {max_steps}).")
        return "perform_analysis"
    else:
        if current_analysis_index >= max_steps:
            print(f"[Graph Condition] Reached max analysis steps ({max_steps}). Moving to gap analysis.")
        else:
            print("[Graph Condition] All planned analysis steps complete. Moving to gap analysis.")
        return "analyze_gaps"

def decide_gap_followup(state: ResearchState) -> Literal["execute_gap_search", "synthesize_final_report"]:
    """Decides whether to execute gap-filling web searches or move to synthesis."""
    gaps = state.get('gaps_identified')
    # Check if gap analysis suggested *actionable* web follow-up queries
    # AND if the gap search node hasn't already run (check presence/content of gap_search_results)
    has_run_gap_search = len(state.get('gap_search_results', [])) > 0
    follow_up_queries_exist = gaps and gaps.follow_up_queries and isinstance(gaps.follow_up_queries, list) and len(gaps.follow_up_queries) > 0

    if follow_up_queries_exist and not has_run_gap_search:
         print("[Graph Condition] Actionable gaps identified with web search suggestions, proceeding to execute gap search.")
         return "execute_gap_search"
    else:
        if has_run_gap_search:
             print("[Graph Condition] Gap search already performed or skipped previously. Moving to synthesis.")
        elif not follow_up_queries_exist:
             print("[Graph Condition] No actionable web follow-up needed based on gap analysis. Moving to synthesis.")
        else: # Should not happen but safety catch
             print("[Graph Condition] Unexpected state in gap decision. Moving to synthesis.")
        return "synthesize_final_report"

def check_synthesis(state: ResearchState) -> Literal["generate_final_markdown_report", "finalize_basic_research"]:
     """Checks if the synthesis step was successful before generating the final report."""
     final_synthesis = state.get("final_synthesis")
     # Check if synthesis result exists and has non-empty key findings
     if final_synthesis and hasattr(final_synthesis, 'key_findings_summary') and final_synthesis.key_findings_summary and \
        "fail" not in final_synthesis.key_findings_summary.lower(): # Basic check for failure text
         print("[Graph Condition] Synthesis successful, proceeding to report generation.")
         return "generate_final_markdown_report"
     else:
         print("[Graph Condition] Synthesis failed, missing, or empty, finalizing research.")
         state['error_message'] = "Synthesis failed or produced empty results." # Set error
         return "finalize_basic_research"


# --- Build the Optimized M&A Workflow ---
def build_mna_research_graph_yfinance_optimized(for_web: bool = False) -> StateGraph:
    """
    Builds the LangGraph StateGraph for M&A preliminary research (Optimized Version).
    """
    workflow = StateGraph(ResearchState)

    # --- Define Nodes ---
    workflow.add_node("initialize_research", initialize_research)
    workflow.add_node("plan_research", plan_research)
    workflow.add_node("prepare_steps", prepare_steps)
    workflow.add_node("fetch_financial_data", fetch_financial_data)
    workflow.add_node("execute_search", execute_search) # Handles both search types
    workflow.add_node("perform_analysis", perform_analysis)
    workflow.add_node("analyze_gaps", analyze_gaps)
    workflow.add_node("execute_gap_search", execute_gap_search)
    workflow.add_node("synthesize_final_report", synthesize_final_report)
    workflow.add_node("generate_final_markdown_report", generate_final_markdown_report)
    workflow.add_node("finalize_basic_research", finalize_basic_research)

    # --- Define Edges ---

    # 1. Set Entry Point
    workflow.set_entry_point("initialize_research")

    # 2. Initialization to Planning (Conditional)
    workflow.add_conditional_edges(
        "initialize_research",
        check_initialization,
        {"plan_research": "plan_research", "finalize_basic_research": "finalize_basic_research"}
    )

    # 3. Planning to Prepare Steps (Conditional)
    workflow.add_conditional_edges(
        "plan_research",
        check_planning,
        {"prepare_steps": "prepare_steps", "finalize_basic_research": "finalize_basic_research"}
    )

    # 4. Prepare Steps to Fetching Financial Data
    # Always attempt YF fetch after preparing steps (node handles failure flag).
    workflow.add_edge("prepare_steps", "fetch_financial_data")

    # 5. Fetch Financial Data to Starting Web Search
    # Always proceed to execute_search node after fetch attempt.
    # execute_search node internally decides which searches to run based on YF flag.
    workflow.add_edge("fetch_financial_data", "execute_search")

    # 6. Web Search Loop (Handles both Financial Fallback and General)
    # **MODIFIED Condition:** Uses the revised condition function.
    workflow.add_conditional_edges(
        "execute_search",
        should_continue_web_search, # Uses revised logic checking total searches needed vs completed
        {
            "execute_search": "execute_search", # Loop back if more searches needed
            "perform_analysis": "perform_analysis", # Move to analysis if searches done & analysis planned
            "analyze_gaps": "analyze_gaps" # Move to gaps if searches done & no analysis planned
        }
    )

    # 7. Analysis Loop to Gap Analysis
    workflow.add_conditional_edges(
        "perform_analysis",
        should_continue_analysis, # Function checks if more analysis steps are planned within limits
        {"perform_analysis": "perform_analysis", "analyze_gaps": "analyze_gaps"}
    )

    # 8. Gap Analysis to Gap Search or Synthesis
    workflow.add_conditional_edges(
        "analyze_gaps",
        decide_gap_followup, # Checks for *actionable* web follow-ups
        {"execute_gap_search": "execute_gap_search", "synthesize_final_report": "synthesize_final_report"}
    )

    # 9. After Gap Search (if run) to Synthesis
    # Always go to synthesis after attempting gap search.
    workflow.add_edge("execute_gap_search", "synthesize_final_report")

    # 10. Synthesis to Final Report (Conditional)
    workflow.add_conditional_edges(
        "synthesize_final_report",
        check_synthesis, # Checks if synthesis result is valid
        {"generate_final_markdown_report": "generate_final_markdown_report", "finalize_basic_research": "finalize_basic_research"}
    )

    # 11. Final Report to END
    workflow.add_edge("generate_final_markdown_report", END)

    # 12. Fallback End Path
    workflow.add_edge("finalize_basic_research", END)

    print("M&A Research Graph Built (Optimized JSON Input & YF Fallback Version).")
    return workflow

# --- Build and Compile ---
graph_app_builder = build_mna_research_graph_yfinance_optimized

# Compile the graph instance for script execution
app_mna_yf_opt = graph_app_builder(for_web=False).compile()
# Optionally compile for web if needed
# web_app_mna_yf_opt = graph_app_builder(for_web=True).compile()

# --- Function for main.py to Import ---
def get_mna_app_yfinance(for_web: bool = False) -> Any:
    """Returns the compiled optimized M&A graph."""
    print(f"[Graph Module] Providing compiled OPTIMIZED graph instance (for_web={for_web})...")
    # if for_web:
    #     return web_app_mna_yf_opt # If you have a web version
    # else:
    return app_mna_yf_opt # Return the optimized version