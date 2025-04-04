import { useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import {
  Checkpoint,
  Interrupt,
  AppCheckpoint,
  RunAgentInput,
  ResumeAgentInput,
  ForkAgentInput,
  ReplayAgentInput,
  RunAgentInputInternal,
  ResumeAgentInputInternal,
  ForkAgentInputInternal,
  ReplayAgentInputInternal,
  AgentStatus,
  ToolCall,
  WithMessages,
  NodeMessageChunk,
  StreamUpdateData,
  Message,
} from './types';
import { callAgentRoute } from './api';
import { getHistory, stopAgent } from './actions';

interface UseAgentStateCallbacks<TAgentState extends object | WithMessages, TInterruptValue> {
  /** Callback for when a checkpoint starts.*/
  onCheckpointStart?: (checkpoint: AppCheckpoint<TAgentState, TInterruptValue>) => void;
  /** Callback for when a checkpoint ends. */
  onCheckpointEnd?: (checkpoint: AppCheckpoint<TAgentState, TInterruptValue>) => void;
  /** Callback for when a checkpoint intermediate state is updated. It can happen in if the custom event in the node is called. */
  onCheckpointStateUpdate?: (checkpoint: AppCheckpoint<TAgentState, TInterruptValue>) => void;
}

// Singleton cache that persists across page navigations
// Enable if needed
const historyCache = new Map<string, Checkpoint<any, any>[]>();
const enableRestoreCache = false;

/**
 * Hook to manage agent state and execution.
 * @template TAgentState - Type of agent state. Can be any object or an object implementing {@link WithMessages} interface.
 *                        If the state has 'messages' property, it will be used for message processing.
 * @template TInterruptValue - Type of value used when agent execution is interrupted (usually several types of interruptions are possible).
 * @template TResumeValue - Type of value used when resuming agent execution (usually several types of resumes are possible).
 * @param callbacks - Optional callbacks for checkpoint lifecycle events (see {@link UseAgentStateCallbacks}).
 */
export function useLangGraphAgent<TAgentState extends object | WithMessages, TInterruptValue, TResumeValue>(
  callbacks?: UseAgentStateCallbacks<TAgentState, TInterruptValue>
) {
  const { onCheckpointStart, onCheckpointEnd, onCheckpointStateUpdate } = callbacks ?? {};

  const [status, setStatus] = useState<AgentStatus>('idle');
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState(false);
  const [appCheckpoints, setAppCheckpoints] = useState<AppCheckpoint<TAgentState, TInterruptValue>[]>([]);
  // Add messages state to directly manage message history
  const [messages, setMessages] = useState<Message[]>([]);
  const [progressUpdates, setProgressUpdates] = useState<Record<string, StreamUpdateData>>({});

  /**
   * Run the agent.
   * @param agentInput - Input configuration for running the agent (see {@link RunAgentInput}).
   */
  const run = useCallback(async (agentInput: RunAgentInput<TAgentState>) => {
    // Extract user input messages from state and ensure they have IDs
    const userInputMessages = (agentInput.state as WithMessages)?.messages ?? [];
    if (userInputMessages.length > 0 && !userInputMessages[0].id) {
      userInputMessages[0].id = `user-${uuidv4()}`;
    }

    // Update messages state immediately to show user input
    setMessages(prev => [...prev, ...(userInputMessages as Message[])]);
    
    setProgressUpdates({}); // Reset progress updates
    setAppCheckpoints([]); // Clear checkpoints for new run
    
    await callAgent({ type: "run", ...agentInput });
  }, []);

  /**
   * Resume the agent. Action should be called after the agent has been interrupted.
   * @param agentInput - Input configuration for resuming the agent (see {@link ResumeAgentInput}).
   */
  const resume = useCallback(async (agentInput: ResumeAgentInput<TResumeValue>) => {
    await callAgent({ type: "resume", ...agentInput });
  }, []);

  /**
   * Fork the checkpoint with the updated state.
   * @param agentInput - Input configuration for forking the agent (see {@link ForkAgentInput}).
   */
  const fork = useCallback(async (agentInput: ForkAgentInput<TAgentState>) => {
    removeAppCheckpointsAfterCheckpoint(agentInput.config.configurable.checkpoint_id);
    await callAgent({ type: "fork", ...agentInput });
  }, []);

  /**
   * Runs agent from the checkpoint.
   * @param agentInput - Input configuration for replaying the agent (see {@link ReplayAgentInput}).
   */
  const replay = useCallback(async (agentInput: ReplayAgentInput) => {
    removeAppCheckpointsAfterCheckpoint(agentInput.config.configurable.checkpoint_id);
    await callAgent({ type: "replay", ...agentInput });
  }, []);

  /**
   * Stops the agent execution. Agent will not stop immediately. It will stop before emitting the last event (see {@link AgentEvent}).
   * @param threadId - The ID of the thread to stop.
   */
  const stop = useCallback(async (threadId: string) => {
    try {
      setStatus('stopping');
      await stopAgent(threadId);
    } catch (error) {
      console.error('Error stopping agent:', error);
      setStatus('idle');
    }
  }, []);

  function removeAppCheckpointsAfterCheckpoint(checkpointId: string) {
    setAppCheckpoints(prevCheckpoints => {
      const index = prevCheckpoints.findIndex(
        node => node.checkpointConfig.configurable.checkpoint_id === checkpointId
      );
      if (index !== -1) {
        return prevCheckpoints.slice(0, index + 1);
      }
      return prevCheckpoints;
    });
  }

  const callAgent = useCallback(async (agentInput: RunAgentInputInternal<TAgentState> | ResumeAgentInputInternal<TResumeValue> | ForkAgentInputInternal<TAgentState> | ReplayAgentInputInternal) => {
    if (!agentInput.type) {
      throw new Error('Type is required');
    }

    if (!agentInput.thread_id) {
      throw new Error('Thread id is required');
    }

    // Create local copies of state to modify during streaming
    let currentMessagesCopy: Message[] = [];
    setMessages(prev => { 
      currentMessagesCopy = [...prev]; 
      return prev;
    });
    
    let currentAppCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[] = [];
    setAppCheckpoints(prev => { 
      currentAppCheckpoints = [...prev]; 
      return prev;
    });

    try {
      setStatus('running');
      // Invalidate cache when agent is called
      historyCache.delete(agentInput.thread_id);

      const messageStream = callAgentRoute<TAgentState, TInterruptValue, TResumeValue>(agentInput);
      for await (const msg of messageStream) {
        if (msg.event === 'checkpoint') {
          const checkpoint = msg.data as Checkpoint<TAgentState, TInterruptValue>;
          processCheckpoint(checkpoint, currentAppCheckpoints);
          
          // Update messages from checkpoint state if available
          const stateValues = checkpoint.values as WithMessages;
          if (stateValues?.messages) {
            currentMessagesCopy = deepCopy(stateValues.messages);
            setMessages([...currentMessagesCopy]);
          }
          
          setAppCheckpoints([...currentAppCheckpoints]);
        }

        if (msg.event === 'message_chunk') {
          processMessageChunk(msg.data as NodeMessageChunk, currentMessagesCopy);
          setMessages([...currentMessagesCopy]);
        }

        if (msg.event === 'stream_update') {
          try {
            let updateData: StreamUpdateData;
            if (typeof msg.data === 'string') {
              updateData = JSON.parse(msg.data) as StreamUpdateData;
            } else {
              updateData = msg.data as StreamUpdateData;
            }
            
            if (updateData?.id) {
              setProgressUpdates(prev => ({ ...prev, [updateData.id]: updateData }));
            } else {
              console.warn("Invalid stream_update data");
            }
          } catch (e) {
            console.error("Error processing stream_update:", e, msg.data);
          }
        }

        if (msg.event === 'custom') {
          processCustomEvent(msg.data as Partial<TAgentState>, currentAppCheckpoints);
          setAppCheckpoints([...currentAppCheckpoints]);
        }

        if (msg.event === 'interrupt') {
          processInterrupts(msg.data as Interrupt<TInterruptValue>[], currentAppCheckpoints);
          setAppCheckpoints([...currentAppCheckpoints]);
        }

        if (msg.event === 'error') {
          processError(currentAppCheckpoints);
          setAppCheckpoints([...currentAppCheckpoints]);
          setStatus('error');
        }
      }

      setStatus('idle');
    } catch (error) {
      console.error('Error in callAgent:', error);
      // Keep current messages on error
      setMessages(currentMessagesCopy);
      setStatus('error');
    }
  }, [onCheckpointStart, onCheckpointEnd, onCheckpointStateUpdate]);

  /**
   * Restores the agent state from the checkpoints history.
   * @param threadId - The ID of the thread to restore.
   * @returns Promise that resolves to the restored checkpoints
   */
  const restore = useCallback(async (threadId: string): Promise<AppCheckpoint<TAgentState, TInterruptValue>[]> => {
    if (!threadId) {
      throw new Error('Thread id is required');
    }

    try {
      setRestoring(true);
      setRestoreError(false);

      const restoredCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[] = [];
      let finalMessagesCopy: Message[] = [];
      
      let history: Checkpoint<TAgentState, TInterruptValue>[];

      // Try to get history from cache
      const cachedHistory = historyCache.get(threadId);
      if (cachedHistory && enableRestoreCache) {
        console.log("Getting history from cache");
        history = cachedHistory;
      } else {
        history = await getHistory(threadId);
        historyCache.set(threadId, history);
      }

      // History contains all forks of graph execution. We need to restore the last fork.
      const newHistory: Checkpoint<TAgentState, TInterruptValue>[] = [];
      let skipToCheckpointId: string | undefined = undefined;
      for (let i = 0; i < history.length; i++) {
        if (skipToCheckpointId && history[i].config.configurable.checkpoint_id !== skipToCheckpointId) {
          continue;
        }

        newHistory.push(history[i]);
        skipToCheckpointId = history[i].parent_config?.configurable.checkpoint_id;
      }

      for (const checkpoint of newHistory.reverse()) {
        processHistoryCheckpoint(checkpoint, restoredCheckpoints);
        
        // Extract messages from checkpoint state
        const stateValues = checkpoint.values as WithMessages;
        if (stateValues?.messages) {
          finalMessagesCopy = deepCopy(stateValues.messages);
        }
      }

      setAppCheckpoints(restoredCheckpoints);
      setMessages(finalMessagesCopy);
      
      return restoredCheckpoints;
    } catch (error) {
      console.error('Error restoring agent:', error);
      setRestoreError(true);
      throw new Error('Error restoring agent');
    } finally {
      setRestoring(false);
    }
  }, []);

  function processHistoryCheckpoint(checkpoint: Checkpoint<TAgentState, TInterruptValue>, appCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[]) {
    let interruptionInLastCheckpoint = false;

    // Update the last checkpoint with the latest checkpoint values
    if (appCheckpoints.length > 0) {
      const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
      lastCheckpoint.state = deepCopy(checkpoint.values);
      lastCheckpoint.stateDiff = getStateDiff(lastCheckpoint.stateInitial, checkpoint.values);
      updateGraphNodeStateFromMetadata(lastCheckpoint, checkpoint);

      // Delete interrupt if there are further checkpoints to restore.
      // Preserve interrupt for the last checkpoint.
      interruptionInLastCheckpoint = lastCheckpoint.interruptValue !== undefined;
      if (interruptionInLastCheckpoint) {
        lastCheckpoint.interruptValue = undefined;
      }
    }

    // Create a new app checkpoint except for the last checkpoint.
    if (checkpoint.next.length > 0) {
      const newAppCheckpoint = createAppCheckpoint(checkpoint);

      // When restoring checkpoints from graph history, the checkpoint stores interrupts as interrupts property.
      if (checkpoint.interrupts) {
        newAppCheckpoint.interruptValue = checkpoint.interrupts?.[0]?.value; // handle only single interrupt for now
      }
      appCheckpoints.push(newAppCheckpoint);
    }
  }

  function processCheckpoint(checkpoint: Checkpoint<TAgentState, TInterruptValue>, appCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[]) {
    let interruptionInLastCheckpoint = false;

    // Update the last checkpoint with the latest checkpoint values
    if (appCheckpoints.length > 0) {
      const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
      lastCheckpoint.state = deepCopy(checkpoint.values);
      lastCheckpoint.stateDiff = getStateDiff(lastCheckpoint.stateInitial, checkpoint.values);
      updateGraphNodeStateFromMetadata(lastCheckpoint, checkpoint);

      // Delete interrupt if there are further checkpoints. It means that the interruption was handled.
      // Preserve interrupt for the last checkpoint.
      interruptionInLastCheckpoint = lastCheckpoint.interruptValue !== undefined;
      if (interruptionInLastCheckpoint) {
        lastCheckpoint.interruptValue = undefined;
        onCheckpointEnd?.(lastCheckpoint);
      }
    }

    // Create a new checkpoint except for the last checkpoint. Do not create a new checkpoint if there was an interruption in the last checkpoint.
    if (checkpoint.next.length > 0 && !interruptionInLastCheckpoint) {
      const newCheckpoint = createAppCheckpoint(checkpoint);
      appCheckpoints.push(newCheckpoint);
      onCheckpointStart?.(newCheckpoint);
    }
  }

  function createAppCheckpoint(checkpoint: Checkpoint<TAgentState, TInterruptValue>): AppCheckpoint<TAgentState, TInterruptValue> {
    return {
      nodes: checkpoint.next.map((x, index) => {
        const matchingKey = Object.keys(checkpoint.metadata?.writes ?? {}).find(key => key === x);
        const value = matchingKey ? checkpoint.metadata?.writes?.[matchingKey] : undefined;
        return {
          name: x,
          state: matchingKey
            ? Array.isArray(value)
              ? deepCopy((value as Partial<TAgentState>[])[index] as TAgentState)
              : deepCopy(value as TAgentState)
            : {} as TAgentState
        };
      }),
      stateInitial: deepCopy(checkpoint.values),
      state: deepCopy(checkpoint.values),
      stateDiff: {} as TAgentState,
      checkpointConfig: checkpoint.config,
      error: false
    };
  }

  function updateGraphNodeStateFromMetadata(appCheckpoint: AppCheckpoint<TAgentState, TInterruptValue>, checkpoint: Checkpoint<TAgentState, TInterruptValue>) {
    // Update nodes states with the writes from the checkpoint metadata
    Object.entries(checkpoint.metadata?.writes ?? {}).forEach(([key, value]) => {
      const matchingNodes = appCheckpoint.nodes.filter(node => node.name === key);
      matchingNodes.forEach((node, index) => {
        node.state = Array.isArray(value)
          ? deepCopy((value as Partial<TAgentState>[])[index] as TAgentState)
          : deepCopy(value as TAgentState);
      });
    });
  }

  function processMessageChunk(nodeMessageChunk: NodeMessageChunk, currentMessages: Message[]) {
    if (!nodeMessageChunk?.message_chunk?.id) return;
    
    const chunkId = nodeMessageChunk.message_chunk.id;
    const chunkContent = nodeMessageChunk.message_chunk.content || '';
    const chunkToolCalls = nodeMessageChunk.message_chunk.tool_call_chunks;
    
    const existingMsgIndex = currentMessages.findIndex(m => m.id === chunkId);

    if (existingMsgIndex !== -1) {
      // Update existing message
      currentMessages[existingMsgIndex].content += chunkContent;
      
      // Process tool call chunks if available
      if (chunkToolCalls?.length > 0) {
        // Update or add tool calls
        if (!currentMessages[existingMsgIndex].tool_calls) {
          currentMessages[existingMsgIndex].tool_calls = [];
        }
        
        // For each tool call chunk, find matching tool call or create new one
        chunkToolCalls.forEach(toolCallChunk => {
          if (!toolCallChunk.id) return;
          
          const existingToolCallIndex = currentMessages[existingMsgIndex].tool_calls?.findIndex(
            tc => tc.id === toolCallChunk.id
          );
          
          if (existingToolCallIndex !== -1 && currentMessages[existingMsgIndex].tool_calls) {
            // Update existing tool call
            const toolCall = currentMessages[existingMsgIndex].tool_calls![existingToolCallIndex];
            if (toolCallChunk.name) toolCall.name = toolCallChunk.name;
            
            // Append arguments (typically JSON string)
            if (toolCallChunk.args) {
              if (!toolCall.args) toolCall.args = {};
              try {
                const argsObj = typeof toolCallChunk.args === 'string' 
                  ? JSON.parse(toolCallChunk.args)
                  : toolCallChunk.args;
                toolCall.args = { ...toolCall.args, ...argsObj };
              } catch (e) {
                console.error("Error parsing tool call args:", e);
                // If parsing fails, store as raw string
                toolCall.args = toolCallChunk.args;
              }
            }
          } else if (currentMessages[existingMsgIndex].tool_calls) {
            // Create new tool call
            currentMessages[existingMsgIndex].tool_calls.push({
              id: toolCallChunk.id,
              name: toolCallChunk.name || '',
              args: toolCallChunk.args || {}
            });
          }
        });
      }
      
      // Update node-specific messages
      if (nodeMessageChunk.node_name) {
        // This is handled by the checkpoint update, not needed here
      }
    } else {
      // Create new message
      const toolCalls: ToolCall[] = [];
      
      // Initialize tool calls if present in the chunk
      if (chunkToolCalls?.length > 0) {
        chunkToolCalls.forEach(tc => {
          if (tc.id && tc.name) {
            toolCalls.push({
              id: tc.id,
              name: tc.name,
              args: tc.args || {}
            });
          }
        });
      }
      
      const newMessage: Message = {
        type: "ai",
        content: chunkContent,
        id: chunkId,
        tool_calls: toolCalls.length > 0 ? toolCalls : undefined
      };
      
      if (nodeMessageChunk.node_name) {
        newMessage.name = nodeMessageChunk.node_name;
      }
      
      currentMessages.push(newMessage);
    }
  }

  function processCustomEvent(state: Partial<TAgentState>, appCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[]) {
    if (appCheckpoints.length === 0) {
      return;
    }

    // Update the last checkpoint state. Update only the properties that are in the custom event.
    const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
    lastCheckpoint.state = deepCopy({ ...lastCheckpoint.state, ...state }) as TAgentState;

    // Update all child nodes with the same partial state
    lastCheckpoint.nodes.forEach(node => {
      node.state = deepCopy({ ...node.state, ...state }) as TAgentState;
    });

    onCheckpointStateUpdate?.(lastCheckpoint);
  }

  function processInterrupts(interrupts: Interrupt<TInterruptValue>[], appCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[]) {
    if (appCheckpoints.length === 0) {
      return;
    }

    const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
    lastCheckpoint.interruptValue = interrupts[0].value; // handle only single interrupt for now
  }

  function processError(appCheckpoints: AppCheckpoint<TAgentState, TInterruptValue>[]) {
    if (appCheckpoints.length === 0) {
      return;
    }

    const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
    lastCheckpoint.error = true;
  }

  function getStateDiff(stateOld: TAgentState, stateNew: TAgentState): TAgentState {
    const diff = {} as TAgentState;

    // Get all keys from old state (structure should be the same in both states)
    const keys = Object.keys(stateOld);

    for (const key of keys) {
      const oldValue = (stateOld as any)[key];
      const newValue = (stateNew as any)[key];

      // Handle arrays - only include new items
      if (Array.isArray(oldValue)) {
        const newItems = newValue.filter((newItem: any) =>
          !oldValue.some((oldItem: any) =>
            JSON.stringify(oldItem) === JSON.stringify(newItem)
          )
        );
        (diff as any)[key] = newItems.length > 0 ? deepCopy(newItems) : [];
        continue;
      }

      // For objects, recursively compute diff
      if (typeof oldValue === 'object' && oldValue !== null) {
        (diff as any)[key] = getStateDiff(oldValue, newValue);
      }
      // For primitive values, include both changed and unchanged
      else {
        (diff as any)[key] = newValue;
      }
    }

    return diff;
  }

  function deepCopy<T>(obj: T): T {
    if (obj === null || typeof obj !== 'object') { 
      return obj; 
    }
    try { 
      return JSON.parse(JSON.stringify(obj)); 
    } catch (e) { 
      console.error("Deep copy failed:", e); 
      return obj; 
    }
  }

  return { 
    status, 
    appCheckpoints, 
    run, 
    resume, 
    fork, 
    replay, 
    restore, 
    stop, 
    restoring,
    restoreError,
    messages,
    progressUpdates
  };
}
