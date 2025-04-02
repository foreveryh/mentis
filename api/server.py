import uvicorn
from langgraph.types import Command, Interrupt
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from typing import AsyncGenerator, Dict, Optional, Union, Any
from api.utils import message_chunk_event, interrupt_event, custom_event, checkpoint_event, format_state_snapshot
import asyncio
import traceback
import json
from langchain_core.messages import HumanMessage

# Import the agent loader
from api.agent.loader import load_agent, list_available_agents, get_default_agent

# Load the default agent
graph = get_default_agent()

# Track active connections
active_connections: Dict[str, asyncio.Event] = {}

app = FastAPI(
    title="LangGraph API",
    description="API for LangGraph interactions",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/agents")
async def list_agents():
    """Endpoint returning a list of available agents."""
    return list_available_agents()


@app.get("/state")
async def state(thread_id: str | None = None, agent: Optional[str] = Query(None)):
    """Endpoint returning current graph state."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")
    
    # Load the specified agent if provided
    current_graph = load_agent(agent) if agent else graph
    if not current_graph:
        raise HTTPException(status_code=404, detail=f"Agent '{agent}' not found")

    config = {"configurable": {"thread_id": thread_id}}

    state = await current_graph.aget_state(config)
    return format_state_snapshot(state)


@app.get("/history")
async def history(thread_id: str | None = None, agent: Optional[str] = Query(None)):
    """Endpoint returning complete state history. Used for restoring graph."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")
    
    # Load the specified agent if provided
    current_graph = load_agent(agent) if agent else graph
    if not current_graph:
        raise HTTPException(status_code=404, detail=f"Agent '{agent}' not found")

    config = {"configurable": {"thread_id": thread_id}}

    records = []
    async for state in current_graph.aget_state_history(config):
        records.append(format_state_snapshot(state))
    return records


@app.post("/agent/stop")
async def stop_agent(request: Request):
    """Endpoint for stopping the running agent."""
    body = await request.json()
    thread_id = body.get("thread_id")
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    if thread_id in active_connections:
        active_connections[thread_id].set()
        return {"status": "stopped", "thread_id": thread_id}
    raise HTTPException(status_code=404, detail="Thread is not running")


@app.post("/agent")
async def agent(request: Request):
    """Endpoint for running the agent."""
    body = await request.json()

    request_type = body.get("type")
    if not request_type:
        raise HTTPException(status_code=400, detail="type is required")

    thread_id = body.get("thread_id")
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    # Get the agent name if provided
    agent_name = body.get("agent")
    
    # Load the specified agent if provided
    current_graph = load_agent(agent_name) if agent_name else graph
    if not current_graph:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name or 'default'}' not found")

    stop_event = asyncio.Event()
    active_connections[thread_id] = stop_event

    config = {"configurable": {"thread_id": thread_id}}
    initial_graph_state: Dict[str, Any] = {}
    input_for_astream: Optional[Union[Dict, Command]] = None  # input for astream

    # Get initial state or messages from frontend
    initial_state_input = body.get("state", {"messages": []})
    if not isinstance(initial_state_input, dict):
        raise HTTPException(status_code=400, detail="state must be a dictionary")

    if agent_name == "deep_research":
        # --- Prepare state for DeepResearch Agent ---
        print("Preparing state for DeepResearchAgent...")
        # Extract topic from the first message in state['messages']
        first_message_content = ""
        try:
            # Ensure initial_state_input['messages'] is a list and not empty
            if isinstance(initial_state_input.get('messages'), list) and initial_state_input['messages']:
                # Assume the first message's content is the topic
                first_message_content = initial_state_input['messages'][0]['content']
            else:
                # Try to get topic from other fields in state (alternative)
                first_message_content = initial_state_input.get('topic', '')
                
        except Exception as e:
            print(f"Warning: Could not extract topic from initial state input: {e}")

        if not first_message_content or not isinstance(first_message_content, str):
            raise HTTPException(status_code=400, detail="A valid 'topic' string is required for deep_research agent, expected in state.messages[0].content or state.topic")

        # Build the ResearchState needed by DeepResearch Agent (at least topic and depth)
        initial_graph_state = {
            "topic": first_message_content,
            "depth": initial_state_input.get("depth", "advanced"),  # Optional: allow frontend to specify depth
            "messages": [],  # DeepResearch manages its own message history
            "stream_updates": [],  # Initialize stream_updates
            # Initialize other ResearchState fields to None or default values
            "plan": None, "research_plan": None, "search_results": [], 
            "gap_analysis": None, "final_synthesis": None, 
            "final_report_markdown": None,
        }
        print(f"Initial ResearchState: {{'topic': '{initial_graph_state['topic']}', 'depth': '{initial_graph_state['depth']}', ...}}")
        
        # DeepResearch Agent's astream input is the complete initial state
        if request_type == "run":
            input_for_astream = initial_graph_state
        elif request_type == "resume":
            # DeepResearch Agent might not support or need different resume approach
            print("Warning: 'resume' might not be fully supported for DeepResearchAgent yet.")
            # Assume resume Command can be understood by the graph
            input_for_astream = Command(resume=body.get("resume"))
            config["configurable"]["checkpoint_id"] = body.get("resume")  # Resume usually needs checkpoint ID
        else:  # Fork, Replay typically only need config
            config_from_request = body.get("config")
            if not config_from_request:
                raise HTTPException(status_code=400, detail="config is required for fork/replay")
            config = config_from_request  # Use complete config provided in the request
            input_for_astream = None

    else:  # For Supervisor or other Agents (assume using PlanningAgentState)
        print("Preparing state for Supervisor/Other Agent...")
        # --- Prepare PlanningAgentState ---
        # Ensure messages list contains correct BaseMessage objects (or let BaseAgent preprocess)
        initial_messages = initial_state_input.get("messages", [])

        initial_graph_state = {
            "messages": initial_messages,
            "plan": None,  # Planner node will create it
            "error": None
            # Add other fields needed by PlanningAgentState and set to None or default values
        }
        
        # --- Set astream input (logic similar to before) ---
        if request_type == "run":
            # For PlanningAgentState, initial input typically only contains messages
            input_for_astream = {"messages": initial_messages}
        elif request_type == "resume":
            resume_val = body.get("resume")
            if not resume_val:
                raise HTTPException(status_code=400, detail="resume value is required")
            input_for_astream = Command(resume=resume_val)
            # Ensure config includes checkpoint_id for resuming
            if "configurable" not in config:
                config["configurable"] = {}
            config["configurable"]["checkpoint_id"] = resume_val 
        elif request_type == "fork": 
            config_from_request = body.get("config")
            if not config_from_request:
                raise HTTPException(status_code=400, detail="config is required for fork")
            config = config_from_request  # Fork uses complete config provided
            # Fork typically starts from specified checkpoint, no extra state dict input needed
            input_for_astream = None 
        elif request_type == "replay": 
            config_from_request = body.get("config")
            if not config_from_request:
                raise HTTPException(status_code=400, detail="config is required for replay")
            config = config_from_request
            input_for_astream = None
        else:
            raise HTTPException(status_code=400, detail="invalid request type")
             
    # Ensure config always has thread_id (important for all agents)
    if "configurable" not in config:
        config["configurable"] = {}
    config["configurable"]["thread_id"] = thread_id

    # --- State and Input preparation complete ---
    print(f"Agent: {agent_name or 'default'}, Request Type: {request_type}")
    print(f"Input for astream: {type(input_for_astream)}")
    print(f"Config for astream: {config}")

    async def generate_events() -> AsyncGenerator[dict, None]:
        try:
            async for chunk in current_graph.astream(
                input_for_astream,  # Use prepared input
                config,             # Use prepared config
                stream_mode=["debug", "messages", "updates", "custom"],
            ):
                if stop_event.is_set():
                    break

                chunk_type, chunk_data = chunk

                if chunk_type == "debug":
                    # type can be checkpoint, task, task_result
                    debug_type = chunk_data["type"]
                    if debug_type == "checkpoint":
                        yield checkpoint_event(chunk_data)
                    elif debug_type == "task_result":
                        interrupts = chunk_data["payload"].get(
                            "interrupts", [])
                        if interrupts and len(interrupts) > 0:
                            yield interrupt_event(interrupts)
                elif chunk_type == "messages":
                    yield message_chunk_event(chunk_data[1]["langgraph_node"], chunk_data[0])
                elif chunk_type == "custom":
                    # Check if this is a StreamUpdate
                    if isinstance(chunk_data, dict) and all(k in chunk_data for k in ['id', 'type', 'status', 'title']):
                        # Use stream_update_event formatter if available, otherwise fall back to custom_event
                        try:
                            from api.utils import stream_update_event
                            yield stream_update_event(chunk_data)
                        except ImportError:
                            yield custom_event(chunk_data)
                    else:
                        yield custom_event(chunk_data)
                elif chunk_type == "updates":
                    # Handle state update events (e.g., real-time Plan updates)
                    pass  # Currently ignore updates events, rely on checkpoint or custom
            
            # --- Loop ended ---
            yield {"event": "end", "data": "{}"}  # Send an end event to frontend

        except Exception as e:
            print(f"Error during agent execution stream: {e}")
            traceback.print_exc()
            # Send error event to frontend
            yield {"event": "error", "data": json.dumps({"message": f"Agent execution error: {e}"})}
        finally:
            if thread_id in active_connections:
                del active_connections[thread_id]

    return EventSourceResponse(generate_events())


def main():
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
