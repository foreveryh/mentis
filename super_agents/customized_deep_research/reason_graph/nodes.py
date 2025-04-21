# /Users/peng/Dev/AI_AGENTS/mentis/super_agents/company_deep_research/reason_graph/nodes.py
# (Optimized Version)

import re
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Literal, Optional
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# --- Internal Imports ---
from .state import ResearchState, YFinanceData
from .schemas import (
    SearchQuery, RequiredAnalysis, AnalysisResult, GapAnalysisResult, GapFollowUpQuery,
    FinalSynthesisResult, SearchStepResult, SearchResultItem, StreamUpdate, StepInfo, ResearchPlan, KeyFinding
)
from .tools import (
    llm, llm_creative, generate_structured_output,
    perform_web_search,
    fetch_yfinance_data,
    create_update # Use the corrected helper
)
from .prompt import (
    PLAN_RESEARCH_PROMPT_YFINANCE,
    FINAL_REPORT_SYSTEM_PROMPT_TEMPLATE_YFINANCE_ONLY,
    FINANCIAL_ANALYSIS_PROMPT_YFINANCE,
    COMPETITIVE_ANALYSIS_PROMPT_YFINANCE,
    MANAGEMENT_GOVERNANCE_PROMPT_YFINANCE,
    GAP_ANALYSIS_PROMPT_YFINANCE,
    SYNTHESIS_PROMPT_YFINANCE
)
# Import logger from tools if defined there, or set up locally
# from .tools import logger # Assuming logger is setup in tools.py
# Fallback basic logger if not imported
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')


# --- Node Functions (Optimized Version) ---

async def initialize_research(state: ResearchState) -> Dict[str, Any]:
    """Initializes research using guaranteed JSON input fields."""
    # Assumes state is pre-populated with JSON input by main.py
    identifier_ric = state['identifier_ric'] # Guaranteed
    company_name = state['company_name'] # Guaranteed
    step_id = 'initialize-research'

    # Use guaranteed fields directly
    ticker = identifier_ric # Use RIC as the ticker for yfinance
    research_topic = f"M&A Preliminary Deep Research for {company_name} ({ticker})"

    logger.info(f"--- Running Node: initialize_research ({company_name} / {ticker}) ---")
    logger.info(f"Using guaranteed input: Ticker='{ticker}', Name='{company_name}'")
    # Log optional fields if present
    for key in ['country_of_exchange', 'market_cap_usd', 'input_business_description', 'input_pe_ratio', 'input_ebitda_usd', 'input_query_date']:
        if state.get(key):
            logger.info(f"Input {key}: {state[key]}")

    message = f"Initialization complete. Target: {company_name} ({ticker})"
    status = 'completed'
    # Corrected create_update call
    all_updates = create_update(state, {
        'id': step_id,
        'type': 'setup',
        'status': status,
        'title': 'Initialize Research',
        'message': message,
        'overwrite': True
    })
    # Corrected create_update call for progress
    all_updates.extend(create_update(state, {
        'id': 'research-progress',
        'type': 'progress',
        'status': 'running',
        'title': 'Research Progress',
        'completedSteps': 0.5,
        'message':'Initialization complete, planning research...',
        'overwrite': True
    }))

    logger.info(f"--- Exiting Node: initialize_research ---")
    # Return minimal update as core info is already in state
    return {
        "topic": research_topic, # Set derived topic
        "ticker": ticker, # Ensure ticker is explicitly set from RIC
        "yfinance_fetch_failed": False, # Initialize YF status flag
        "stream_updates": state.get('stream_updates', []) + all_updates
    }


async def plan_research(state: ResearchState) -> Dict[str, Any]:
    """Generates research plan, adapting based on yfinance fetch status."""
    ticker = state['ticker'] # Guaranteed from init
    company_name = state['company_name'] # Guaranteed from init
    topic = state['topic'] # Derived topic string
    yfinance_failed = state.get('yfinance_fetch_failed', False) # Check YF status flag
    step_id = 'research-plan-initial'

    all_updates = create_update(state, {
        'id': step_id, 'type': 'plan', 'status': 'running',
        'title': 'Research Plan', 'message': 'Creating research plan...', 'overwrite': True
    })
    logger.info(f"\n--- Running Node: plan_research (Target: {company_name} / {ticker}) ---")
    logger.info(f"Yahoo Finance fetch status (before plan): {'Failed' if yfinance_failed else 'Assumed OK / Pending'}")

    # Prepare context for the planning prompt, including initial JSON data
    yfinance_status_text = "Failed" if yfinance_failed else "Successful" # Text for prompt
    country = state.get('country_of_exchange', 'N/A')
    market_cap = state.get('market_cap_usd', 'N/A')
    ebitda = state.get('input_ebitda_usd', 'N/A')
    query_date = state.get('input_query_date', 'N/A')
    business_desc = state.get('input_business_description', 'N/A')


    plan_prompt = PLAN_RESEARCH_PROMPT_YFINANCE.format(
        company_name=company_name,
        ticker=ticker,
        country=country,
        market_cap=market_cap,
        ebitda=ebitda,
        query_date=query_date,
        business_desc=business_desc,
        yfinance_status=yfinance_status_text
        # topic=topic # Topic string might be less useful now
    )

    try:
        research_plan_result: Optional[ResearchPlan] = await generate_structured_output(
            llm_creative, ResearchPlan, plan_prompt
        )

        if not research_plan_result:
             raise ValueError("Research plan generation failed or yielded empty result.")

        # Separate planned steps
        search_steps_planned = research_plan_result.search_queries if research_plan_result.search_queries else []
        analysis_steps_planned = research_plan_result.required_analyses if research_plan_result.required_analyses else []

        # Filter out yfinance step if YF failed - it shouldn't be planned anyway based on prompt, but double-check.
        if yfinance_failed:
            search_steps_planned = [s for s in search_steps_planned if s.tool_hint != 'yfinance']
            num_yfinance_steps = 0
        else:
             num_yfinance_steps = sum(1 for s in search_steps_planned if s.tool_hint == 'yfinance')

        # Separate financial web searches if YF failed (assuming they are generated by the prompt)
        financial_web_search_steps = []
        other_web_search_steps = []
        if yfinance_failed:
             # Heuristic: Identify financial web searches based on keywords in query
             financial_keywords = ['revenue', 'profit', 'financials', 'market cap', 'ebitda', 'funding', 'financing', 'debt', 'valuation']
             for s in search_steps_planned:
                 if s.tool_hint == 'web_search' and any(keyword in s.query.lower() for keyword in financial_keywords):
                     financial_web_search_steps.append(s)
                 elif s.tool_hint == 'web_search': # Keep other web searches
                     other_web_search_steps.append(s)
             logger.info(f"YF failed. Identified {len(financial_web_search_steps)} potential financial web searches and {len(other_web_search_steps)} other web searches.")
             search_steps_planned = other_web_search_steps # Main loop handles non-financial web searches
        else:
             search_steps_planned = [s for s in search_steps_planned if s.tool_hint != 'yfinance'] # Remove YF step for web search loop

        num_web_search_steps = len(search_steps_planned)
        num_financial_web_search_steps = len(financial_web_search_steps)
        num_analysis_steps = len(analysis_steps_planned)
        # Adjust total steps estimate
        total_steps = 1 + 1 + (0 if yfinance_failed else 1) + num_web_search_steps + num_financial_web_search_steps + num_analysis_steps + 1 + 1 + 1 + 1

        message = f"Research plan created: {num_web_search_steps} general web searches, {num_financial_web_search_steps} financial web searches (YF fallback), {num_analysis_steps} analyses."
        if not yfinance_failed: message = f"Research plan created: 1 yfinance step, {num_web_search_steps} web searches, {num_analysis_steps} analyses."

        all_updates.extend(create_update(state, {
            'id': step_id, 'type': 'plan', 'status': 'completed', 'title': 'Research Plan',
            'message': message,
            'payload': research_plan_result.dict() if research_plan_result else {},
            'overwrite': True
        }))
        all_updates.extend(create_update(state, {
            'id': 'research-progress', 'type': 'progress', 'status': 'running', 'title': 'Research Progress',
            'message': 'Research plan complete.', 'completedSteps': 1.5, 'totalSteps': total_steps,
            'isComplete': False, 'overwrite': True
        }))

        logger.info("--- Exiting Node: plan_research (Success) ---")
        return {
            "research_plan": research_plan_result,
            "search_steps_planned": search_steps_planned, # General web searches
            "financial_web_search_steps": financial_web_search_steps, # Financial web searches (if YF failed)
            "analysis_steps_planned": analysis_steps_planned,
            "current_search_step_index": 0,
            "current_analysis_step_index": 0,
            "completed_steps_count": 1.5,
            "total_steps": total_steps,
            "stream_updates": state.get('stream_updates', []) + all_updates,
        }
    except Exception as e:
        logger.error(f"Error in plan_research: {e}", exc_info=True)
        error_updates = create_update(state, {
            'id': step_id, 'type': 'plan', 'status': 'error', 'title': 'Research Plan',
            'message': f"Failed to create plan: {e}", 'overwrite': True
            })
        progress_error = create_update(state, {
            'id': 'research-progress', 'type': 'progress', 'status': 'error', 'title': 'Research Progress',
            'message': 'Research planning failed.', 'isComplete': True, 'overwrite': True
            })
        logger.info("--- Exiting Node: plan_research (Error) ---")
        return {"stream_updates": state.get('stream_updates', []) + all_updates + error_updates + progress_error, "research_plan": None}


async def prepare_steps(state: ResearchState) -> Dict[str, Any]:
    """Prepares step info for UI, reflecting dynamic plan."""
    # Get planned steps from state
    yfinance_failed = state.get('yfinance_fetch_failed', False)
    web_search_steps = state.get('search_steps_planned', []) # General web searches
    financial_web_searches = state.get('financial_web_search_steps', []) # Financial web searches (if YF failed)
    analysis_steps = state.get('analysis_steps_planned', [])
    steps_info = []
    all_updates = state.get('stream_updates', [])
    logger.info("--- Running Node: prepare_steps ---")

    # Create StepInfo objects for UI display
    steps_info.append(StepInfo(id='initialize-research', type='setup', status='completed', title='Initialize Research', description=f"Target: {state['company_name']} ({state['ticker']})"))
    steps_info.append(StepInfo(id='research-plan-initial', type='plan', status='completed', title='Research Plan', description='Plan Created'))

    # Add YFinance Step OR Financial Web Search Steps
    if not yfinance_failed:
        steps_info.append(StepInfo(id='fetch-yfinance', type='data_fetch', status='pending', title='Fetch Yahoo Finance Data', description=f"Get financial data for {state['ticker']}"))
    else:
        for i, step in enumerate(financial_web_searches):
            steps_info.append(StepInfo(id=f'financial-web-search-{i}', type='search', status='pending', title=f"Financial Web Search #{i+1}", description=f"Alt for YF: {step.query[:60]}..." ))

    # Add General Web Search Steps
    for i, step in enumerate(web_search_steps):
        steps_info.append(StepInfo(id=f'web-search-{i}', type='search', status='pending', title=f"Web Search #{i+1}", description=step.query[:60]+"..." ))

    # Add Analysis Steps
    for i, step in enumerate(analysis_steps):
         steps_info.append(StepInfo(id=f'analysis-{i}', type='analysis', status='pending', title=f"Analysis #{i+1}", description=step.analysis_goal[:60]+"..." ))

    # Add Fixed Subsequent Steps
    steps_info.append(StepInfo(id='gap-analysis', type='analysis', status='pending', title='Identify Gaps', description='Analyze limitations.'))
    steps_info.append(StepInfo(id='gap-search', type='search', status='pending', title='Gap Filling Search', description='Follow-up web searches.'))
    steps_info.append(StepInfo(id='synthesis', type='synthesis', status='pending', title='Synthesize Findings', description='Combine all findings.'))
    steps_info.append(StepInfo(id='final-report', type='report', status='pending', title='Generate Final Report', description='Create final report.'))

    # Send steps list update
    all_updates.extend(create_update(state, {
        'id': 'research-steps-list',
        'type': 'steps_list',
        'status': 'completed',
        'title': 'Research Steps',
        'payload': [s.dict() for s in steps_info] # Use model_dump for Pydantic V2
    }))

    # Update total steps based on actual steps listed for better accuracy
    total_steps_actual = len(steps_info)
    if state.get('total_steps') != total_steps_actual:
        all_updates.extend(create_update(state, {
            'id': 'research-progress', 'type': 'progress', 'status': 'running',
            'title': 'Research Progress', 'totalSteps': total_steps_actual,
            'message': 'Steps prepared.', 'overwrite': True
            }))

    logger.info(f"--- Exiting Node: prepare_steps (Prepared {total_steps_actual} steps) ---")
    return {"stream_updates": all_updates, "total_steps": total_steps_actual} # Return updated total_steps


async def fetch_financial_data(state: ResearchState) -> Dict[str, Any]:
    """Fetches data using the yfinance tool and sets failure flag."""
    ticker = state['ticker'] # Guaranteed from init
    step_id = 'fetch-yfinance'
    yfinance_fetch_failed = False # Default to success initially
    all_updates = create_update(state, {
        'id': step_id, 'type': 'data_fetch', 'status': 'running',
        'title': 'Fetch Yahoo Finance Data', 'message': f"Fetching Yahoo Finance data for {ticker}...",
        'overwrite': True
    })
    logger.info(f"\n--- Running Node: fetch_financial_data ({ticker}) ---")

    yfinance_result: YFinanceData = {"error": "Fetch not attempted."} # Default
    status = 'pending'

    try:
        # Call the tool function from tools.py
        yfinance_result = await fetch_yfinance_data(ticker) # Assumes tool is async
        fetch_error = yfinance_result.get('error')

        if fetch_error:
            # Check if it's a critical failure (e.g., info failed, or many errors)
            if "Failed to fetch core info" in fetch_error or "critical error" in fetch_error.lower():
                 message = f"Yahoo Finance critical error: {fetch_error[:150]}..."
                 status = 'error'
                 yfinance_fetch_failed = True # Set failure flag
                 logger.error(message)
            else:
                 # Treat other errors as warnings, data might be partially useful
                 message = f"Yahoo Finance fetch completed with non-critical error: {fetch_error[:100]}..."
                 status = 'warning'
                 # yfinance_fetch_failed = False # Assume partial success is okay unless explicitly critical
                 logger.warning(message)
        else:
             message = "Yahoo Finance data fetched successfully."
             status = 'completed'
             logger.info(message)

    except Exception as e:
        message = f"Critical system error in fetch_financial_data node: {e}"
        logger.error(message, exc_info=True)
        yfinance_result = {"error": message}
        status = 'error'
        yfinance_fetch_failed = True # Set failure flag on system error

    # Update UI for node completion/status
    payload = {'keys': list(yfinance_result.keys()), 'error': yfinance_result.get('error')} if isinstance(yfinance_result, dict) else None
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': 'data_fetch', 'status': status,
        'title': 'Fetch Yahoo Finance Data', 'message': message,
        'payload': payload, 'overwrite': True
    }))

    # Update progress
    completed_steps = state.get('completed_steps_count', 0) + 1
    all_updates.extend(create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': 'running',
        'title': 'Research Progress', 'completedSteps': completed_steps,
        'message': f'Completed financial data fetch step ({status}).',
        'overwrite': True
    }))

    logger.info(f"--- Exiting Node: fetch_financial_data ({status}, YF_Failed={yfinance_fetch_failed}) ---")
    return {
        "yfinance_data": yfinance_result,
        "yfinance_fetch_failed": yfinance_fetch_failed, # Pass the flag status
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates
    }


async def execute_search(state: ResearchState) -> Dict[str, Any]:
    """Executes planned web searches: financial fallback first (if YF failed), then general."""
    yfinance_failed = state.get('yfinance_fetch_failed', False)
    completed_web_search_total = state.get('completed_web_search_count', 0) # Use the total count

    financial_searches_planned = state.get('financial_web_search_steps', [])
    general_searches_planned = state.get('search_steps_planned', [])

    num_financial_to_do = len(financial_searches_planned) if yfinance_failed else 0
    num_general_to_do = len(general_searches_planned)

    search_to_execute = None
    list_being_processed = None # 'financial' or 'general'
    current_local_index = -1 # Index within the specific list
    result_key = None # State key to append results to
    step_prefix = None
    step_type = 'search'
    step_title_prefix = None

    # Determine which search step is next based on the total completed count
    if yfinance_failed and completed_web_search_total < num_financial_to_do:
        list_being_processed = 'financial'
        current_local_index = completed_web_search_total
        search_to_execute = financial_searches_planned[current_local_index]
        result_key = 'financial_web_search_results'
        step_prefix = 'financial-web-search-'
        step_title_prefix = "Financial Web Search #"
    elif completed_web_search_total < (num_financial_to_do + num_general_to_do):
        list_being_processed = 'general'
        # Adjust index based on whether financial searches were done
        current_local_index = completed_web_search_total - num_financial_to_do
        search_to_execute = general_searches_planned[current_local_index]
        result_key = 'search_results'
        step_prefix = 'web-search-'
        step_title_prefix = "Web Search #"
    else:
        # Should not be called if condition in graph is correct, but handle defensively
        logger.warning("execute_search called but all web searches seem complete. Check graph logic.")
        return {"completed_web_search_count": completed_web_search_total} # No changes


    step_id = f'{step_prefix}{current_local_index}'
    all_updates = create_update(state, {
        'id': step_id, 'type': step_type, 'status': 'running',
        'title': f'{step_title_prefix}{current_local_index + 1}', # Use local index for title numbering
        'message': f"Executing: {search_to_execute.query[:60]}...", 'overwrite': True
    })
    logger.info(f"\n--- Running Node: execute_search ({step_title_prefix}{current_local_index + 1}) ---")
    logger.info(f"Overall Web Step: {completed_web_search_total + 1} / {num_financial_to_do + num_general_to_do}")
    logger.info(f"Query: {search_to_execute.query}")

    search_step_result = SearchStepResult(query=search_to_execute.query, results=[], tool_used="web_search")
    status = 'error'

    try:
        web_results = await perform_web_search(search_to_execute.query, max_results=5)
        search_step_result.results = web_results
        message = f"{step_title_prefix}{current_local_index + 1} finished, found {len(web_results)} results."
        status = 'completed'
        logger.info(message)
    except Exception as e:
        message = f"{step_title_prefix}{current_local_index + 1} failed: {e}"
        status = 'error'
        logger.error(f"Error during web search for query '{search_to_execute.query}': {e}", exc_info=True)
        search_step_result.results = []

    # --- Update UI for node completion ---
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': step_type, 'status': status,
        'title': f'{step_title_prefix}{current_local_index + 1}',
        'message': message, 'overwrite': True
    }))

    # --- Update PROGRESS (Overall step count AND web search count) ---
    completed_steps = state.get('completed_steps_count', 0) + 1
    new_completed_web_search_count = completed_web_search_total + 1 # Increment total web search count

    all_updates.extend(create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': 'running',
        'title': 'Research Progress', 'completedSteps': completed_steps,
        'message': f'Completed Web Search Step {new_completed_web_search_count} ({status}).', # Use total count in message
        'overwrite': True
    }))

    # --- Append result to the correct list in the state ---
    current_results_list = state.get(result_key, [])
    new_results = current_results_list + [search_step_result]

    logger.info(f"--- Exiting Node: execute_search ({step_title_prefix}{current_local_index + 1}) ---")

    return {
        result_key: new_results,
        "completed_web_search_count": new_completed_web_search_count, # Return updated total count
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates,
    }


async def perform_analysis(state: ResearchState) -> Dict[str, Any]:
    """Performs analysis, adapting prompt context based on YFinance status."""
    current_index = state.get('current_analysis_step_index', 0)
    analysis_steps_planned = state.get('analysis_steps_planned', [])

    if current_index >= len(analysis_steps_planned):
        logger.info("No more analysis steps planned.")
        return {"current_analysis_step_index": current_index}

    analysis_step = analysis_steps_planned[current_index]
    company_name = state['company_name']
    ticker = state['ticker']
    topic = state['topic']
    step_id = f'analysis-{current_index}'
    yfinance_failed = state.get('yfinance_fetch_failed', False)

    all_updates = create_update(state, {
        'id': step_id, 'type': 'analysis', 'status': 'running',
        'title': f'Analysis #{current_index + 1}',
        'message': f"Performing: {analysis_step.analysis_goal[:60]}...", 'overwrite': True
    })
    logger.info(f"\n--- Running Node: perform_analysis (Step {current_index + 1}/{len(analysis_steps_planned)}) ---")
    logger.info(f"Goal: {analysis_step.analysis_goal}")
    logger.info(f"YFinance Status: {'Failed - Using Web Fallback' if yfinance_failed else 'OK - Using YF Data'}")

    # --- Gather Context ---
    # Financial Context (Conditional)
    financial_context = "[Financial Context]\n"
    financial_data_source_description = "N/A" # Default
    if yfinance_failed:
        financial_web_results = state.get('financial_web_search_results', [])
        if financial_web_results:
             financial_context += "Source: Financial Web Search Results (Yahoo Finance Failed)\n"
             financial_data_source_description = "financial web search results"
             for i, res in enumerate(financial_web_results):
                 financial_context += f"Query {i+1}: {res.query}\n"
                 for item in res.results[:3]: # Limit snippets
                     financial_context += f"- {item.title}: {item.snippet[:150]}...\n"
             # Include initial JSON financial data if available
             initial_market_cap = state.get('market_cap_usd')
             initial_ebitda = state.get('input_ebitda_usd')
             initial_pe = state.get('input_pe_ratio')
             if initial_market_cap or initial_ebitda or initial_pe:
                  financial_context += "\nInitial Input Data Hints:\n"
                  if initial_market_cap: financial_context += f"- Market Cap (USD): {initial_market_cap}\n"
                  if initial_ebitda: financial_context += f"- EBITDA (USD, FY0): {initial_ebitda}\n"
                  if initial_pe: financial_context += f"- P/E Ratio: {initial_pe}\n"
        else:
             financial_context += "Source: Yahoo Finance Failed and NO financial web search results available.\n"
             financial_data_source_description = "web search (YF failed, limited results)"
    else:
        yfinance_data = state.get('yfinance_data')
        if yfinance_data and not yfinance_data.get('error'):
             financial_context += "Source: Yahoo Finance Data (Serialized Dictionaries)\n"
             financial_data_source_description = "Yahoo Finance data"
             # Summarize available YF data keys/presence
             financial_context += f"Available YF Keys: {list(yfinance_data.keys())}\n"
             # Optionally include snippets of info or structure hints if needed by prompt
             if yfinance_data.get('info'):
                  info_preview = {k: v for k, v in yfinance_data['info'].items() if k in ['sector', 'industry', 'marketCap', 'currency']}
                  financial_context += f"Info Preview: {json.dumps(info_preview)}\n"
             # Add note about serialized format
             financial_context += "(Financial statements are dicts with 'index', 'columns', 'data')\n"
        elif yfinance_data and yfinance_data.get('error'):
             financial_context += f"Source: Yahoo Finance Data (Fetch completed with error: {yfinance_data.get('error')})\n"
             financial_data_source_description = "Yahoo Finance data (with errors)"
        else:
            financial_context += "Source: Yahoo Finance Data (Not Available or Fetch Error)\n"
            financial_data_source_description = "Yahoo Finance data (unavailable)"


    # General Web Search Context
    web_search_context = "[General Web Search Results Context]\n"
    general_web_results = state.get('search_results', [])
    gap_web_results = state.get('gap_search_results', [])
    all_web_for_context = general_web_results + gap_web_results
    if all_web_for_context:
        for i, res in enumerate(all_web_for_context):
            web_search_context += f"Query {i+1}: {res.query}\n"
            for item in res.results[:3]: # Limit snippets
                web_search_context += f"- {item.title}: {item.snippet[:150]}...\n"
    else:
        web_search_context += "N/A\n"

    # Previous Analysis Context
    previous_analysis_context = "[Previous Analysis Steps Summary]\n"
    analyses = state.get('analysis_results', [])
    if isinstance(analyses, list) and analyses:
        formatted_analyses = []
        for idx, ar in enumerate(analyses):
             # Simplified access assuming AnalysisResult objects are stored
             goal_summary = ar.analysis_goal[:60] if isinstance(ar, AnalysisResult) else f'Goal N/A step {idx}'
             result_summary = ar.analysis_result[:200] if isinstance(ar, AnalysisResult) else f'Result N/A step {idx}'
             formatted_analyses.append(f"- Step {idx+1} ({goal_summary}...): {result_summary}...")
        previous_analysis_context += "\n".join(formatted_analyses)
    else:
         previous_analysis_context += "N/A\n"

    # Company Info Context (YF Info + Input Desc)
    info_context = "[Company Info Context]\n"
    input_desc = state.get('input_business_description', 'N/A')
    yf_info_data = state.get('yfinance_data', {}).get('info') if not yfinance_failed else None
    info_context += f"Input Description: {input_desc}\n"
    if yf_info_data:
         info_context += f"YF Info Summary: Sector: {yf_info_data.get('sector', 'N/A')}, Industry: {yf_info_data.get('industry', 'N/A')}, Employees: {yf_info_data.get('fullTimeEmployees', 'N/A')}\n"
         info_context += f"YF Long Description: {yf_info_data.get('longBusinessSummary', 'N/A')[:500]}...\n" # Limit length
    else:
         info_context += "YF Info: Not available or fetch failed.\n"

    # YF Holders Context (if not failed)
    yfinance_info_context = "[Yahoo Finance Info/Holders Context]\n" + info_context # Reuse info part
    if not yfinance_failed and state.get('yfinance_data'):
         holders_summary = ""
         major = state['yfinance_data'].get('major_holders')
         inst = state['yfinance_data'].get('institutional_holders')
         if major is not None: holders_summary += f"Major Holders data present (structure: {major.get('columns') if isinstance(major,dict) else 'N/A'}).\n"
         if inst is not None: holders_summary += f"Institutional Holders data present (structure: {inst.get('columns') if isinstance(inst,dict) else 'N/A'}).\n"
         yfinance_info_context += holders_summary if holders_summary else "Holders data: Not found in YF results.\n"
    else:
         yfinance_info_context += "Holders data: Not applicable (YF fetch failed or data unavailable).\n"


    # --- Determine Prompt & State Key ---
    analysis_prompt_template = None
    state_key_to_update = None # Key in ResearchState to store result

    analysis_goal_lower = analysis_step.analysis_goal.lower()
    is_financial_analysis_goal = "financial" in analysis_goal_lower or "财务" in analysis_goal_lower
    is_competitive_analysis_goal = "competitive" in analysis_goal_lower or "竞争" in analysis_goal_lower or "market" in analysis_goal_lower or "moat" in analysis_goal_lower
    is_mgmt_gov_analysis_goal = "management" in analysis_goal_lower or "governance" in analysis_goal_lower or "管理" in analysis_goal_lower

    if is_financial_analysis_goal:
        logger.info("Using FINANCIAL_ANALYSIS_PROMPT_YFINANCE...")
        analysis_prompt_template = FINANCIAL_ANALYSIS_PROMPT_YFINANCE
        state_key_to_update = "financial_analysis"
    elif is_competitive_analysis_goal:
         logger.info("Using COMPETITIVE_ANALYSIS_PROMPT_YFINANCE...")
         analysis_prompt_template = COMPETITIVE_ANALYSIS_PROMPT_YFINANCE
         state_key_to_update = "competitive_analysis"
    elif is_mgmt_gov_analysis_goal:
         logger.info("Using MANAGEMENT_GOVERNANCE_PROMPT_YFINANCE...")
         analysis_prompt_template = MANAGEMENT_GOVERNANCE_PROMPT_YFINANCE
         state_key_to_update = "management_governance_assessment"
    else:
        logger.warning(f"No specific prompt matched goal: '{analysis_step.analysis_goal}'. Using generic approach.")
        # Fallback generic analysis (less structured)
        analysis_prompt_template = """Analyze the provided context for the goal: '{analysis_goal}'.
        Combine information from financial context ({financial_data_source_description}), web searches, company info, and previous analyses.
        Focus on insights relevant to M&A if possible.

        Goal: {analysis_goal}

        Financial Context ({financial_data_source_description}):
        {financial_context}

        General Web Search Context:
        {web_context}

        Company Info Context:
        {info_context}

        Previous Analysis Context:
        {previous_analysis_context}

        Analysis:
        """
        state_key_to_update = None # Store in general list


    analysis_content = f"Analysis failed for goal: {analysis_step.analysis_goal}" # Default content
    status = 'error'

    # Ensure template exists before formatting
    if analysis_prompt_template:
         try:
             # Format the selected prompt with all gathered context
             prompt = analysis_prompt_template.format(
                 company_name=company_name,
                 ticker=ticker,
                 financial_data_source_description=financial_data_source_description, # Pass the description
                 financial_context=financial_context[:8000], # Limit context
                 web_context=web_search_context[:8000], # Limit context
                 info_context=info_context[:3000],
                 previous_analysis_context=previous_analysis_context[:3000],
                 yfinance_info_context=yfinance_info_context[:6000], # For mgmt/gov prompt
                 analysis_goal=analysis_step.analysis_goal, # For generic prompt
                 market_cap=state.get('market_cap_usd', 'N/A'), # Pass market cap for financial prompt context
                 ebitda=state.get('input_ebitda_usd', 'N/A') # Pass EBITDA for financial prompt context
             )

             # --- Invoke LLM ---
             analysis_response = await llm.ainvoke(prompt) # Use standard LLM for analysis
             analysis_content = analysis_response.content if hasattr(analysis_response, 'content') else str(analysis_response)
             message = f"Analysis #{current_index + 1} finished."
             status = 'completed'
             logger.info(message)

         except KeyError as ke:
              message = f"Analysis #{current_index + 1} failed: Missing key in prompt format - {ke}"
              status = 'error'
              logger.error(message, exc_info=True)
              analysis_content = f"Analysis prompt formatting failed: {ke}"
         except Exception as e:
             message = f"Analysis #{current_index + 1} failed: {e}"
             status = 'error'
             logger.error(f"Error during analysis for goal '{analysis_step.analysis_goal}': {e}", exc_info=True)
             analysis_content = f"Analysis failed: {e}"
    else:
         # This case should ideally not happen if generic fallback exists
         message = f"Analysis #{current_index + 1} skipped: No suitable prompt template found."
         status = 'skipped'
         logger.error(message)
         analysis_content = "Analysis skipped."


    # --- Prepare State Update ---
    state_update = {}
    if state_key_to_update:
        state_update = {state_key_to_update: analysis_content}
    else:
        # Store generic analysis in the list
        analysis_result_obj = AnalysisResult(analysis_goal=analysis_step.analysis_goal, analysis_result=analysis_content)
        new_analysis_results = state.get('analysis_results', []) + [analysis_result_obj]
        state_update = {"analysis_results": new_analysis_results}


    # Update UI for node completion
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': 'analysis', 'status': status,
        'title': f'Analysis #{current_index + 1}', 'message': message,
        'overwrite': True
    }))

    # Update progress
    completed_steps = state.get('completed_steps_count', 0) + 1
    all_updates.extend(create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': 'running',
        'title': 'Research Progress', 'completedSteps': completed_steps,
        'message': f'Completed analysis step {current_index + 1} ({status}).',
        'overwrite': True
    }))

    logger.info(f"--- Exiting Node: perform_analysis (Step {current_index + 1}) ---")
    # Merge state_update into the return dictionary
    return_state = {
        "current_analysis_step_index": current_index + 1,
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates,
    }
    return_state.update(state_update)
    return return_state


async def analyze_gaps(state: ResearchState) -> Dict[str, Any]:
    """Analyzes gaps, potentially suggesting actionable web searches."""
    step_id = 'gap-analysis'
    all_updates = create_update(state, {
        'id': step_id, 'type': 'analysis', 'status': 'running',
        'title': 'Gap Analysis', 'message': 'Analyzing for knowledge gaps & limitations...',
        'overwrite': True
        })
    logger.info(f"\n--- Running Node: analyze_gaps ---")
    yfinance_failed = state.get('yfinance_fetch_failed', False)
    yfinance_status_text = "Failed (Used Web Fallback)" if yfinance_failed else "Successful"

    # --- Gather Context ---
    # Consolidate context from various analysis steps and data sources
    context_parts = []
    context_parts.append(f"Research Target: {state['company_name']} ({state['ticker']})")
    context_parts.append(f"Yahoo Finance Status: {yfinance_status_text}")
    if state.get('financial_analysis'): context_parts.append(f"\n[Financial Analysis Summary]\n{state['financial_analysis'][:1000]}...")
    if state.get('competitive_analysis'): context_parts.append(f"\n[Competitive Analysis Summary]\n{state['competitive_analysis'][:1000]}...")
    if state.get('management_governance_assessment'): context_parts.append(f"\n[Mgmt/Gov Assessment Summary]\n{state['management_governance_assessment'][:1000]}...")
    # Include snippets from web searches maybe?
    # search_summary = "\n[Web Search Snippet Highlights]\n"
    # ... logic to add highlights ...
    # context_parts.append(search_summary)

    context = "\n".join(context_parts)

    # --- Format Prompt ---
    prompt = GAP_ANALYSIS_PROMPT_YFINANCE.format(
        topic=state['topic'], # Keep original topic for reference if needed
        company_name=state['company_name'],
        ticker=state['ticker'],
        yfinance_status=yfinance_status_text, # Pass status to prompt
        context=context[:10000] # Limit context
    )

    gap_analysis_result: Optional[GapAnalysisResult] = None # Initialize
    status = 'error' # Default
    message = "Gap analysis failed before LLM call."

    try:
        gap_analysis_result = await generate_structured_output(
            llm_creative, GapAnalysisResult, prompt
        )
        if not gap_analysis_result:
             gap_analysis_result = GapAnalysisResult(summary="Failed to generate structured gap analysis.", follow_up_queries=[])
             message = "Gap analysis LLM call succeeded but failed to parse structure."
             status = 'warning'
        else:
             # Filter follow-up queries - Keep this filtering
             original_query_count = len(gap_analysis_result.follow_up_queries)
             gap_analysis_result.follow_up_queries = [
                 q for q in gap_analysis_result.follow_up_queries if isinstance(q, GapFollowUpQuery) and q.tool_hint == 'web_search'
             ]
             filtered_query_count = len(gap_analysis_result.follow_up_queries)
             message = f"Gap analysis completed. Identified limitations. {filtered_query_count} actionable follow-up web searches suggested (out of {original_query_count} raw suggestions)."
             status = 'completed'
        logger.info(message)
    except Exception as e:
        logger.error(f"Error during gap analysis LLM call or parsing: {e}", exc_info=True)
        gap_analysis_result = GapAnalysisResult(summary=f"Gap analysis failed: {e}", follow_up_queries=[])
        message = f"Gap analysis failed: {e}"
        status = 'error'

    # Update UI for node completion
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': 'analysis', 'status': status,
        'title': 'Gap Analysis', 'message': message,
        'payload': gap_analysis_result.dict() if hasattr(gap_analysis_result, 'dict') else {"summary": "Error or N/A"},
        'overwrite': True
    }))
    # Update progress
    completed_steps = state.get('completed_steps_count', 0) + 1
    all_updates.extend(create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': 'running',
        'title': 'Research Progress', 'completedSteps': completed_steps,
        'message': f'Completed gap analysis step ({status}).', 'overwrite': True
    }))

    logger.info(f"--- Exiting Node: analyze_gaps ---")
    return {
        "gaps_identified": gap_analysis_result,
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates
    }


async def execute_gap_search(state: ResearchState) -> Dict[str, Any]:
    """Executes follow-up *web* searches based on identified gaps."""
    step_id = 'gap-search'
    all_updates = create_update(state, {
        'id': step_id, 'type':'search', 'status': 'running',
        'title': 'Gap Filling Web Search', 'message': 'Executing follow-up web searches...',
        'overwrite': True
        })
    logger.info(f"\n--- Running Node: execute_gap_search ---")

    gaps = state.get('gaps_identified')
    follow_up_web_queries = gaps.follow_up_queries if gaps and hasattr(gaps, 'follow_up_queries') and isinstance(gaps.follow_up_queries, list) else []
    status = 'skipped' # Default if no queries
    message = "No actionable follow-up web searches suggested by gap analysis."

    gap_search_step_results: List[SearchStepResult] = []

    if follow_up_web_queries:
        max_gap_queries = 3 # Keep limit or adjust if needed
        queries_to_run = follow_up_web_queries[:max_gap_queries]
        status = 'running' # Will be updated later
        logger.info(f"Executing {len(queries_to_run)} gap web queries (max {max_gap_queries})...")
        try:
            for i, gap_query_obj in enumerate(queries_to_run):
                if not isinstance(gap_query_obj, GapFollowUpQuery): continue
                query_text = gap_query_obj.query
                logger.info(f"Executing Gap Web Query {i+1}/{len(queries_to_run)}: {query_text}")
                try:
                    web_results = await perform_web_search(query_text, 3) # Use slightly fewer results for gap fill?
                    gap_search_step_results.append(SearchStepResult(query=query_text, results=web_results, tool_used="web_search_gap"))
                except Exception as e_inner:
                    logger.error(f"Error during specific gap web search for query '{query_text}': {e_inner}")
                    gap_search_step_results.append(SearchStepResult(query=query_text, results=[], tool_used="web_search_gap")) # Add empty result on error

            message = f"Gap web search finished. Executed {len(queries_to_run)} queries, found {sum(len(r.results) for r in gap_search_step_results)} total results."
            status = 'completed'
            logger.info(message)
        except Exception as e_outer:
            message = f"Error during gap search execution loop: {e_outer}"
            status = 'error'
            logger.error(message, exc_info=True)
    else:
        logger.info(message) # Log skip message

    # Update UI for node completion
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': 'search', 'status': status,
        'title': 'Gap Filling Web Search', 'message': message,
        'overwrite': True
    }))

    # Update progress - Count as one step overall
    completed_steps = state.get('completed_steps_count', 0) + 1
    all_updates.extend(create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': 'running',
        'title': 'Research Progress', 'completedSteps': completed_steps,
        'message': f'Completed gap search step ({status}).', 'overwrite': True
    }))

    logger.info(f"--- Exiting Node: execute_gap_search ---")
    # Append gap search results to the main search results list OR keep separate?
    # Let's keep them separate for now in state, but combine for context later.
    return {
        "gap_search_results": gap_search_step_results, # Store gap results separately
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates
    }


async def synthesize_final_report(state: ResearchState) -> Dict[str, Any]:
    """Synthesizes findings, adapting context based on YF status."""
    step_id = 'synthesis'
    all_updates = create_update(state, {
        'id': step_id, 'type':'synthesis', 'status': 'running',
        'title': 'Synthesize Findings', 'message': 'Synthesizing all findings...',
        'overwrite': True
        })
    logger.info(f"\n--- Running Node: synthesize_final_report ---")
    yfinance_failed = state.get('yfinance_fetch_failed', False)
    yfinance_status_text = "Failed (Used Web Fallback)" if yfinance_failed else "Successful"

    # --- Gather Context (More robust handling of potential None values) ---
    context_parts = []
    context_parts.append(f"Research Target: {state.get('company_name', 'N/A')} ({state.get('ticker', 'N/A')})")
    context_parts.append(f"Yahoo Finance Status: {yfinance_status_text}")

    # Add initial input data summary with checks for None
    input_summary = "\n[Initial Input Data Summary]\n"
    country = state.get('country_of_exchange')
    input_summary += f"- Country: {country if country else 'N/A'}\n"
    market_cap = state.get('market_cap_usd')
    input_summary += f"- Market Cap (USD, {state.get('input_query_date', 'N/A')}): {market_cap if market_cap is not None else 'N/A'}\n"
    ebitda = state.get('input_ebitda_usd')
    input_summary += f"- EBITDA (USD, FY0, {state.get('input_query_date', 'N/A')}): {ebitda if ebitda is not None else 'N/A'}\n"
    input_pe = state.get('input_pe_ratio')
    input_summary += f"- P/E Ratio ({state.get('input_query_date', 'N/A')}): {input_pe if input_pe is not None else 'N/A'}\n"
    # *** FIX: Check if description is None before slicing ***
    business_desc_val = state.get('input_business_description')
    input_summary += f"- Business Desc: {(business_desc_val[:300] + '...') if business_desc_val else 'N/A'}\n"
    context_parts.append(input_summary)

    # Add analysis summaries (Safely access potentially None values)
    financial_analysis_val = state.get('financial_analysis')
    if financial_analysis_val: context_parts.append(f"\n[Financial Analysis Summary (Source: {'Web Fallback' if yfinance_failed else 'YF Data'})]\n{financial_analysis_val[:1500]}...")

    competitive_analysis_val = state.get('competitive_analysis')
    if competitive_analysis_val: context_parts.append(f"\n[Competitive Analysis Summary]\n{competitive_analysis_val[:1500]}...")

    mgmt_gov_val = state.get('management_governance_assessment')
    if mgmt_gov_val: context_parts.append(f"\n[Mgmt/Gov Assessment Summary]\n{mgmt_gov_val[:1500]}...")

    analysis_results_list = state.get('analysis_results')
    if analysis_results_list: # Check if the list itself exists
        generic_analysis_summary = "\n[Other Analysis Results]\n"
        for ar in analysis_results_list:
            if isinstance(ar, AnalysisResult): # Check type for safety
                 generic_analysis_summary += f"- {ar.analysis_goal[:50]}...: {ar.analysis_result[:150]}...\n"
        context_parts.append(generic_analysis_summary)

    # Add Gap Analysis Summary (Safely access)
    gaps = state.get('gaps_identified')
    if gaps and isinstance(gaps, GapAnalysisResult): context_parts.append(f"\n[Gap Analysis Summary]\n{gaps.summary[:1000]}...")

    # Add Web Search Highlights (Combine all searches safely)
    web_highlights = "\n[Web Search Highlights (All Searches)]\n"
    search_results = state.get('search_results', []) or []
    financial_web_results = state.get('financial_web_search_results', []) or []
    gap_search_results = state.get('gap_search_results', []) or []
    all_searches = search_results + financial_web_results + gap_search_results
    highlight_count = 0
    max_highlights = 15
    if all_searches: # Check if there are any search results at all
        for res in all_searches:
            if highlight_count >= max_highlights: break
            if isinstance(res, SearchStepResult): # Check type
                web_highlights += f"Query: {res.query}\n"
                if res.results: # Check if results list exists
                     for item in res.results[:2]:
                         if highlight_count >= max_highlights: break
                         if isinstance(item, SearchResultItem): # Check type
                             title = item.title or "N/A"
                             snippet = item.snippet or ""
                             web_highlights += f"- {title}: {snippet[:100]}...\n"
                             highlight_count += 1
    context_parts.append(web_highlights if highlight_count > 0 else "\n[Web Search Highlights: None available or processed]\n")

    context = "\n".join(context_parts)

    # --- Use Synthesis Prompt ---
    prompt = SYNTHESIS_PROMPT_YFINANCE.format(
        company_name=state.get('company_name', 'N/A'), # Use .get for safety
        ticker=state.get('ticker', 'N/A'),
        yfinance_status=yfinance_status_text,
        context=context[:20000] # Limit context
    )

    # ... (Rest of the synthesize_final_report function remains the same: LLM call, error handling, state update) ...
    # ... (LLM call and result handling as before) ...
    synthesis_result: Optional[FinalSynthesisResult] = None
    status = 'error'
    message = "Synthesis failed before LLM call."

    try:
         synthesis_result = await generate_structured_output(
             llm_creative, FinalSynthesisResult, prompt
         )
         if not synthesis_result or not synthesis_result.key_findings_summary: # Check summary content
             synthesis_result = FinalSynthesisResult(
                 key_findings_summary="Synthesis generation failed or returned empty summary.",
                 remaining_uncertainties=["Data limitations significantly impacted synthesis.", "Error during parsing or generation."]
             )
             message = "Synthesis completed but failed to generate valid/meaningful structure."
             status = 'warning'
         else:
             message = "Synthesis of all findings completed."
             status = 'completed'
         logger.info(message)
    except Exception as e:
        logger.error(f"Error during synthesis: {e}", exc_info=True)
        synthesis_result = FinalSynthesisResult(key_findings_summary=f"Synthesis failed: {e}", remaining_uncertainties=["Error during synthesis process."])
        message = f"Synthesis failed: {e}"
        status = 'error'

    # Update UI for node completion
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': 'synthesis', 'status': status,
        'title': 'Synthesize Findings', 'message': message,
        'payload': synthesis_result.dict() if hasattr(synthesis_result, 'dict') else {"key_findings_summary": "Error or N/A"},
        'overwrite': True
    }))
    # Update progress
    completed_steps = state.get('completed_steps_count', 0) + 1
    all_updates.extend(create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': 'running',
        'title': 'Research Progress', 'completedSteps': completed_steps,
        'message': f'Completed synthesis step ({status}).', 'overwrite': True
    }))

    logger.info(f"--- Exiting Node: synthesize_final_report ---")
    return {
        "final_synthesis": synthesis_result,
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates
    }


async def generate_final_markdown_report(state: ResearchState) -> Dict[str, Any]:
    """Generates the final Markdown report, including summary table and adjusted tone."""
    step_id = 'final-report-generation'
    all_updates = create_update(state, {
        'id': step_id, 'type':'report', 'status': 'running',
        'title':'Final Report Generation', 'message': 'Generating final report...',
        'overwrite': True
        })
    logger.info(f"\n--- Running Node: generate_final_markdown_report ---")

    # --- 1. Generate Structured Summary Table ---
    # ... (Summary table generation logic remains the same as previous version) ...
    summary_table_md = "# ERROR: Could not generate summary table." # Default
    try:
        # (Keep the table generation logic here)
        company_name = state.get('company_name', 'N/A')
        ticker = state.get('ticker', 'N/A')
        country = state.get('country_of_exchange', 'N/A')
        query_date = state.get('input_query_date', 'N/A')
        market_cap = state.get('market_cap_usd') # Get value, might be None
        market_cap_str = f"{market_cap:,.2f}" if isinstance(market_cap, (int, float)) else "N/A"
        ebitda = state.get('input_ebitda_usd') # Get value, might be None
        ebitda_str = f"{ebitda:,.2f}" if isinstance(ebitda, (int, float)) else "N/A"
        input_pe = state.get('input_pe_ratio') # Get value, might be None
        input_pe_str = f"{input_pe:.2f}" if isinstance(input_pe, (int, float)) else "N/A" # Format if number

        # Infer Industry (best effort)
        industry = "N/A"
        yf_info = state.get('yfinance_data', {}).get('info') if not state.get('yfinance_fetch_failed') else None
        if yf_info and yf_info.get('industry'):
            industry = yf_info['industry']
        elif state.get('input_business_description'):
             business_desc_val = state.get('input_business_description') # Check if None later
             if business_desc_val: # Check if not None before using
                 desc_lower = business_desc_val.lower()
                 # ... (industry inference logic) ...
                 if 'cloud service' in desc_lower: industry = "Cloud Services (from Desc)"
                 # ... (other heuristics) ...
                 else: industry = business_desc_val[:30] + "... (from Desc)"

        # Extract from Synthesis
        synthesis = state.get('final_synthesis')
        prelim_rationale = "See Exec Summary" # Default
        key_risks = "See Exec Summary / Risks Section" # Default
        if synthesis and isinstance(synthesis, FinalSynthesisResult) and synthesis.key_findings_summary:
             summary_text = synthesis.key_findings_summary.lower()
             rationale_hints = re.findall(r"(?:potential rationale|attractive aspect|strength).{0,100}", summary_text)
             if rationale_hints: prelim_rationale = rationale_hints[0][20:].strip() # Basic extraction

             risk_hints = re.findall(r"(?:red flag|major risk|key risk|concern).{0,100}", summary_text)
             if risk_hints: key_risks = risk_hints[0][10:].strip() # Basic extraction

        # Format Table (Ensure N/A for None values passed)
        summary_table_md = f"""
| Key Information Item          | Details (Preliminary - Based on YF/Web)                     |
| :---------------------------- | :---------------------------------------------------------- |
| **Company Name** | {company_name}                                              |
| **Ticker / RIC** | {ticker}                                                    |
| **Country of Exchange** | {country if country else 'N/A'}                           |
| **Market Cap (USD)** | {market_cap_str} *(as of {query_date if query_date else 'N/A'})* |
| **Input EBITDA (USD, FY0)** | {ebitda_str} *(as of {query_date if query_date else 'N/A'})* |
| **Input P/E Ratio** | {input_pe_str} *(as of {query_date if query_date else 'N/A'})* |
| **Industry (Inferred)** | {industry}                                                  |
| **Preliminary M&A Rationale** | {prelim_rationale} *(Speculative)* |
| **Key Preliminary Risks** | {key_risks} *(Speculative)* |
| **Data Confidence Level** | **Low (YF/Web Only)** |
| **Next Step Recommendation** | **Deep Due Diligence using Official Filings REQUIRED** |
"""
        logger.info("Successfully generated structured summary table.")
    except Exception as table_e:
        logger.error(f"Error generating summary table: {table_e}", exc_info=True)
        summary_table_md = f"# Error Generating Summary Table: {table_e}\n"
        # Ensure it's still a string even on error
        if not isinstance(summary_table_md, str): summary_table_md = "# Summary Table Error\n"


    # --- 2. Prepare Context for Final Report LLM (More robust handling of None) ---
    synthesis = state.get('final_synthesis')
    gaps = state.get('gaps_identified')
    yfinance_failed = state.get('yfinance_fetch_failed', False)
    yfinance_status_text = "Failed (Used Web Fallback)" if yfinance_failed else "Successful"
    financial_data_source = "Web Search Fallback" if yfinance_failed else "Yahoo Finance"
    financial_section_source_note = f"Based on {financial_data_source}"

    final_report_text = f"{summary_table_md}\n\n# Report Generation Failed\nSynthesis data missing." # Default error
    status = 'error'
    message = "Report generation failed: Missing synthesis data."

    if synthesis and isinstance(synthesis, FinalSynthesisResult): # Check synthesis exists and is correct type
        context_parts = {
            "structured_summary_table_context": summary_table_md, # Pass generated table
            "synthesis_context": "",
            "gap_context": "",
            "analysis_summaries_context": "",
            "search_results_context": "",
            "initial_input_context": "" # Will be built below
        }

        # Synthesis Context
        context_parts["synthesis_context"] = f"Synthesized Key Findings:\n{synthesis.key_findings_summary}\n\nRemaining Uncertainties:\n" + "\n".join(f"- {u}" for u in (synthesis.remaining_uncertainties or [])) # Handle None

        # Gap Context
        context_parts["gap_context"] = f"Gap Analysis Summary:\n{gaps.summary if gaps and isinstance(gaps, GapAnalysisResult) else 'N/A'}" # Check gaps type

        # Analysis Summaries Context (Handle None values safely)
        analysis_summaries = []
        fin_analysis = state.get('financial_analysis')
        if fin_analysis: analysis_summaries.append(f"### Financial Analysis (Source: {financial_data_source})\n{fin_analysis}")
        comp_analysis = state.get('competitive_analysis')
        if comp_analysis: analysis_summaries.append(f"### Competitive Analysis\n{comp_analysis}")
        mgmt_gov = state.get('management_governance_assessment')
        if mgmt_gov: analysis_summaries.append(f"### Management/Governance Assessment\n{mgmt_gov}")
        other_analysis = state.get('analysis_results')
        if other_analysis: # Check list exists
             generic_summary = "### Other Analysis Results\n"
             for ar in other_analysis:
                 if isinstance(ar, AnalysisResult): # Check type
                     generic_summary += f"- **{ar.analysis_goal}**: {ar.analysis_result}\n"
             analysis_summaries.append(generic_summary)
        context_parts["analysis_summaries_context"] = "\n\n".join(analysis_summaries) if analysis_summaries else "N/A"

        # Search Results Context (Handle None values safely)
        search_context = "[Web Search Results Context for Reference]\n"
        search_results = state.get('search_results', []) or []
        financial_web_results = state.get('financial_web_search_results', []) or []
        gap_search_results = state.get('gap_search_results', []) or []
        all_searches = search_results + financial_web_results + gap_search_results
        search_count = 0
        max_search_items = 20
        if all_searches:
            for res in all_searches:
                if search_count >= max_search_items: break
                if isinstance(res, SearchStepResult): # Check type
                    search_context += f"Query: {res.query}\n"
                    if res.results:
                        for item in res.results[:2]:
                            if search_count >= max_search_items: break
                            if isinstance(item, SearchResultItem):
                                title = item.title or "N/A"
                                snippet = item.snippet or ""
                                url = item.url or "#" # Provide fallback URL
                                search_context += f"- [{title}]({url}): {snippet[:150]}...\n"
                                search_count +=1
        context_parts["search_results_context"] = search_context[:15000] if search_count > 0 else "[Web Search Results Context for Reference]\nN/A"


        # *** FIX: Build Initial Input Context Safely ***
        input_ctx = "[Initial Input Data]\n"
        company_name_val = state.get('company_name', 'N/A')
        ticker_val = state.get('ticker', 'N/A')
        country_val = state.get('country_of_exchange')
        market_cap_val = state.get('market_cap_usd')
        ebitda_val = state.get('input_ebitda_usd')
        pe_val = state.get('input_pe_ratio')
        desc_val = state.get('input_business_description') # Get the value, could be None
        query_date_val = state.get('input_query_date')

        input_ctx += f"- Name: {company_name_val}\n"
        input_ctx += f"- RIC/Ticker: {ticker_val}\n"
        input_ctx += f"- Country: {country_val if country_val else 'N/A'}\n"
        input_ctx += f"- Market Cap (USD, {query_date_val if query_date_val else 'N/A'}): {market_cap_val if market_cap_val is not None else 'N/A'}\n"
        input_ctx += f"- EBITDA (USD, FY0, {query_date_val if query_date_val else 'N/A'}): {ebitda_val if ebitda_val is not None else 'N/A'}\n"
        input_ctx += f"- P/E Ratio ({query_date_val if query_date_val else 'N/A'}): {pe_val if pe_val is not None else 'N/A'}\n"
        # Check desc_val before slicing
        input_ctx += f"- Business Desc: {(desc_val[:500] + '...') if desc_val else 'N/A'}\n"
        context_parts["initial_input_context"] = input_ctx
        # *** END FIX ***

        # --- 3. Format Final Report Prompt ---
        current_date_str = datetime.now().strftime('%Y-%m-%d')
        try:
            prompt = FINAL_REPORT_SYSTEM_PROMPT_TEMPLATE_YFINANCE_ONLY.format(
                current_date=current_date_str,
                research_topic=state.get('topic', 'N/A'), # Use .get
                yfinance_status=yfinance_status_text,
                financial_section_source_note=financial_section_source_note,
                financial_data_source=financial_data_source,
                **context_parts # Pass all context sections
            )
        except KeyError as ke:
            logger.error(f"KeyError formatting final report prompt: {ke}. Context keys: {list(context_parts.keys())}", exc_info=True)
            final_report_text = f"{summary_table_md}\n\n# Report Generation Failed\n\nError: Missing key in final report prompt template: {ke}"
            message = f"Error formatting report prompt: Missing key {ke}"
            status = 'error'
            prompt = None # Prevent LLM call

        # --- 4. Invoke LLM for Report Generation (only if prompt formatting succeeded) ---
        if prompt:
            try:
                final_report = await llm_creative.ainvoke(prompt) # Use creative for report writing
                final_report_text = final_report.content if hasattr(final_report, 'content') else str(final_report)

                if len(final_report_text) < 500 or "report generation failed" in final_report_text.lower():
                     logger.warning("Final report seems short or indicates internal failure.")
                     message = "Final report generated, but may be incomplete or failed."
                     status = 'warning'
                     # Keep the potentially faulty report text
                else:
                     message = "Final research report generated successfully."
                     status = 'completed'
                logger.info(message)

            except Exception as e:
                logger.error(f"Error generating final report via LLM: {e}", exc_info=True)
                final_report_text = f"{summary_table_md}\n\n# Report Generation Failed\n\nError during LLM call: {str(e)}"
                message = f"Error generating report via LLM: {str(e)[:100]}..."
                status = 'error'

    else: # Synthesis was missing
         logger.error("Cannot generate report: Final synthesis is missing.")
         final_report_text = f"{summary_table_md}\n\n" + final_report_text # Include table even if synthesis failed
         message = "Report generation failed: Missing synthesis data."
         status = 'error'


    # --- 5. Update UI and Progress ---
    all_updates.extend(create_update(state, {
        'id': step_id, 'type': 'report', 'status': status,
        'title': 'Final Report Generation', 'message': message,
        'payload': {'report_preview': final_report_text[:500]+"..."} if status != 'error' else None,
        'overwrite': True
        }))

    completed_steps = state.get('completed_steps_count', 0) + 1
    final_total_steps = state.get('total_steps', completed_steps)
    progress_final = create_update(state, {
        'id': 'research-progress', 'type': 'progress',
        'status': status if status == 'error' else 'completed',
        'title': 'Research Progress', 'message': f'Research finished ({status}).',
        'completedSteps': completed_steps if status == 'completed' else completed_steps -1, # Adjust completed on error?
        'totalSteps': final_total_steps, 'isComplete': True, 'overwrite': True
    })
    all_updates.extend(progress_final)

    logger.info(f"--- Exiting Node: generate_final_markdown_report ({status}) ---")
    return {
        "final_report_markdown": final_report_text,
        "structured_summary_table": summary_table_md,
        "completed_steps_count": completed_steps,
        "stream_updates": state.get('stream_updates', []) + all_updates,
    }

async def finalize_basic_research(state: ResearchState) -> Dict[str, Any]:
    """Fallback finalizer, attempts to include summary table."""
    step_id = 'finalize-research'
    all_updates = state.get('stream_updates', [])
    final_message = state.get("error_message", "Research process finalized via fallback path.")
    all_updates.extend(create_update(state, {
        'id': step_id, 'type':'end', 'status': 'completed',
        'title':'Research Finalized', 'message': final_message, 'overwrite': True
        }))
    logger.info(f"\n--- Running Node: finalize_basic_research ({final_message}) ---")

    # Determine final overall progress status
    is_error_final = bool(state.get("error_message"))
    final_status = 'error' if is_error_final else 'completed'
    final_completed_steps = state.get('completed_steps_count', 0)
    final_total_steps = state.get('total_steps', final_completed_steps)

    progress_final = create_update(state, {
        'id': 'research-progress', 'type': 'progress', 'status': final_status,
        'title': 'Research Progress', 'message': f'Research finished ({final_status} via fallback).',
        'completedSteps': final_completed_steps, 'totalSteps': final_total_steps,
        'isComplete': True, 'overwrite': True
    })
    all_updates.extend(progress_final)

    # Try to provide a minimal useful report, including summary table if available
    final_report = state.get("final_report_markdown")
    summary_table = state.get("structured_summary_table", "\n# Summary Table Generation Failed in Fallback\n")

    if not final_report or "Report Generation Failed" in final_report or "final state." in final_report: # Check for various failure states
        fallback_report_content = f"\n\n# Research Finalized ({final_status.upper()})\n\n{final_message}\n\n"
        final_synthesis = state.get('final_synthesis')
        if final_synthesis and hasattr(final_synthesis, 'key_findings_summary'):
            fallback_report_content += f"## Last Available Synthesis Summary\n{final_synthesis.key_findings_summary}\n\n## Remaining Uncertainties\n" + "\n".join(f"- {u}" for u in final_synthesis.remaining_uncertainties)
        else:
            fallback_report_content += "No usable synthesis or report was generated prior to fallback."
        # Prepend summary table to the fallback content
        final_report = summary_table + fallback_report_content

    return {"final_report_markdown": final_report, "stream_updates": all_updates}