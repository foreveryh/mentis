/** 
 * Represents the current status of an agent:
 * - idle: agent is not running, waiting for user input
 * - running: agent is running
 * - stopping: stop request has been sent, waiting for agent to stop
 * - error: error has occurred calling agent. It can occur when the agent is not accessible 
 *          or when there is an error handling the request.
 * 
 * Note: If there is an error in the graph node, the error property will be set to true in GraphNode.
 */
export type AgentStatus = 'idle' | 'running' | 'stopping' | 'error';

/** Represents LangGraph checkpoint config */
export type CheckpointConfig = { configurable: { thread_id: string, checkpoint_id: string, checkpoint_ns: string } };

/** Represents LangGraph checkpoint metadata */
export type CheckpointMetadata = {
  source: string;
  step: number;
  writes: Record<string, object | object[]>;
  parents: Record<string, string>;
};

/** Generic interface for an interruption (Human in the loop). Value can be anything. */
export interface Interrupt<TInterruptValue> {
  value: TInterruptValue;
}

/** Represents LangGraph checkpoint
 * This object is recieved from the agent server.
 */
export interface Checkpoint<TAgentState, TInterruptValue> {
  next: string[];
  values: TAgentState;
  config: CheckpointConfig;
  interrupts?: Interrupt<TInterruptValue>[];
  parent_config?: CheckpointConfig;
  metadata?: CheckpointMetadata;
}

/** Graph checkpoint in the application.
 * @param nodes - array of nodes in the graph
 * @param stateInitial - initial state when checkpoint is created
 * @param state - state of the checkpoint after the nodes has been executed or intermediate state
 * @param stateDiff - difference between the initial state and the state after the node has been executed
 * @param interruptValue - contains the value passed to the interrupt function in the node
 * @param checkpointConfig - checkpoint config of the node
 * @param error - true if there is an error in the nodes.
 */
export interface AppCheckpoint<TAgentState, TInterruptValue> {
  nodes: GraphNode<TAgentState>[];
  stateInitial: TAgentState;
  state: TAgentState;
  stateDiff: TAgentState;
  interruptValue?: TInterruptValue;
  checkpointConfig: CheckpointConfig;
  error: boolean;
}

/** Node that is executed in the checkpoint.
 * @param name - name of the node
 * @param state - the state produced by the node
 */
export interface GraphNode<TAgentState> {
  name: string;
  state: Partial<TAgentState>;
}

/** Representation of the LangChain message. */
export interface Message {
  type: string;
  content: string;
  id?: string;
  tool_calls?: ToolCall[];
  name?: string; // Added name field
}

export type ToolCall = { name: string, args: object, id: string };

// StreamUpdateData interface for research progress updates
export interface StreamUpdateData {
  id: string;
  timestamp: number;
  title: string;
  status: 'running' | 'completed' | 'error';
  message: string;
  completedSteps?: number;
  totalSteps?: number;
  metadata?: Record<string, any>;
}

/** Data of the message chunk event. */
export interface NodeMessageChunk {
  node_name: string;
  message_chunk: MessageChunk;
}

/** Represents a LangChain message chunk. LLMs stream messages in chunks. */
export interface MessageChunk {
  content: string;
  id: string;
  tool_call_chunks?: ToolCallChunk[];
}

export type ToolCallChunk = { name?: string, args?: object, id?: string };

/** Interface for states that have messages property.
 * Inherit this interface in your agent state interface if you use messages.
 */
export interface WithMessages {
  messages: Message[];
}

/** Events that are emitted by the agent.
 * @param event - event type. Can be 'checkpoint', 'message_chunk', 'interrupt', 'custom', 'error', 'stream_update', 'end'.
 */
export interface AgentEvent<TAgentState, TInterruptValue> {
  event: string; // 'checkpoint', 'message_chunk', 'interrupt', 'custom', 'error', 'stream_update', 'end'
  data: Checkpoint<TAgentState, TInterruptValue> | NodeMessageChunk | Interrupt<TInterruptValue>[] | Partial<TAgentState> | StreamUpdateData | string | any;
}

/** Generic interface for an agent input. Thread id is required. */
interface AgentInput {
  thread_id: string;
}

export interface RunAgentInput<TAgentState> extends AgentInput {
  state: Partial<TAgentState>;
}

export interface ResumeAgentInput<TResumeValue> extends AgentInput {
  resume: TResumeValue;
}

export interface ForkAgentInput<TAgentState> extends AgentInput {
  config: CheckpointConfig;
  state: Partial<TAgentState>;
}

export interface ReplayAgentInput extends AgentInput {
  config: CheckpointConfig;
}

export interface RunAgentInputInternal<TAgentState> extends RunAgentInput<TAgentState> {
  type: "run";
}

export interface ResumeAgentInputInternal<TResumeValue> extends ResumeAgentInput<TResumeValue> {
  type: "resume";
}

export interface ForkAgentInputInternal<TAgentState> extends ForkAgentInput<TAgentState> {
  type: "fork";
}

export interface ReplayAgentInputInternal extends ReplayAgentInput {
  type: "replay";
}