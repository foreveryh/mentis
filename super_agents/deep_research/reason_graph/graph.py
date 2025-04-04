from typing import Literal
from langgraph.graph import StateGraph, END
from super_agents.deep_research.reason_graph.state import ResearchState
from super_agents.deep_research.reason_graph.nodes import (
    plan_research,
    prepare_steps,
    execute_search,
    perform_analysis,
    analyze_gaps,
    execute_gap_search,
    synthesize_final_report,
    finalize_basic_research,
    generate_final_markdown_report 
    # These are the functions that will be used as nodes in the graph
)
# --- Conditional Edge Functions ---

def should_continue_search(state: ResearchState) -> Literal["execute_search", "perform_analysis"]:
    """Decides whether to continue searching or move to analysis."""
    if state['current_search_step_index'] < len(state['search_steps_planned']):
        return "execute_search"
    else:
        # Check if analysis steps exist before proceeding
        if state['analysis_steps_planned']:
             return "perform_analysis"
        else:
             # If no analysis steps, go directly to gap analysis
             return "analyze_gaps"


def should_continue_analysis(state: ResearchState) -> Literal["perform_analysis", "analyze_gaps"]:
    """Decides whether to continue analysis or move to gap analysis."""
    if state['current_analysis_step_index'] < len(state['analysis_steps_planned']):
        return "perform_analysis"
    else:
        return "analyze_gaps"

def decide_gap_followup(state: ResearchState) -> Literal["execute_gap_search", "synthesize_final_report", "finalize_basic"]:
    """Decides whether to perform gap searches, synthesize, or end."""
    depth = state['depth']
    gap_analysis = state.get('gap_analysis')
    additional_queries = state.get('additional_queries_planned', [])
    current_gap_index = state.get('current_gap_search_index', 0)

    if depth == 'advanced' and gap_analysis and additional_queries:
        if current_gap_index < len(additional_queries):
             return "execute_gap_search" 
        else:
             # Finished gap searches, proceed to final synthesis
             return "synthesize_final_report" 
    else:
        # Basic depth, or advanced with no gaps/failed gap analysis/no queries from gaps
        return "finalize_basic_research" # Use correct function name

# --- Build the Graph ---

workflow = StateGraph(ResearchState)

# Add Nodes
workflow.add_node("plan_research", plan_research)
workflow.add_node("prepare_steps", prepare_steps)
workflow.add_node("execute_search", execute_search)
workflow.add_node("perform_analysis", perform_analysis)
workflow.add_node("analyze_gaps", analyze_gaps)
workflow.add_node("execute_gap_search", execute_gap_search)
workflow.add_node("synthesize_final_report", synthesize_final_report)
workflow.add_node("finalize_basic_research", finalize_basic_research)
workflow.add_node("generate_final_markdown_report", generate_final_markdown_report) # <-- Add new node



# Define Edges
workflow.set_entry_point("plan_research")
workflow.add_edge("plan_research", "prepare_steps")
workflow.add_edge("prepare_steps", "execute_search") # Start search loop

# Search Loop
workflow.add_conditional_edges(
    "execute_search",
    should_continue_search,
    { "execute_search": "execute_search", "perform_analysis": "perform_analysis", "analyze_gaps": "analyze_gaps" }
)

# Analysis Loop
workflow.add_conditional_edges(
    "perform_analysis",
    should_continue_analysis,
    { "perform_analysis": "perform_analysis", "analyze_gaps": "analyze_gaps" }
)

# Gap Analysis Follow-up Logic
workflow.add_conditional_edges(
    "analyze_gaps",
    decide_gap_followup,
    { "execute_gap_search": "execute_gap_search", "synthesize_final_report": "synthesize_final_report", "finalize_basic_research": "finalize_basic_research" } # Point to correct basic finalizer
)

# Gap Search Loop & Synthesis
workflow.add_conditional_edges(
    "execute_gap_search",
    decide_gap_followup, 
    { "execute_gap_search": "execute_gap_search", "synthesize_final_report": "synthesize_final_report", "finalize_basic_research": "finalize_basic_research" } # Point to correct basic finalizer
)

# --- Adjust Final Edges ---
# If synthesis succeeds, go to report generation
workflow.add_edge("synthesize_final_report", "generate_final_markdown_report") 
# If report generation succeeds, END
workflow.add_edge("generate_final_markdown_report", END) 
# If flow goes to basic finalizer, END
workflow.add_edge("finalize_basic_research", END) 

# Compile the graph
app = workflow.compile()