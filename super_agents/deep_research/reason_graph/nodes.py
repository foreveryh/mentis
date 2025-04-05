import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Literal
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
# --- Internal Imports ---
from super_agents.deep_research.reason_graph.state import ResearchState # Relative import
from super_agents.deep_research.reason_graph.schemas import ( # Relative import
    SearchQuery, 
    RequiredAnalysis, 
    AnalysisResult, 
    GapAnalysisResult, 
    FinalSynthesisResult, 
    SearchStepResult, 
    SearchResultItem,
    StreamUpdate,
    StepInfo,
    ResearchPlan
)
from super_agents.deep_research.reason_graph.tools import ( # Relative import
    llm, 
    llm_creative, 
    generate_structured_output, 
    perform_web_search, 
    perform_academic_search, 
    perform_x_search, 
    add_stream_update
)
from super_agents.deep_research.reason_graph.prompt import FINAL_REPORT_SYSTEM_PROMPT_TEMPLATE 
# --- Node Functions ---

async def plan_research(state: ResearchState) -> Dict[str, Any]:
    """Generates the initial research plan using an LLM."""
    topic = state['topic']
    updates = add_stream_update(state, {
        'id': 'research-plan-initial',
        'type': 'plan',
        'status': 'running',
        'title': 'Research Plan',
        'message': 'Creating research plan...',
        'overwrite': True
    })

    prompt = f"""Create a focused research plan for the topic: "{topic}". 

Today's date and day of the week: {datetime.now().strftime('%A, %B %d, %Y')}

Keep the plan concise but comprehensive, with:
- 4-12 targeted search queries (each can use web, academic, x (Twitter), or all sources)
- 2-8 key analyses to perform
- Prioritize the most important aspects to investigate (priority 2-4 for searches, 1-5 for analyses)

Available sources:
- "web": General web search (Use Tavily)
- "academic": Academic papers and research (Use Exa)
- "x": X/Twitter posts and discussions (Use Exa with domain filter)
- "all": Use all source types (web, academic, and X/Twitter)

Priority rules for search_queries:
- Use only whole numbers between 2 and 4. Lower number means higher priority (e.g., 2 is highest).

Importance rules for required_analyses:
- Use only whole numbers between 1 and 5. Higher number means higher importance.

Consider different angles and potential controversies, but maintain focus on the core aspects.
Ensure the total number of steps (searches + analyses) does not exceed 20."""

    research_plan = await asyncio.get_event_loop().run_in_executor(
        None, generate_structured_output, llm, ResearchPlan, prompt
    )
    # research_plan = generate_structured_output(llm, ResearchPlan, prompt) # If generate_structured_output is async

    return {"research_plan": research_plan, "stream_updates": updates}


def prepare_steps(state: ResearchState) -> Dict[str, Any]:
    """Processes the plan to create lists of search and analysis steps with IDs."""
    plan = state['research_plan']
    if not plan:
        raise ValueError("Research plan is missing.")

    search_steps_planned = []
    analysis_steps_planned = []
    search_counter = 0
    analysis_counter = 0

    # Generate search steps, expanding 'all'
    for i, query in enumerate(plan.search_queries):
        if query.source == 'all':
            search_steps_planned.append(StepInfo(id=f"search-web-{i}", type='web', details=query.dict()))
            search_steps_planned.append(StepInfo(id=f"search-academic-{i}", type='academic', details=query.dict()))
            search_steps_planned.append(StepInfo(id=f"search-x-{i}", type='x', details=query.dict()))
            search_counter += 3
        elif query.source == 'x':
            search_steps_planned.append(StepInfo(id=f"search-x-{i}", type='x', details=query.dict()))
            search_counter += 1
        elif query.source == 'academic':
            search_steps_planned.append(StepInfo(id=f"search-academic-{i}", type='academic', details=query.dict()))
            search_counter += 1
        else: # 'web'
            search_steps_planned.append(StepInfo(id=f"search-web-{i}", type='web', details=query.dict()))
            search_counter += 1

    # Generate analysis steps
    for i, analysis in enumerate(plan.required_analyses):
        analysis_steps_planned.append(StepInfo(id=f"analysis-{i}", type='analysis', details=analysis.dict()))
        analysis_counter += 1
        
    total_steps = search_counter + analysis_counter
    
    # Send plan completed update
    updates = add_stream_update(state, {
        'id': 'research-plan',
        'type': 'plan',
        'status': 'completed',
        'title': 'Research Plan',
        'plan': plan, # Send the plan object itself
        'totalSteps': total_steps,
        'message': 'Research plan created',
        'overwrite': True
    })

    return {
        "search_steps_planned": search_steps_planned,
        "analysis_steps_planned": analysis_steps_planned,
        "current_search_step_index": 0,
        "current_analysis_step_index": 0,
        "total_steps": total_steps,
        "completed_steps_count": 0, # Initialize completed steps
        "stream_updates": updates
    }


async def execute_search(state: ResearchState) -> Dict[str, Any]:
    """Executes a single search step based on the current index."""
    idx = state['current_search_step_index']
    step = state['search_steps_planned'][idx]
    query_obj = SearchQuery(**step.details)
    depth = state['depth']
    
    step_type = step.type
    step_id = step.id
    query_str = query_obj.query
    
    # 计算当前完成的步骤数和总步骤数，用于进度显示
    completed_steps = state.get('completed_steps_count', 0)
    total_steps = state.get('total_steps', 0)
    
    # Send running update with progress information
    running_updates = add_stream_update(state, {
        'id': step_id,
        'type': step_type,
        'status': 'running',
        'title': f"Searching {step_type} for '{query_str}'",
        'query': query_str,
        'message': f"Searching {query_obj.source} sources...",
        'completedSteps': completed_steps,
        'totalSteps': total_steps,
    })

    results = []
    search_step_result = None

    try:
        if step_type == 'web':
            results = await perform_web_search(query_str, depth, query_obj.priority)
        elif step_type == 'academic':
            results = await perform_academic_search(query_str, query_obj.priority)
        elif step_type == 'x':
            # Pass the full query object to x_search if it needs more context (like priority)
            results = await perform_x_search(query_obj)
            
        search_step_result = SearchStepResult(type=step_type, query=query_obj, results=results)
        
        # Send completed update
        completed_updates = add_stream_update(state, {
            'id': step_id,
            'type': step_type,
            'status': 'completed',
            'title': f"Search complete for '{query_str}'",
            'query': query_str,
            'results': results, # Send results in the update
            'message': f"Found {len(results)} results",
            'overwrite': True
        })
        
        all_updates = running_updates + completed_updates
        
        return {
            "search_results": [search_step_result] if search_step_result else [], # Use operator.add
            "current_search_step_index": idx + 1,
            "completed_steps_count": state.get('completed_steps_count', 0) + 1,
            "stream_updates": all_updates
        }
    except Exception as e:
        print(f"Error executing search step {step_id}: {e}")
         # Send error update
        error_updates = add_stream_update(state, {
            'id': step_id,
            'type': step_type,
            'status': 'completed', # Mark as completed even on error to proceed
            'title': f"Search failed for '{query_str}'",
            'query': query_str,
            'message': f"Error during search: {str(e)}",
            'overwrite': True
        })
        all_updates = running_updates + error_updates
        return {
            "search_results": [], 
            "current_search_step_index": idx + 1, # Move to next step even on error
            "completed_steps_count": state.get('completed_steps_count', 0) + 1, # Count error step as 'completed' for progress
            "stream_updates": all_updates
        }

async def perform_analysis(state: ResearchState) -> Dict[str, Any]:
    """Performs a single analysis step based on the current index."""
    idx = state['current_analysis_step_index']
    step = state['analysis_steps_planned'][idx]
    analysis_obj = RequiredAnalysis(**step.details)
    all_search_results = state['search_results']

    step_id = step.id
    analysis_type = analysis_obj.type
    analysis_desc = analysis_obj.description

    # 计算当前完成的步骤数和总步骤数，用于进度显示
    completed_steps = state.get('completed_steps_count', 0)
    total_steps = state.get('total_steps', 0)
    
    # Send running update with progress information
    running_updates = add_stream_update(state, {
        'id': step_id,
        'type': 'analysis',
        'status': 'running',
        'title': f"Analyzing {analysis_type}",
        'analysisType': analysis_type,
        'message': f"Analyzing {analysis_type}...",
        'completedSteps': completed_steps,
        'totalSteps': total_steps,
    })

    prompt = f"""Perform a "{analysis_type}" analysis. Analysis description: "{analysis_desc}"
Consider all sources and their reliability based on the provided search results.

Search results JSON: 
{json.dumps([r.dict() for r in all_search_results], indent=2)}

Generate findings (insight, evidence, confidence), implications, and limitations based *only* on the provided search results."""
    
    try:
        # Use the 'creative' LLM instance if needed
        analysis_result = await asyncio.get_event_loop().run_in_executor(
             None, generate_structured_output, llm_creative, AnalysisResult, prompt
        )
        # analysis_result = generate_structured_output(llm_creative, AnalysisResult, prompt) # If generate_structured_output is async

        # 更新完成步骤数
        completed_steps = state.get('completed_steps_count', 0) + 1
        
        # Send completed update with progress information
        completed_updates = add_stream_update(state, {
            'id': step_id,
            'type': 'analysis',
            'status': 'completed',
            'title': f"Analysis of {analysis_type} complete",
            'analysisType': analysis_type,
            # Simplify findings for streaming if needed, or send full object
            'findings': [f.dict() for f in analysis_result.findings], 
            'message': f"Analysis complete",
            'overwrite': True,
            'completedSteps': completed_steps,
            'totalSteps': total_steps
        })
        
        all_updates = running_updates + completed_updates

        # NOTE: The original code streams the result but doesn't seem to store
        # the *output* of individual analyses for later LLM steps, only the *plan*.
        # We will follow that here. If aggregation is needed, modify the state.
        return {
            "current_analysis_step_index": idx + 1,
            "completed_steps_count": state.get('completed_steps_count', 0) + 1,
            "stream_updates": all_updates
        }
    except Exception as e:
        print(f"Error performing analysis step {step_id}: {e}")
         # Send error update
        error_updates = add_stream_update(state, {
            'id': step_id,
            'type': 'analysis',
            'status': 'completed',
            'title': f"Analysis failed for {analysis_type}",
            'analysisType': analysis_type,
            'message': f"Error during analysis: {str(e)}",
            'overwrite': True
        })
        all_updates = running_updates + error_updates
        return {
            "current_analysis_step_index": idx + 1, # Move to next step
            "completed_steps_count": state.get('completed_steps_count', 0) + 1,
            "stream_updates": all_updates
        }


async def analyze_gaps(state: ResearchState) -> Dict[str, Any]:
    """Analyzes limitations and knowledge gaps based on all search results."""
    all_search_results = state['search_results']
    analysis_steps_info = state['analysis_steps_planned'] # Get info about what analyses were done

    # 计算当前完成的步骤数和总步骤数，用于进度显示
    completed_steps = state.get('completed_steps_count', 0)
    total_steps = state.get('total_steps', 0)
    
    # Send running update with progress information
    running_updates = add_stream_update(state, {
        'id': 'gap-analysis',
        'type': 'analysis',
        'status': 'running',
        'title': 'Research Gaps and Limitations',
        'analysisType': 'gaps',
        'message': 'Analyzing research gaps and limitations...',
        'completedSteps': completed_steps,
        'totalSteps': total_steps,
    })

    # Prepare info about analyses performed for the prompt
    analyses_performed_summary = [
        {"type": step.details.get('type'), "description": step.details.get('description')} 
        for step in analysis_steps_info
    ]

    prompt = f"""Analyze the research results and identify limitations, knowledge gaps, and recommended follow-up actions.
Consider:
- Quality and reliability of sources evident in the results.
- Missing perspectives or data based on the topic: "{state['topic']}".
- Areas needing deeper investigation.
- Potential biases or conflicts observed in the content.
- Severity for limitations should be between 2 and 10.
- Priority for follow-up actions should be between 2 and 10.

When suggesting additional_queries for knowledge gaps, keep in mind they might be used to search:
- Web sources (Tavily)
- Academic papers (Exa)
- X/Twitter (Exa)
Design queries likely to yield useful results across these diverse source types.

Research results JSON:
{json.dumps([r.dict() for r in all_search_results], indent=2)}

Analyses performed during research (types and descriptions):
{json.dumps(analyses_performed_summary, indent=2)}
"""
    try:
        gap_analysis_result = await asyncio.get_event_loop().run_in_executor(
             None, generate_structured_output, llm, GapAnalysisResult, prompt
        )
        # gap_analysis_result = generate_structured_output(llm, GapAnalysisResult, prompt) # If async
        
        # Calculate total steps including potential advanced steps for the update
        base_total_steps = state['total_steps']
        final_total_steps = base_total_steps + (2 if state['depth'] == 'advanced' else 1) # +1 for gap analysis, +1 for synthesis if advanced
        
        # Send completed update
        completed_updates = add_stream_update(state, {
            'id': 'gap-analysis',
            'type': 'analysis',
            'status': 'completed',
            'title': 'Research Gaps and Limitations',
            'analysisType': 'gaps',
            # Simplify findings for streaming
            'findings': [
                {"insight": l.description, "evidence": l.potential_solutions, "confidence": (10 - l.severity) / 8.0} 
                for l in gap_analysis_result.limitations
            ], 
            'gaps': gap_analysis_result.knowledge_gaps,
            'recommendations': gap_analysis_result.recommended_followup,
            'message': f"Identified {len(gap_analysis_result.limitations)} limitations and {len(gap_analysis_result.knowledge_gaps)} knowledge gaps",
            'overwrite': True,
            'completedSteps': state.get('completed_steps_count', 0) + 1,
            'totalSteps': final_total_steps
        })
        
        all_updates = running_updates + completed_updates
        
        # Prepare additional queries if needed
        additional_queries_planned = []
        if state['depth'] == 'advanced' and gap_analysis_result.knowledge_gaps:
             for gap_idx, gap in enumerate(gap_analysis_result.knowledge_gaps):
                 for query_idx, query_str in enumerate(gap.additional_queries):
                     # Strategy: 'all' for first query per gap, rotate others
                     source: Literal['web', 'academic', 'x', 'all']
                     if query_idx == 0:
                         source = 'all'
                     else:
                         source_types: List[Literal['web', 'academic', 'x']] = ['web', 'academic', 'x']
                         source = source_types[query_idx % len(source_types)]
                         
                     additional_queries_planned.append(SearchQuery(
                         query=query_str,
                         rationale=gap.reason,
                         source=source,
                         priority=3 # Default priority for gap fills
                     ))

        return {
            "gap_analysis": gap_analysis_result,
            "completed_steps_count": state.get('completed_steps_count', 0) + 1,
            "stream_updates": all_updates,
            "additional_queries_planned": additional_queries_planned,
            "current_gap_search_index": 0, # Initialize gap search index
            "total_steps": final_total_steps # Update total steps in state
        }
    except Exception as e:
        print(f"Error during gap analysis: {e}")
        # Send error update
        error_updates = add_stream_update(state, {
            'id': 'gap-analysis',
            'type': 'analysis',
            'status': 'completed',
            'title': 'Gap Analysis Failed',
            'analysisType': 'gaps',
            'message': f"Error during gap analysis: {str(e)}",
            'overwrite': True,
            'completedSteps': state.get('completed_steps_count', 0) + 1,
             # Use base total steps + 1 for gap analysis step itself
            'totalSteps': state['total_steps'] + 1 
        })
        all_updates = running_updates + error_updates
        return {
            "gap_analysis": None, # Indicate failure
            "completed_steps_count": state.get('completed_steps_count', 0) + 1,
            "stream_updates": all_updates,
            "additional_queries_planned": [], # No additional searches on error
            "current_gap_search_index": 0,
             # Ensure total_steps reflects only the completed gap analysis attempt
            "total_steps": state['total_steps'] + 1 
        }


async def execute_gap_search(state: ResearchState) -> Dict[str, Any]:
    """Executes searches based on identified gaps (for advanced depth)."""
    idx = state['current_gap_search_index']
    if not state.get('additional_queries_planned') or idx >= len(state['additional_queries_planned']):
        return {} # Should not happen if logic is correct, but safe return

    query_obj = state['additional_queries_planned'][idx]
    depth = state['depth'] # Should be 'advanced' here
    
    # 计算当前完成的步骤数和总步骤数，用于进度显示
    completed_steps = state.get('completed_steps_count', 0)
    total_steps = state.get('total_steps', 0)
    
    all_new_results: List[SearchStepResult] = []
    all_updates: List[StreamUpdate] = []
    
    search_tasks = []
    step_ids = []

    # If source is 'all', create tasks for web, academic, and x
    # Otherwise, create a task for the specific source
    
    base_id = f"gap-search-{state['current_search_step_index'] + idx}" # Create a unique enough ID base

    sources_to_search: List[Literal['web', 'academic', 'x']] = []
    if query_obj.source == 'all':
        sources_to_search = ['web', 'academic', 'x']
    else:
        sources_to_search = [query_obj.source]

    search_counter = 0 # To create unique IDs if 'all'
    for source_type in sources_to_search:
        step_id = f"{base_id}-{source_type}" if query_obj.source == 'all' else base_id
        step_ids.append(step_id)
        
        # Send running update with progress information
        running_update = add_stream_update(state, {
            'id': step_id,
            'type': source_type,
            'status': 'running',
            'title': f"Additional {source_type} search for '{query_obj.query}'",
            'query': query_obj.query,
            'message': f"Searching {source_type} to fill gap: {query_obj.rationale}",
            'completedSteps': completed_steps,
            'totalSteps': total_steps,
        })
        all_updates.extend(running_update)
        
        # Create async task
        if source_type == 'web':
            search_tasks.append(perform_web_search(query_obj.query, depth, query_obj.priority))
        elif source_type == 'academic':
            search_tasks.append(perform_academic_search(query_obj.query, query_obj.priority))
        elif source_type == 'x':
            search_tasks.append(perform_x_search(query_obj)) # Pass full object
            
        search_counter +=1

    # Execute searches concurrently
    try:
        search_outputs: List[List[SearchResultItem]] = await asyncio.gather(*search_tasks)
        
        # Process results and send completed updates
        for i, results in enumerate(search_outputs):
            source_type = sources_to_search[i]
            step_id = step_ids[i]
            
            # Create a query object specific to this source type for the result log
            specific_query = SearchQuery(
                query=query_obj.query, 
                rationale=query_obj.rationale, 
                source=source_type, 
                priority=query_obj.priority
            )
            step_result = SearchStepResult(type=source_type, query=specific_query, results=results)
            all_new_results.append(step_result)
            
            completed_update = add_stream_update(state, {
                'id': step_id,
                'type': source_type,
                'status': 'completed',
                'title': f"Additional {source_type} search complete for '{query_obj.query}'",
                'query': query_obj.query,
                'results': results,
                'message': f"Found {len(results)} results",
                'overwrite': True # Overwrite the running status
            })
            all_updates.extend(completed_update)

    except Exception as e:
         print(f"Error during gap search for query '{query_obj.query}': {e}")
         # Send error updates for all attempted steps in this batch
         for i, source_type in enumerate(sources_to_search):
             step_id = step_ids[i]
             error_update = add_stream_update(state, {
                 'id': step_id,
                 'type': source_type,
                 'status': 'completed',
                 'title': f"Additional {source_type} search failed for '{query_obj.query}'",
                 'query': query_obj.query,
                 'message': f"Error during gap search: {str(e)}",
                 'completedSteps': completed_steps,
                 'totalSteps': total_steps,
                 'overwrite': True
             })
             all_updates.extend(error_update)
         # Do not add partial results if gather failed significantly
         all_new_results = []


    return {
        "search_results": all_new_results, # Append results
        "current_gap_search_index": idx + 1,
        "stream_updates": all_updates
        # Note: completed_steps_count is handled in the final synthesis update
    }


async def synthesize_final_report(state: ResearchState) -> Dict[str, Any]:
    """Synthesizes all findings if advanced search was performed."""
    all_search_results = state['search_results']
    gap_analysis = state.get('gap_analysis')
    
    # This node is only reached if depth=='advanced' and gaps were found/searched
    
    # 计算当前完成的步骤数和总步骤数，用于进度显示
    completed_steps = state.get('completed_steps_count', 0)
    total_steps = state.get('total_steps', 0)
    
    # Send running update with progress information
    running_updates = add_stream_update(state, {
        'id': 'final-synthesis',
        'type': 'analysis',
        'status': 'running',
        'title': 'Final Research Synthesis',
        'analysisType': 'synthesis',
        'message': 'Synthesizing all research findings...',
        'completedSteps': completed_steps,
        'totalSteps': total_steps,
    })

    # Prepare gap analysis summary for prompt (avoid sending full objects if too large)
    gap_summary = "No gap analysis performed or available."
    if gap_analysis:
         gap_summary = {
             "limitations_summary": [l.description for l in gap_analysis.limitations],
             "knowledge_gaps_summary": [f"{g.topic}: {g.reason}" for g in gap_analysis.knowledge_gaps],
             "followup_summary": [f.action for f in gap_analysis.recommended_followup]
         }
         gap_summary = json.dumps(gap_summary, indent=2)


    prompt = f"""Synthesize all research findings, including the initial searches, the gap analysis, and any follow-up research conducted to fill those gaps.
Highlight key conclusions, assign a confidence score (0-1), list supporting evidence (e.g., citing source URLs or titles briefly), and identify remaining uncertainties.

Stick strictly to the requested output schema.

Topic: "{state['topic']}"

Combined Search Results (Initial + Gap Filling) JSON:
{json.dumps([r.dict() for r in all_search_results], indent=2, default=str)} 

Gap Analysis Summary:
{gap_summary}

Generate the final synthesis."""

    try:
        final_synthesis_result = await asyncio.get_event_loop().run_in_executor(
            None, generate_structured_output, llm, FinalSynthesisResult, prompt
        )
        # final_synthesis_result = generate_structured_output(llm, FinalSynthesisResult, prompt) # If async
        
        final_total_steps = state['total_steps'] # Should already include the +2 for advanced
        final_completed_steps = final_total_steps # Synthesis is the last step

        # Send completed update
        completed_updates = add_stream_update(state, {
            'id': 'final-synthesis',
            'type': 'analysis',
            'status': 'completed',
            'title': 'Final Research Synthesis',
            'analysisType': 'synthesis',
            'findings': [
                 {"insight": f.finding, "evidence": f.supporting_evidence, "confidence": f.confidence} 
                 for f in final_synthesis_result.key_findings
             ], # Simplified for stream
            'uncertainties': final_synthesis_result.remaining_uncertainties,
            'message': f"Synthesized {len(final_synthesis_result.key_findings)} key findings",
            'overwrite': True,
            'completedSteps': final_completed_steps -1, # Show as nearly complete before final progress update
            'totalSteps': final_total_steps
        })

        all_updates = running_updates + completed_updates
        
        # Add final progress update
        final_progress_update = add_stream_update(state, {
            'id': 'research-progress',
            'type': 'progress',
            'status': 'completed',
            'title': 'Research Progress', 
            'message': 'Research complete',
            'completedSteps': final_completed_steps,
            'totalSteps': final_total_steps,
            'isComplete': True,
            'overwrite': True, # Overwrite any previous progress
            'timestamp': time.time()
        })
        all_updates.extend(final_progress_update)

        return {
            "final_synthesis": final_synthesis_result,
            "stream_updates": all_updates,
            "completed_steps_count": final_completed_steps # Mark final count
        }
    except Exception as e:
        print(f"Error during final synthesis: {e}")
        final_total_steps = state['total_steps']
        # Send error update for synthesis
        running_updates = add_stream_update(state, { # 重新获取或确保 running_updates 可用
            'id': 'final-synthesis', 
            'type': 'analysis', 
            'status': 'running', 
            'title': 'Final Research Synthesis', 
            'analysisType': 'synthesis', 
            'message': 'Synthesizing all research findings...', 'timestamp': time.time() # Add timestamp if needed
        }) # 确保 running_updates 可用, 或者移除它如果你不打算在这里加它
        error_updates = add_stream_update(state, {
            'id': 'final-synthesis',
            'type': 'analysis',
            'status': 'completed', # Mark step as ended
            'title': 'Final Synthesis Failed',
            'analysisType': 'synthesis',
            'message': f"Error during synthesis: {str(e)}",
            'overwrite': True,
            'completedSteps': final_total_steps -1, 
            'totalSteps': final_total_steps
        })
         # Still send a final progress update, but indicate potential incompletion
        final_progress_update = add_stream_update(state, {
            'id': 'research-progress',
            'type': 'progress',
            'status': 'completed', # Research process finished, even if synthesis failed
            'title': 'Research Progress', 
            'message': 'Research finished, but final synthesis failed.',
            'completedSteps': final_total_steps - 1, # One step failed
            'totalSteps': final_total_steps,
            'isComplete': True, # The graph run is complete
            'overwrite': True 
        })
        all_updates = running_updates + error_updates + final_progress_update
        return {
            "final_synthesis": None, # Indicate failure
            "stream_updates": all_updates,
             "completed_steps_count": final_total_steps - 1
        }


def finalize_basic_research(state: ResearchState) -> Dict[str, Any]:
    """Adds the final progress update for basic depth or advanced without gaps."""
    final_total_steps = state['total_steps']
    final_completed_steps = state['completed_steps_count'] # Should be total_steps if no errors
    
    message = "Research complete"
    # Check if gap analysis failed, adjust message
    if state.get('gap_analysis') is None and state['current_analysis_step_index'] == len(state['analysis_steps_planned']):
         message = "Research finished, but gap analysis failed."
         final_completed_steps = state['completed_steps_count'] # Keep completed count as is

    final_progress_update = add_stream_update(state, {
        'id': 'research-progress',
        'type': 'progress',
        'status': 'completed',
        'title': 'Research Progress',
        'message': message,
        'completedSteps': final_completed_steps,
        'totalSteps': final_total_steps,
        'isComplete': True,
        'overwrite': True,
        'timestamp': time.time()
    })
    return {"stream_updates": final_progress_update}

# --- generate_final_markdown_report 函数 ---

async def generate_final_markdown_report(state: ResearchState) -> Dict[str, Any]:
    """Generates the final, long-form Markdown report using all gathered data."""

    print("--- Entering Node: generate_final_markdown_report ---")

    # --- 获取状态数据 ---
    topic = state['topic']
    final_synthesis = state.get('final_synthesis')
    search_results = state.get('search_results', [])
    gap_analysis = state.get('gap_analysis')
    
    # 计算当前完成的步骤数和总步骤数，用于进度显示
    completed_steps = state.get('completed_steps_count', 0)
    total_steps = state.get('total_steps', 0)

    # --- 检查是否有 Synthesis 数据 ---
    if not final_synthesis:
        print("Skipping final report generation: Final synthesis data is missing.")
        skipped_update = add_stream_update(state, {
            'id': 'final-report-generation', 'type': 'report', 'status': 'completed',
            'title': 'Final Report Generation Skipped',
            'message': 'Skipped report generation because final synthesis data was missing.',
            'completedSteps': completed_steps,
            'totalSteps': total_steps,
            'overwrite': True, 'timestamp': time.time()
        })
        base_total_steps = state.get('total_steps', 0)
        final_total_steps = base_total_steps # 没有增加步骤
        final_completed_steps = state.get('completed_steps_count', 0)
        final_progress_update = add_stream_update(state, {
             'id': 'research-progress', 'type': 'progress', 'status': 'completed',
             'title': 'Research Progress', 'message': 'Research finished, synthesis missing, report skipped.',
             'completedSteps': final_completed_steps, 'totalSteps': final_total_steps,
             'isComplete': True, 'overwrite': True, 'timestamp': time.time()
        })
        return {"final_report_markdown": None, "stream_updates": skipped_update + final_progress_update}

    # --- 发送运行中 Update ---
    running_updates = add_stream_update(state, {
        'id': 'final-report-generation',
        'type': 'report',
        'status': 'running',
        'title': 'Generating Final Report',
        'message': 'Compiling research findings into the final report...',
        'completedSteps': completed_steps,
        'totalSteps': total_steps,
        'timestamp': time.time() # 添加时间戳
    })
    all_updates = list(running_updates) # 初始化 updates 列表

    # --- 构建详细上下文 (只构建一次) ---
    print("--- Building Context for Final Report ---")
    context_parts = []
    context_parts.append(f"## Research Topic:\n{topic}\n")

    # 1. 添加 Final Synthesis 结果
    context_parts.append("## I. Synthesized Key Findings & Uncertainties (Core Content)\n")
    context_parts.append("### Key Findings (Elaborate on these using evidence below):\n")
    if final_synthesis.key_findings:
        for i, finding in enumerate(final_synthesis.key_findings):
            context_parts.append(f"**Finding {i+1}: {finding.finding}**")
            context_parts.append(f"   - Confidence: {finding.confidence:.2f}")
            context_parts.append(f"   - Evidence Hints: {', '.join(finding.supporting_evidence)}")
            context_parts.append("")
    else:
        context_parts.append("- No key findings were synthesized.\n")

    context_parts.append("### Remaining Uncertainties (Address in conclusion or limitations):\n")
    if final_synthesis.remaining_uncertainties:
        for uncertainty in final_synthesis.remaining_uncertainties:
            context_parts.append(f"- {uncertainty}")
    else:
        context_parts.append("- No specific remaining uncertainties identified.\n")
    context_parts.append("\n")

    # 2. 添加 Gap Analysis 结果
    if gap_analysis:
         context_parts.append("## II. Gap Analysis Summary (For 'Scope and Limitations' section):\n")
         if gap_analysis.limitations:
              context_parts.append("### Identified Limitations:\n")
              for limit in gap_analysis.limitations:
                   context_parts.append(f"- **{limit.type}**: {limit.description} (Severity: {limit.severity})")
                   if limit.potential_solutions:
                        context_parts.append(f"  - Potential Solutions: {'; '.join(limit.potential_solutions)}")
         else:
             context_parts.append("- No specific limitations identified.\n")

         if gap_analysis.knowledge_gaps:
              context_parts.append("### Identified Knowledge Gaps:\n")
              for gap in gap_analysis.knowledge_gaps:
                   context_parts.append(f"- **{gap.topic}**: {gap.reason}")
         else:
             context_parts.append("- No specific knowledge gaps identified.\n")
         context_parts.append("\n")
    else:
        context_parts.append("## II. Gap Analysis Summary:\n- Gap analysis was not performed or yielded no results.\n")

    # 3. 添加详细的 Search Results Context
    context_parts.append("## III. Search Results Context (Evidence for Citations [Title](URL) and Details):\n")
    search_results_list = state.get('search_results', [])
    total_results_count = sum(len(group.results) for group in search_results_list)
    context_parts.append(f"(Reference Appendix: Contains snippets from {total_results_count} collected results)\n")

    processed_urls: Set[str] = set()
    max_results_per_query_in_context = 5
    max_content_length = 600

    if search_results_list:
        for result_group in search_results_list:
             query_text = result_group.query.query
             source_type = result_group.type
             context_parts.append(f"### Context for Query: \"{query_text}\" ({source_type.upper()})\n")

             results_shown_count = 0
             if result_group.results:
                  for item in result_group.results:
                        if results_shown_count >= max_results_per_query_in_context:
                             break
                        if not item.url or item.url in processed_urls:
                             continue

                        title = item.title.replace('"',"'").strip() if item.title else "Source"
                        url = item.url

                        content_full = item.content if item.content else ""
                        content_snippet = content_full[:max_content_length]
                        if len(content_full) > max_content_length:
                             last_period = content_snippet.rfind('.')
                             if last_period > max_content_length * 0.7:
                                  content_snippet = content_snippet[:last_period+1]
                             else:
                                  content_snippet += "..."
                        content_snippet = content_snippet.replace('\n', ' ').strip()

                        context_parts.append(f"- **[{title}]({url})**")
                        if content_snippet:
                            context_parts.append(f"  - Snippet: {content_snippet}")

                        processed_urls.add(url)
                        results_shown_count += 1
             else:
                  context_parts.append("- (No relevant results found or processed for this query)")
             context_parts.append("")
    else:
        context_parts.append("- No search results were collected.\n")

    user_prompt_context = "\n".join(context_parts)
    # --- 上下文构建结束 ---

    # --- 定义 Prompts ---
    try:
        current_date_str = datetime.now().strftime("%a, %b %d, %Y")
        # 从 prompt.py 导入模板并格式化
        system_prompt = FINAL_REPORT_SYSTEM_PROMPT_TEMPLATE.format(current_date=current_date_str)
    except Exception as e:
        print(f"Error formatting system prompt: {e}")
        system_prompt = "Error: Could not format system prompt." # Fallback

    # User Prompt 结尾指令
    user_prompt = f"""Based *only* on the provided context below (Sections I, II, III), please generate the comprehensive research report following ALL the guidelines and requirements detailed in the system prompt. Ensure deep analysis, structure with Introduction, thematic H2 sections with H3 subsections for each finding (3-5 paragraphs each), Scope/Limitations, and Conclusion. Every factual claim MUST have an inline citation [Title](URL) from Section III. Aim for a substantial word count by fully utilizing the context.

{user_prompt_context}

Generate the final Markdown research report now:"""

    # --- Call LLM and handle response ---
    markdown_content = ""
    try:
        print("--- Calling LLM for Final Report Generation ---")
        response = await llm_creative.ainvoke([
            AIMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        markdown_content = response.content
        print(f"--- LLM Call Successful. Report Length: {len(markdown_content)} chars ---")

        # 发送 'final-report-generation' 完成 Update
        completed_updates = add_stream_update(state, {
            'id': 'final-report-generation', 'type': 'report', 'status': 'completed',
            'title': 'Final Report Generated',
            'message': f'Successfully generated Markdown report ({len(markdown_content)} characters).',
            'completedSteps': completed_steps,
            'totalSteps': total_steps,
            'overwrite': True, 'timestamp': time.time() # 添加时间戳
        })
        all_updates.extend(completed_updates) # 添加到列表中

        # 发送最终 'research-progress' 完成 Update
        base_total_steps = state.get('total_steps', 0)
        # 如果 base_total_steps 有效则加1，否则基于 completed_steps 加1
        final_total_steps = base_total_steps + 1 if base_total_steps > 0 else state.get('completed_steps_count', 0) + 1
        final_completed_steps = final_total_steps

        final_progress_update = add_stream_update(state, {
             'id': 'research-progress', 'type': 'progress', 'status': 'completed',
             'title': 'Research Progress', # <-- 确保有 title
             'message': 'Research complete',
             'completedSteps': final_completed_steps,
             'totalSteps': final_total_steps,
             'isComplete': True, 'overwrite': True, 'timestamp': time.time()
        })
        all_updates.extend(final_progress_update)

        print("--- Exiting Node: generate_final_markdown_report (Success) ---")
        return {
            "final_report_markdown": markdown_content,
            "stream_updates": all_updates,
            "completed_steps_count": final_completed_steps
        }

    except Exception as e:
        print(f"Error during final report generation: {e}")
        # 发送 'final-report-generation' 失败 Update
        error_updates = add_stream_update(state, {
            'id': 'final-report-generation', 'type': 'report', 'status': 'completed',
            'title': 'Final Report Generation Failed',
            'message': f"Error generating report: {str(e)}",
            'overwrite': True, 'timestamp': time.time()
        })
        all_updates.extend(error_updates)

        # 发送最终 'research-progress' 完成 (但报告失败) Update
        base_total_steps = state.get('total_steps', 0)
        final_total_steps = base_total_steps + 1 if base_total_steps > 0 else state.get('completed_steps_count', 0) + 1
        final_completed_steps = final_total_steps - 1 # 本节点失败

        final_progress_update = add_stream_update(state, {
             'id': 'research-progress', 'type': 'progress', 'status': 'completed',
             'title': 'Research Progress', # <-- 确保有 title
             'message': 'Research finished, but final report generation failed.',
             'completedSteps': final_completed_steps,
             'totalSteps': final_total_steps,
             'isComplete': True, 'overwrite': True, 'timestamp': time.time()
        })
        all_updates.extend(final_progress_update)

        print("--- Exiting Node: generate_final_markdown_report (Error) ---")
        return {
            "final_report_markdown": f"# Report Generation Failed\n\nError: {str(e)}",
            "stream_updates": all_updates,
            "completed_steps_count": state.get('completed_steps_count', 0) # 失败时不增加
        }