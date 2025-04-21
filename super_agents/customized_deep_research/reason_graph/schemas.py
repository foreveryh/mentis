from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
import time

# --- Schemas for Planning ---
class SearchQuery(BaseModel):
    query: str = Field(..., description="The specific search query string.")
    tool_hint: str = Field("web_search", description="Hint for which tool to use (e.g., 'yfinance', 'web_search', 'news_api').")
    # Optional: Add expected information type if needed

class RequiredAnalysis(BaseModel):
    analysis_goal: str = Field(..., description="The specific question or goal for the analysis step.")
    required_inputs: List[str] = Field(default_factory=list, description="Data types needed for this analysis (e.g., 'yfinance_financials', 'web_search_market_info').")

class ResearchPlan(BaseModel):
    search_queries: List[SearchQuery] = Field(..., description="List of planned search queries.")
    required_analyses: List[RequiredAnalysis] = Field(..., description="List of planned analysis steps.")

# --- Schemas for Search Results ---
class SearchResultItem(BaseModel):
    title: str
    url: Optional[str] = None
    snippet: str

class SearchStepResult(BaseModel):
    query: str
    results: List[SearchResultItem] = Field(default_factory=list)
    tool_used: Optional[str] = None # Optional: Track which tool generated results

# --- Schemas for Analysis ---
class AnalysisResult(BaseModel):
    analysis_goal: str
    analysis_result: str # The textual output of the analysis

# --- Schemas for Gap Analysis ---
class GapFollowUpQuery(BaseModel):
     query: str = Field(..., description="Specific web search query to fill a gap.")
     tool_hint: str = Field("web_search", description="Should primarily be 'web_search' in this version.")
     rationale: Optional[str] = Field(None, description="Why this query helps fill a gap.")

class GapAnalysisResult(BaseModel):
    summary: str = Field(..., description="Summary of key limitations and information gaps, focusing on YFinance/Web constraints for M&A.")
    follow_up_queries: List[GapFollowUpQuery] = Field(default_factory=list, description="Suggested *web search* queries to potentially find related info.")

# --- Schemas for Synthesis & Reporting ---
class KeyFinding(BaseModel):
     finding: str = Field(..., description="A single key finding or insight.")
     evidence_source: Optional[str] = Field(None, description="Brief note on source (e.g., 'YFinance Trend', 'Web Search Mention').")

class FinalSynthesisResult(BaseModel):
    key_findings_summary: str = Field(..., description="Synthesized summary of the most important findings relevant to M&A, based on YFinance/Web.")
    remaining_uncertainties: List[str] = Field(..., description="List of key questions or uncertainties remaining due to data limitations.")
    # Optional: Add structured key findings list if needed
    # key_findings: List[KeyFinding] = Field(default_factory=list)

# --- Schemas for UI Streaming & State ---
class StreamUpdateData(BaseModel):
    id: str # Unique ID for the step/update type
    type: Literal["plan", "search", "analysis", "data_fetch", "synthesis", "report", "progress", "steps_list", "error", "info", "setup", "end"]
    status: Literal["pending", "running", "completed", "error", "skipped", "warning"]
    title: Optional[str] = None # User-friendly title for the step
    message: Optional[str] = None # Status message
    payload: Optional[Dict[str, Any] | List[Dict[str, Any]]] = None # Any associated data (e.g., results preview, step list)
    overwrite: bool = False # Whether this update should replace previous updates with the same ID
    isComplete: Optional[bool] = None # For progress updates
    completedSteps: Optional[float] = None # For progress updates
    totalSteps: Optional[int] = None # For progress updates

class StreamUpdate(BaseModel):
    data: StreamUpdateData
    timestamp: float = Field(default_factory=time.time)

class StepInfo(BaseModel):
    id: str
    type: str
    status: str
    title: str
    description: Optional[str] = None