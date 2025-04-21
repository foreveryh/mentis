# /Users/peng/Dev/AI_AGENTS/mentis/super_agents/company_deep_research/reason_graph/state.py
# (Optimized Version v2 - Adjusted for Graph Logic)

from typing import TypedDict, List, Optional, Dict, Any, Literal
import pandas as pd
import time

from .schemas import (
    SearchQuery, RequiredAnalysis, AnalysisResult, GapAnalysisResult,
    FinalSynthesisResult, SearchStepResult, StreamUpdate, StepInfo, ResearchPlan, KeyFinding
)

class YFinanceData(TypedDict, total=False):
    info: Optional[Dict[str, Any]]
    financials: Optional[Dict]
    quarterly_financials: Optional[Dict]
    balance_sheet: Optional[Dict]
    quarterly_balance_sheet: Optional[Dict]
    cashflow: Optional[Dict]
    quarterly_cashflow: Optional[Dict]
    major_holders: Optional[Dict]
    institutional_holders: Optional[Dict]
    recommendations: Optional[Dict]
    news: Optional[List[Dict[str, Any]]]
    error: Optional[str]

class ResearchState(TypedDict):
    # --- Input Fields ---
    identifier_ric: str
    company_name: str
    country_of_exchange: Optional[str]
    market_cap_usd: Optional[float]
    input_business_description: Optional[str]
    input_pe_ratio: Optional[float]
    input_ebitda_usd: Optional[float]
    input_query_date: Optional[str]

    # --- Derived/Internal Fields ---
    topic: str
    ticker: str
    max_search_iterations: int # Might not be used with current loop logic
    max_analysis_steps: int # Max steps for the analysis loop
    analysis_depth: Literal["basic", "detailed"]

    # --- Planning ---
    research_plan: Optional[ResearchPlan]
    search_steps_planned: List[SearchQuery] # General web searches
    financial_web_search_steps: List[SearchQuery] # Financial web searches (if YF failed)
    analysis_steps_planned: List[RequiredAnalysis]

    # --- Data Collection ---
    yfinance_data: Optional[YFinanceData]
    yfinance_fetch_failed: bool

    search_results: List[SearchStepResult] # Stores general web search results
    financial_web_search_results: List[SearchStepResult] # Stores financial web search results

    # --- Analysis & Synthesis ---
    analysis_results: List[AnalysisResult] # Generic analysis results
    financial_analysis: Optional[str]
    competitive_analysis: Optional[str]
    management_governance_assessment: Optional[str]

    # --- Gap Analysis & Follow-up ---
    gaps_identified: Optional[GapAnalysisResult]
    gap_search_results: List[SearchStepResult]

    # --- Final Output ---
    final_synthesis: Optional[FinalSynthesisResult]
    final_report_markdown: Optional[str]
    structured_summary_table: Optional[str]

    # --- Workflow State Tracking ---
    # REMOVED: current_search_step_index (replaced by completed_web_search_count logic)
    # REMOVED: current_financial_web_search_index (handled internally or via count)
    completed_web_search_count: int # **NEW**: Tracks total web searches completed (both types)
    current_analysis_step_index: int
    completed_steps_count: float # Overall progress counter
    total_steps: Optional[int]

    # --- UI / Streaming ---
    stream_updates: List[StreamUpdate]

    # --- Error Tracking ---
    error_message: Optional[str]