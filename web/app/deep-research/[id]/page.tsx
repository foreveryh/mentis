'use client'; 

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams } from 'next/navigation';
import { v4 as uuidv4 } from 'uuid';
import { Button } from '@/components/ui/button'; 
import { Textarea } from "@/components/ui/textarea"; 
import { ArrowUp, Square, Loader, AlertTriangle, Check } from "lucide-react"; 
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"; 
import { Progress } from "@/components/ui/progress"; 

// Import hook and types
import { useLangGraphAgent } from '@/hooks/useLangGraphAgent/useLangGraphAgent';
import { 
  StreamUpdateData, 
  Message, 
  ToolCall, 
  WithMessages, 
  AppCheckpoint 
} from '@/hooks/useLangGraphAgent/types';

// Markdown renderer
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Deep Research State interface
interface DeepResearchState extends WithMessages { 
  topic?: string; 
  depth?: string;
  final_report_markdown?: string | null; 
}

// Progress display component
function DeepResearchProgressDisplay({ updates }: { updates: Record<string, StreamUpdateData> }) {
  if (Object.keys(updates).length === 0) return null;

  return (
    <div className="space-y-3">
      {Object.entries(updates).map(([id, data]) => (
        <div key={id} className="border rounded-md p-3 bg-muted/20">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center space-x-2">
              {data.status === 'completed' ? (
                <Check className="h-4 w-4 text-green-500" />
              ) : (
                <Loader className="h-4 w-4 animate-spin text-blue-500" />
              )}
              <span className="text-sm font-medium">{data.title || 'Progress'}</span>
            </div>
            <span className="text-xs text-muted-foreground">{Math.round(data.progress * 100)}%</span>
          </div>
          <Progress value={data.progress * 100} className="h-1" />
          {data.message && (
            <p className="text-xs text-muted-foreground mt-1">{data.message}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// Message history display component
function MessageHistoryDisplay({ messages }: { messages: Message[] }) {
  if (messages.length === 0) return null;
  
  return (
    <div className="space-y-4">
      {messages.map((message) => (
        <div 
          key={message.id} 
          className={`p-3 rounded-lg ${
            message.type === 'user' 
              ? 'bg-primary/10 border border-primary/20' 
              : 'bg-card'
          }`}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              message.type === 'user' 
                ? 'bg-primary/20 text-primary' 
                : 'bg-secondary/20 text-secondary'
            }`}>
              {message.name || message.type}
            </span>
          </div>
          
          <div className="prose prose-sm dark:prose-invert max-w-none">
            {message.content && (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            )}
            
            {message.tool_calls?.map((tool) => (
              <div key={tool.id} className="bg-muted/30 p-2 rounded-md mt-2 text-xs font-mono">
                <div className="font-semibold">{tool.name}</div>
                <pre className="overflow-x-auto p-1 mt-1">
                  {typeof tool.args === 'string' 
                    ? tool.args 
                    : JSON.stringify(tool.args, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// Final report display component
function FinalReportDisplay({ report }: { report: string | null }) {
  if (!report) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <p>No report generated yet</p>
      </div>
    );
  }

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {report}
      </ReactMarkdown>
    </div>
  );
}

export default function DeepResearchPage() {
  const params = useParams<{ id: string }>();
  const threadId = params.id; 

  const [topic, setTopic] = useState<string>('');

  // Use the hook with DeepResearchState type
  const { 
    status, 
    run, 
    restore, 
    stop, 
    restoring, 
    restoreError,
    messages,
    progressUpdates,
    appCheckpoints
  } = useLangGraphAgent<DeepResearchState, any, any>({
    onCheckpointEnd: (checkpoint) => {
      console.log('Deep Research Checkpoint ended:', checkpoint.checkpointId);
    },
  });

  // Derive final report from the latest checkpoint
  const finalReport = useMemo(() => {
    if (!appCheckpoints || appCheckpoints.length === 0) return null;
    
    // Get the last checkpoint
    const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
    
    // Try to get final_report_markdown from state
    let report = (lastCheckpoint.state as DeepResearchState)?.final_report_markdown;
    
    // If no report in state and this is the last checkpoint (next is empty)
    // try to use the last AI message as the report
    if (!report && lastCheckpoint.next.length === 0 && messages.length > 0) {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg.type === 'ai' && typeof lastMsg.content === 'string') {
        console.log("Using last AI message as final report (fallback).");
        report = lastMsg.content;
      }
    }
    
    return report ?? null;
  }, [appCheckpoints, messages]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Restore history effect
  useEffect(() => {
    if (threadId) {
      console.log("Restoring history for thread:", threadId);
      restore(threadId)
        .then((restoredCheckpoints) => {
          if (restoredCheckpoints && restoredCheckpoints.length > 0) {
            // Extract topic from the first user message if available
            const firstMsg = restoredCheckpoints[0]?.state?.messages?.[0];
            if (firstMsg?.type === 'user' && typeof firstMsg.content === 'string') {
              setTopic(firstMsg.content);
            }
          }
        })
        .catch((err) => console.error("Error restoring:", err));
    }
  }, [threadId, restore]);

  // Auto-scroll effect
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progressUpdates]);

  // Run research handler
  const handleRunResearch = useCallback(() => {
    if (!topic.trim() || !threadId || status === 'running' || restoring) return;
    
    console.log(`Running Deep Research for topic: ${topic}, thread: ${threadId}`);
    
    // Prepare initial message
    const initialMessages: Message[] = [{ 
      type: 'user', 
      content: topic, 
      id: `user-${uuidv4()}` 
    }];
    
    // Prepare initial state with messages
    const initialState = { messages: initialMessages };
    
    // Call the run method
    run({ 
      thread_id: threadId, 
      state: initialState as DeepResearchState, 
      agent: "deep_research"
    });
  }, [topic, threadId, status, restoring, run]);

  // Stop research handler
  const handleStopResearch = useCallback(() => {
    if (threadId && status === 'running') stop(threadId);
  }, [threadId, status, stop]);

  // Show topic input when there are no messages and not running/restoring
  const showTopicInput = messages.length === 0 && status === 'idle' && !restoring;

  return (
    <div className="flex flex-col h-screen p-2 md:p-4 bg-background text-foreground">
      <h1 className="text-xl md:text-2xl font-semibold mb-2 md:mb-4 text-center flex-shrink-0">
        Deep Research Assistant
      </h1>

      <div className="flex-1 overflow-hidden flex flex-col"> 
        {showTopicInput ? (
          // Topic input interface
          <div className="flex flex-col items-center justify-center h-full w-full">
            <Card className="w-full max-w-2xl shadow-lg">
              <CardHeader>
                <CardTitle>Start New Research</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground mb-4">
                  Enter a topic to research in depth
                </p>
                <Textarea 
                  value={topic} 
                  onChange={(e) => setTopic(e.target.value)} 
                  placeholder="Example: Quantum computing applications in medicine" 
                  className="min-h-[100px] mb-4 text-sm" 
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleRunResearch();
                    }
                  }}
                />
                <Button 
                  onClick={handleRunResearch} 
                  disabled={!topic.trim() || status === 'running' || restoring} 
                  className="w-full"
                >
                  {status === 'running' || restoring ? (
                    <>
                      <Loader className="mr-2 h-4 w-4 animate-spin" /> 
                      Researching...
                    </>
                  ) : (
                    <>Start Research</>
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>
        ) : (
          // Research in progress/completed interface
          <div className="flex flex-col md:flex-row gap-4 flex-1 min-h-0">
            {/* Left side: Progress and messages */}
            <div className="md:w-1/2 h-full flex flex-col border rounded-lg shadow-sm bg-card">
              <div className="p-2 border-b flex justify-between items-center flex-shrink-0">
                <h2 className="text-base md:text-lg font-semibold">Execution Progress</h2>
                {/* Status Indicator */}
                <div className="text-xs text-muted-foreground flex items-center gap-1">
                  {restoring && <><Loader className="h-3 w-3 animate-spin" /> Restoring</>}
                  {status === 'running' && <><Loader className="h-3 w-3 animate-spin" /> Running</>}
                  {status === 'stopping' && <>Stopping...</>}
                  {status === 'idle' && !restoring && <>Idle</>}
                  {status === 'error' && <><AlertTriangle className="h-3 w-3 text-red-500" /> Error</>}
                  {restoreError && <><AlertTriangle className="h-3 w-3 text-red-500" /> Restore Error</>}
                  {status === 'running' && (
                    <Button 
                      variant="outline" 
                      size="sm" 
                      onClick={handleStopResearch} 
                      className="ml-2 h-6 px-2"
                    >
                      <Square className="mr-1 h-3 w-3"/> Stop
                    </Button>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-4" id="messages-container">
                {/* Display progress updates */}
                <DeepResearchProgressDisplay updates={progressUpdates} />
                {/* Display message history */}
                <MessageHistoryDisplay messages={messages} />
                <div ref={messagesEndRef} /> {/* For auto-scrolling */}
              </div>
            </div>

            {/* Right side: Final report */}
            <div className="md:w-1/2 h-full flex flex-col border rounded-lg shadow-sm bg-card">
              <h2 className="text-base md:text-lg font-semibold p-2 border-b flex-shrink-0">
                Final Report
              </h2>
              <div className="flex-1 overflow-y-auto p-2">
                <FinalReportDisplay report={finalReport} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}