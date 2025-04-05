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
      {Object.entries(updates).map(([id, data]) => {
        // Calculate progress percentage - use completedSteps and totalSteps (if available) or default progress value
        const progressValue = data.completedSteps && data.totalSteps
          ? (data.completedSteps / data.totalSteps) * 100
          : data.progress ? data.progress * 100 : 0;
        
        return (
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
              <span className="text-xs text-muted-foreground">
                {data.completedSteps && data.totalSteps 
                  ? `${data.completedSteps}/${data.totalSteps}` 
                  : `${Math.round(progressValue)}%`}
              </span>
            </div>
            <Progress value={progressValue} className="h-1" />
            {data.message && (
              <p className="text-xs text-muted-foreground mt-1">{data.message}</p>
            )}
            {/* Display query result count (if available) */}
            {data.results && data.results.length > 0 && (
              <div className="mt-2 text-xs">
                <span className="font-medium">Results: </span>
                <span className="text-muted-foreground">{data.results.length} items</span>
              </div>
            )}
          </div>
        );
      })}
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

  // State to prevent triggering run multiple times
  const [initialRunAttempted, setInitialRunAttempted] = useState(false);
  // Optional: State to indicate specific startup error
  const [startupError, setStartupError] = useState<string | null>(null);


  const {
      status,
      run, // We need the run function from the hook
      restore,
      stop,
      restoring,
      restoreError,
      messages,
      progressUpdates,
      appCheckpoints
      // Add interrupt state/handlers if needed: isInterrupted, interruptData, resume
  } = useLangGraphAgent<DeepResearchState, any, any>({ // Pass generics if needed
       // Add callbacks if used, e.g., onCheckpointEnd
  });

  // ... (useMemo for finalReport, useMemo for researchTopic, useRef for messagesEndRef) ...
   const researchTopic = useMemo(() => {
       // Logic to get topic from messages remains useful for display
       return messages?.[0]?.type === 'user' && typeof messages[0].content === 'string'
           ? messages[0].content
           : null;
   }, [messages]);
   const messagesEndRef = useRef<HTMLDivElement>(null);


  // Restore history AND trigger initial run if necessary
  useEffect(() => {
    // Guard: Only proceed if we have a threadId and haven't tried the initial run/restore check yet.
    if (!threadId || initialRunAttempted) {
        return;
    }

    setStartupError(null); // Clear previous startup error on new attempt
    console.log("Effect: Starting restore/initial run check for thread:", threadId);

    restore(threadId)
        .then((restoredCheckpoints) => {
            console.log("Effect: Restore promise resolved.");
            const hasMeaningfulHistory = restoredCheckpoints && restoredCheckpoints.length > 1;

            // --- Logic to potentially trigger run ---
            if (!hasMeaningfulHistory && !restoreError) {
                console.log("Effect: Thread appears new based on checkpoints. Checking for topic...");
                const initialTopic = sessionStorage.getItem(`topic_for_${threadId}`);
                sessionStorage.removeItem(`topic_for_${threadId}`);

                if (initialTopic) {
                    console.log(`Effect: Found initial topic: "${initialTopic}". Triggering run...`);
                    const initialMessages: Message[] = [{ type: 'user', content: initialTopic, id: `user-${crypto.randomUUID()}` }];
                    const initialState: DeepResearchState = { messages: initialMessages };

                    run({ thread_id: threadId, state: initialState, agent: "deep_research" })
                        .then(() => {
                            console.log("Initial run command sent successfully.");
                            setInitialRunAttempted(true); // Set attempt complete on success
                        })
                        .catch(runError => {
                            console.error("Error detail from initial run call:", runError);
                            let detail = runError instanceof Error ? runError.message : 'Unknown error';
                            setStartupError(`Failed to start research: ${detail}`);
                            setInitialRunAttempted(true); // Also set attempt complete on failure
                        });
                } else {
                    console.warn("Effect: Thread appears new, but no initial topic found.");
                    setStartupError("Cannot start research: Initial topic is missing.");
                    setInitialRunAttempted(true); // Set attempt complete as we can't proceed
                }
            } else {
                 // Existing thread or restore error occurred
                 console.log("Effect: Existing thread or restore error.");
                 setInitialRunAttempted(true); // Mark attempt complete
                 sessionStorage.removeItem(`topic_for_${threadId}`); // Clean up just in case
            }
            // --- End run trigger logic ---
        })
        .catch((err) => {
            console.error("Effect: Unhandled error during restore promise chain:", err);
             setInitialRunAttempted(true); // Mark attempt complete on unexpected error
             if (!restoreError) {
                setStartupError("An unexpected error occurred during loading.")
             }
        });

// ***** ENSURE THIS DEPENDENCY ARRAY IS USED *****
}, [threadId, restore, run, initialRunAttempted, restoreError]);
// ***** DEPENDENCY ARRAY HAS 5 ITEMS AND IS STABLE *****


  // Auto-scroll effect (remains the same)
  useEffect(() => {
       messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progressUpdates]);


  // Stop research handler (remains the same)
  const handleStopResearch = useCallback(() => {
       if (threadId && status === 'running') {
         stop(threadId);
       }
  }, [threadId, status, stop]);

// --- THIS DEFINITION MUST EXIST BEFORE THE RETURN STATEMENT ---
const finalReport = useMemo(() => {
  // Defensive checks first
  if (!appCheckpoints || !Array.isArray(appCheckpoints) || appCheckpoints.length === 0) {
       return null;
  }
  const lastCheckpoint = appCheckpoints[appCheckpoints.length - 1];
  if (!lastCheckpoint || !lastCheckpoint.state) { // Check if lastCheckpoint and its state exist
      return null;
  }

  // Try to get the specific field from state
  let report = (lastCheckpoint.state as DeepResearchState)?.final_report_markdown;

  // Fallback to last AI message if report not found and it's the end of the graph
  if (!report && lastCheckpoint.next?.length === 0 && messages && messages.length > 0) {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.type === 'ai' && typeof lastMsg.content === 'string') {
      console.log("Using last AI message as final report (fallback).");
      report = lastMsg.content;
    }
  }

  return report ?? null; // Return the found report or null
}, [appCheckpoints, messages]); // Dependencies are correct

  // --- Render Logic ---
  // (Includes checks for restoring, restoreError, startupError,
  //  and then displays messages, progress, report, interrupt UI etc.)
  return (
      <div className="flex flex-col h-screen p-2 md:p-4 bg-background text-foreground">
          <h1 className="text-xl md:text-2xl font-semibold mb-2 md:mb-4 text-center flex-shrink-0">
              Deep Research Assistant
              {researchTopic && !restoring && (
                  <span className="block text-sm text-muted-foreground font-normal mt-1">
                    Topic: {researchTopic}
                  </span>
              )}
          </h1>

          <div className="flex-1 overflow-hidden flex flex-col">
              <div className="flex flex-col gap-4 flex-1 min-h-0">
                  <div className="h-full flex flex-col border rounded-lg shadow-sm bg-card">
                      {/* Header with Status Indicator */}
                      <div className="p-2 border-b flex justify-between items-center flex-shrink-0">
                         {/* ... (Status display logic - same as before) ... */}
                           <h2 className="text-base md:text-lg font-semibold">
                               {researchTopic ? `Research: ${researchTopic.substring(0,30)}...` : "Research Progress"}
                          </h2>
                          <div className="text-xs text-muted-foreground flex items-center gap-1">
                             {/* ... (Status/Error/Stop Button display logic - same as before) ... */}
                          </div>
                      </div>

                      {/* Content Area */}
                      <div className="flex-1 overflow-y-auto p-2 space-y-4" id="messages-container">
                          {restoring ? (
                              <div className="flex justify-center items-center h-full text-muted-foreground">
                                  <Loader className="mr-2 h-4 w-4 animate-spin" /> Loading History...
                              </div>
                          ) : restoreError ? (
                              <div className="flex flex-col justify-center items-center h-full text-red-500 text-center p-4">
                                 <AlertTriangle className="mr-2 h-5 w-5 mb-2" />
                                 <p className="font-semibold">Failed to Load Research History</p>
                                 <p className="text-sm">{restoreError.message || 'An unknown error occurred.'}</p>
                             </div>
                          // Display specific startup error if restore was ok but topic was missing
                          ) : startupError ? (
                               <div className="flex flex-col justify-center items-center h-full text-orange-500 text-center p-4">
                                 <AlertTriangle className="mr-2 h-5 w-5 mb-2" />
                                 <p className="font-semibold">Cannot Start Research</p>
                                 <p className="text-sm">{startupError}</p>
                               </div>
                          ) : (
                              <>
                                  {/* Display content only when no critical errors */}
                                  <DeepResearchProgressDisplay updates={progressUpdates} />
                                  <MessageHistoryDisplay messages={messages} />
                                  {finalReport && (
                                      <div className="mt-6 border-t pt-4">
                                          <h2 className="text-base md:text-lg font-semibold mb-2">Final Report</h2>
                                          <FinalReportDisplay report={finalReport} />
                                      </div>
                                  )}
                                  {/* Message if idle/complete but nothing substantial found */}
                                   {status === 'idle' && messages.length === 0 && !finalReport && (!appCheckpoints || appCheckpoints.length === 0) && (
                                       <div className="text-center text-muted-foreground py-6">
                                         Waiting for research to start or no history found.
                                       </div>
                                   )}
                              </>
                          )}
                          {/* --- End Conditional Content --- */}
                          <div ref={messagesEndRef} />
                      </div>
                       {/* --- Human-in-the-Loop UI (Render based on hook state) --- */}
                      {/* {isInterrupted && interruptData && ( ... UI to call resume ... )} */}
                  </div>
              </div>
          </div>
      </div>
  );
}