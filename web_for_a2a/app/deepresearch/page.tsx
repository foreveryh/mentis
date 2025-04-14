// 文件路径: mentis/web_for_a2a/app/deepresearch/page.tsx
'use client'; // 标记为客户端组件

import { useState, useCallback, useRef, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';

// --- A2A 类型定义 (简化版) ---
interface TextPart { type: "text"; text: string; }
interface DataPart { type: "data"; data: Record<string, any>; }
type Part = TextPart | DataPart;
interface Message { role: "user" | "agent"; parts: Part[]; }
// 使用字符串类型来匹配 TaskState 枚举值
type TaskStateString = "submitted" | "working" | "input-required" | "completed" | "canceled" | "failed" | "unknown";
interface TaskStatus { state: TaskStateString | string; message?: Message; } // 允许 string 以防万一
interface Artifact { parts: Part[]; index?: number; /* 其他可选字段 */ }
interface TaskStatusUpdateEvent { id: string; status: TaskStatus; final: boolean; }
interface TaskArtifactUpdateEvent { id:string; artifact: Artifact; final?: boolean; }
type StreamEventResult = TaskStatusUpdateEvent | TaskArtifactUpdateEvent;
interface JSONRPCError { code: number; message: string; data?: any; }
interface SendTaskStreamingResponse {
    jsonrpc?: "2.0";
    id?: string | number | null;
    result?: StreamEventResult;
    error?: JSONRPCError;
}
// --- 类型定义结束 ---

const A2A_SERVER_URL = process.env.NEXT_PUBLIC_A2A_SERVER_URL || 'http://127.0.0.1:8000';

export default function DeepResearchPage() {
  // --- 状态管理 ---
  const [status, setStatus] = useState<'idle' | 'streaming' | 'completed' | 'error' | 'aborted'>('idle');
  const [streamedContent, setStreamedContent] = useState<StreamEventResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [finalReport, setFinalReport] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // --- 清理函数 ---
  useEffect(() => {
    return () => {
      console.log("组件卸载，中止进行中的 fetch 请求...");
      abortControllerRef.current?.abort();
    };
  }, []);

  // --- 核心：启动流式请求并处理 (保持不变) ---
  const startStream = useCallback(async () => {
    console.log("[startStream] Initiating stream...");
    setStatus('streaming'); setError(null); setStreamedContent([]); setFinalReport(null);
    if (abortControllerRef.current) { abortControllerRef.current.abort(); }
    abortControllerRef.current = new AbortController(); const signal = abortControllerRef.current.signal;
    const taskId = "webui_deep_research_" + uuidv4();
    const research_topic = "特斯拉电动汽车的市场分析和未来发展趋势";
    const message: Message = { role: "user", parts: [{ type: "text", text: research_topic }] };
    const payload = { id: taskId, sessionId: "webui_session_" + uuidv4(), message: message, acceptedOutputModes: ["text"], metadata: { skill_name: "deep_research" } };
    const requestBody = { jsonrpc: "2.0", method: "tasks/sendSubscribe", id: "req-" + taskId, params: payload };

    try {
      console.log("[startStream] Sending request:", JSON.stringify(requestBody, null, 2));
      const response = await fetch(A2A_SERVER_URL, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' }, body: JSON.stringify(requestBody), signal: signal });
      console.log(`[startStream] Initial response status: ${response.status}`);
      console.log("[startStream] Received Response Headers:"); response.headers.forEach((value, key) => { console.log(`  ${key}: ${value}`); });
      const corsHeader = response.headers.get("access-control-allow-origin"); console.log(`[startStream] Access-Control-Allow-Origin Header value: ${corsHeader}`);
      if (!response.ok) { let errorMsg = `HTTP error! status: ${response.status}`; try { const errJson = await response.json(); errorMsg = errJson?.error?.message || JSON.stringify(errJson); } catch { errorMsg = `${response.status} ${response.statusText}`; } throw new Error(errorMsg); }
      const contentType = response.headers.get('content-type'); console.log(`[startStream] Initial response Content-Type: ${contentType}`);
      if (!contentType || !contentType.includes('text/event-stream')) { let errorMsg = `Expected Content-Type 'text/event-stream', but got '${contentType}'`; try { const errBody = await response.text(); errorMsg += ` - Body: ${errBody}`; } catch {} throw new Error(errorMsg); }
      const reader = response.body?.getReader(); if (!reader) throw new Error('Failed to get response body reader');
      console.log("[startStream] Got reader, starting stream processing...");
      await processStream(reader); // 调用修正后的 processStream
      setStatus(prevStatus => { if (prevStatus === 'streaming') { console.log("[startStream] Stream processing finished without error/final flag, setting status to completed."); return 'completed'; } console.log("[startStream] Stream processing finished, keeping status:", prevStatus); return prevStatus; });
    } catch (err: any) {
      if (err.name === 'AbortError') { console.log('[startStream] Stream fetch aborted by client.'); setStatus(prevStatus => { if (prevStatus === 'streaming') { setError('请求已中止'); return 'aborted'; } return prevStatus; }); }
      else { console.error("[startStream] Error during request setup or connection:", err); setError(`请求或连接失败: ${err.message}`); setStatus('error'); }
    } finally { console.log("[startStream] Cleaning up AbortController."); abortControllerRef.current = null; }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- *** 核心修改：processStream 函数 *** ---
  const processStream = async (reader: ReadableStreamDefaultReader<Uint8Array>) => {
    const decoder = new TextDecoder();
    let buffer = '';
    let streamEndedInLoop = false;

    console.log("[processStream] Starting stream processing loop.");

    while (!streamEndedInLoop) {
      try {
         console.log("[processStream] Waiting for reader.read()...");
         const { done, value } = await reader.read();
         console.log(`[processStream] reader.read() returned: done=${done}, value size=${value?.length}`);

         if (done) {
             console.log("[processStream] Stream finished by reader (done=true).");
             streamEndedInLoop = true;
             break; // 显式跳出 while 循环
         }

         buffer += decoder.decode(value, { stream: true });
         console.log(`[processStream] Decoded chunk, current buffer size: ${buffer.length}`); // 打印 buffer 大小

         // --- 使用正则表达式分割 SSE 事件，更健壮 ---
         // SSE 事件由两个换行符分隔 (\n\n, \r\r, or \r\n\r\n)
         const eventSeparatorRegex = /\r\n\r\n|\n\n|\r\r/;
         let match;

         // 循环处理 buffer 中的所有完整事件
         while ((match = eventSeparatorRegex.exec(buffer)) !== null) {
             const boundaryIndex = match.index;
             const eventString = buffer.substring(0, boundaryIndex); // 提取事件部分
             buffer = buffer.substring(boundaryIndex + match[0].length); // 移除已处理的事件和分隔符

             if (!eventString.trim()) {
                 console.log("[processStream] Skipping empty event string found by regex.");
                 continue; // 跳过空事件
             }

             console.log('[processStream] Processing raw SSE message:', eventString.replace(/\n/g, '\\n'));

             // SSE 事件通常包含多行 (event:, id:, data:, retry:)
             // 我们主要关心 data: 行
             const lines = eventString.split(/\r\n|\n|\r/); // 按行分割
             let eventType = 'message'; // 默认事件类型
             let eventDataString = '';
             let eventId = '';

             for (const line of lines) {
                 if (line.startsWith('event:')) {
                     eventType = line.substring(6).trim();
                 } else if (line.startsWith('data:')) {
                     // 如果 data 有多行，需要拼接
                     eventDataString += line.substring(5).trim() + "\n"; // 加换行符以区分多行 data
                 } else if (line.startsWith('id:')) {
                     eventId = line.substring(3).trim();
                 } // 可以添加对 retry: 的处理
             }
             eventDataString = eventDataString.trim(); // 移除末尾的换行符

             // 只处理我们关心的包含有效数据的事件
             if (eventDataString) {
                 console.log(`[processStream] Extracted SSE fields: type=${eventType}, id=${eventId}, data=${eventDataString}`);

                 try {
                     const eventResponse = JSON.parse(eventDataString) as SendTaskStreamingResponse;
                     console.log('[processStream] Successfully parsed JSON:', eventResponse);

                     if (eventResponse.error) {
                         const error = eventResponse.error; console.error("[processStream] Received SSE Error from server:", error);
                         setError(`流式错误 (来自服务器): Code=${error.code}, Msg=${error.message}`); setStatus('error');
                         streamEndedInLoop = true; break; // Exit inner processing loop
                     }
                     const eventData = eventResponse.result;
                     if (eventData) {
                         console.log("[processStream] Preparing to call setStreamedContent with:", eventData);
                         setStreamedContent(prev => [...prev, eventData]); // Update state
                         console.log("[processStream] Call to setStreamedContent completed.");

                         if (eventData.final === true) {
                             console.log("[processStream] Final event flag received. Setting status to completed.");
                             streamEndedInLoop = true; setStatus('completed');
                             // Let the inner loop finish processing this chunk, outer loop will break
                         } else {
                             setStatus(prevStatus => (prevStatus !== 'completed' && prevStatus !== 'error' && prevStatus !== 'aborted') ? 'streaming' : prevStatus);
                         }
                     } else { console.log("[processStream] Skipping event with no result data."); }
                 } catch (e: any) {
                     console.error("[processStream] Failed to parse SSE JSON data:", e, "\nRaw JSON string was:", eventDataString);
                     setError(`解析服务器事件失败: ${e.message}. 收到的数据 (部分): ${eventDataString.substring(0, 150)}...`); setStatus('error');
                     streamEndedInLoop = true; break; // Exit inner processing loop
                 }
             } else {
                 console.log("[processStream] Skipping SSE message with no data field.");
             }
              if (streamEndedInLoop) break; // Exit inner processing loop if needed
         } // end while match = regex.exec(buffer)

          if(streamEndedInLoop) break; // Exit outer while if needed

      } catch (readError: any) {
           console.error("[processStream] Error reading from stream:", readError);
           if (readError.name !== 'AbortError') { setError(`读取流错误: ${readError.message}`); setStatus('error'); }
           else { console.log("[processStream] Stream reading aborted by client."); setStatus('aborted'); }
           streamEndedInLoop = true; break; // Exit outer while
      }
    } // end while (!streamEndedInLoop)
    console.log("[processStream] Exited stream processing loop.");
  }; // end processStream

  // --- useEffect 处理最终报告 (保持不变) ---
  useEffect(() => {
    if (status === 'completed' && streamedContent.length > 0) {
      console.log("[useEffect] Status is completed, processing final report from streamedContent.");
      const finalArtifactEvent = [...streamedContent].reverse().find(ev => ev && 'artifact' in ev) as TaskArtifactUpdateEvent | undefined;
      if (finalArtifactEvent?.artifact?.parts) {
        const reportPart = finalArtifactEvent.artifact.parts.find(p => p.type === 'text') as TextPart | undefined;
        if (reportPart) { console.log("[useEffect] Found final report text in artifact."); setFinalReport(reportPart.text); }
        else { console.log("[useEffect] Completed, but no text part found in final artifact event."); }
      } else {
           console.log("[useEffect] Completed, but no artifact event found or artifact has no parts.");
           const lastStatusEvent = [...streamedContent].reverse().find(ev => ev && 'status' in ev) as TaskStatusUpdateEvent | undefined;
           if (lastStatusEvent?.status?.message?.parts) {
                const reportPart = lastStatusEvent.status.message.parts.find(p => p.type === 'text') as TextPart | undefined;
                 if (reportPart) { console.warn("[useEffect] No artifact found, using text from last status update as final report (fallback)."); setFinalReport(reportPart.text); }
           }
      }
    }
  }, [status, streamedContent]);

  // --- UI 渲染 (保持不变) ---
  return (
    <div className="container mx-auto p-4 font-sans">
      {/* ... (JSX 代码同上一版本) ... */}
      <h1 className="text-2xl font-bold mb-4">DeepResearch A2A 流式客户端 (带调试日志 v2)</h1>
      <button onClick={startStream} disabled={status === 'streaming'} className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-400">
        {status === 'streaming' ? '研究进行中...' : '开始流式研究 (特斯拉主题)'}
      </button>
      <div className="mt-4">
        <p><strong>当前状态:</strong> <span className={`font-semibold ${status === 'error' ? 'text-red-500' : status === 'completed' ? 'text-green-600': status === 'aborted' ? 'text-yellow-700' : 'text-blue-600'}`}>{status}</span></p>
        {error && <p className="text-red-500 mt-2"><strong>错误:</strong> {error}</p>}
      </div>
      <h2 className="text-xl font-semibold mt-6 mb-2">流式内容输出:</h2>
      <div className="stream-output p-4 border rounded bg-gray-100 min-h-[200px] max-h-[500px] overflow-y-auto text-sm font-mono">
        {streamedContent.length === 0 && status !== 'streaming' && status !== 'error' && status !== 'aborted' && <p className="text-gray-500">尚未接收到流式内容。</p>}
        {streamedContent.map((eventData, index) => {
          let displayContent: React.ReactNode = null; let parts: Part[] | undefined = undefined;
          if (eventData && 'status' in eventData && eventData.status?.message?.parts) { parts = eventData.status.message.parts; displayContent = <span className="text-blue-700">[状态更新]</span>; }
          else if (eventData && 'artifact' in eventData && eventData.artifact?.parts) { parts = eventData.artifact.parts; displayContent = <span className="text-green-700">[收到报告片段]</span>; }
          if (parts) { displayContent = (<>{displayContent}{" "}{parts.map((part, pIdx) => { if (part.type === 'text') {return <span key={pIdx}>{part.text}</span>;} else if (part.type === 'data') {return <pre key={pIdx} className="text-xs bg-gray-200 p-1 my-1 rounded overflow-x-auto">{JSON.stringify(part.data, null, 2)}</pre>;} return null; })}</>); }
          else if (typeof eventData === 'object' && eventData !== null) { displayContent = <pre className="text-xs text-gray-500">{JSON.stringify(eventData, null, 2)}</pre>; }
          else { displayContent = <span className="text-xs text-red-500">未知事件: {String(eventData)}</span>;}
          return <div key={index} className="py-1 border-b border-gray-300">{displayContent}</div>;
        })}
        {status === 'streaming' && <p className="text-gray-500 mt-2 animate-pulse">等待服务器事件...</p>}
        {status === 'completed' && !finalReport && <p className="text-yellow-600 font-bold mt-2">流处理完成，但未找到最终报告 Artifact。</p>}
        {status === 'error' && <p className="text-red-700 font-bold mt-2">流处理因错误终止。</p>}
        {status === 'aborted' && <p className="text-yellow-700 font-bold mt-2">流处理已中止。</p>}
      </div>
       {finalReport && (
            <>
                <h2 className="text-xl font-semibold mt-6 mb-2">最终报告:</h2>
                <div className="final-report p-4 border rounded bg-white prose max-w-none"> <pre className="whitespace-pre-wrap text-sm">{finalReport}</pre> </div>
                {status === 'completed' && <p className="text-green-700 font-bold mt-2">任务已成功完成。</p>}
            </>
       )}
    </div>
  );
}