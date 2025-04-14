## 前端对接 DeepResearch A2A 流式接口实现指南 (Next.js + React)

### 1. 前提

* **A2A 服务器运行中:** 确保 `super_agents/deep_research/a2a_adapter/run_server.py` 启动的服务器正在运行，并且监听地址已知（例如 `http://127.0.0.1:8000`）。
* **技术栈:** 前端使用 Next.js, React, TypeScript, Tailwind CSS。
* **核心目标:** 在 Web UI 中实时展示 DeepResearch Agent 的研究进度和最终报告。
* **A2A 类型定义:** 理想情况下，前端可以共享或重新定义 `core/a2a/types.py` 中的关键 Pydantic 模型对应的 TypeScript 接口（如 `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`, `Message`, `TextPart`, `DataPart` 等），以便在代码中获得类型检查和提示。

```typescript
// 示例 TypeScript 接口 (根据 types.py 定义)
interface TextPart {
  type: "text";
  text: string;
  metadata?: Record<string, any>;
}

interface DataPart {
  type: "data";
  data: Record<string, any>; // 结构化数据
  metadata?: Record<string, any>;
}

type Part = TextPart | DataPart; // 可以扩展 FilePart 等

interface Message {
  role: "user" | "agent";
  parts: Part[];
  metadata?: Record<string, any>;
}

interface TaskStatus {
  state: string; // TaskState 枚举值
  message?: Message;
  timestamp: string; // ISO format string
}

interface TaskStatusUpdateEvent {
  id: string; // Task ID
  status: TaskStatus;
  final: boolean;
  metadata?: Record<string, any>;
}

interface Artifact {
    name?: string;
    description?: string;
    parts: Part[];
    metadata?: Record<string, any>;
    index: number;
    append?: boolean;
    lastChunk?: boolean;
}

interface TaskArtifactUpdateEvent {
  id: string; // Task ID
  artifact: Artifact;
  final?: boolean; // Artifact 事件也可能有 final 标志
  metadata?: Record<string, any>;
}

// 流式响应中 result 字段的可能类型
type StreamEventResult = TaskStatusUpdateEvent | TaskArtifactUpdateEvent;

interface SendTaskStreamingResponse {
    jsonrpc: "2.0";
    id: string | number | null; // 对应请求的 ID
    result?: StreamEventResult;
    error?: {
        code: number;
        message: string;
        data?: any;
    };
}
```

### 2. 核心流程概述

1.  **用户输入:** 用户在 UI 中输入研究主题。
2.  **发起请求:** 前端使用 `Workspace` API 向 A2A 服务器的**主端点** (例如 `/`) 发送一个 HTTP `POST` 请求，请求体是符合 A2A 规范的 JSON-RPC 消息，`method` 为 `"tasks/sendSubscribe"`。
3.  **服务器响应:**
    * 如果请求有效且服务器成功启动后台任务并准备好 SSE 流，服务器**必须**返回一个 HTTP 200 OK 响应，且 `Content-Type` 头为 `text/event-stream`。
    * 如果请求无效或在建立流之前出错，服务器会返回一个普通的 JSON 响应（`Content-Type: application/json`），通常包含一个错误状态码（如 400 或 500）和 JSON-RPC 错误对象。
4.  **客户端处理流:**
    * 如果收到 `text/event-stream` 响应，客户端开始读取响应体 (Response Body) 中的数据流。
    * 流中的数据遵循 SSE 格式，主要是 `data: <JSON 字符串>\n\n`。
    * 客户端需要**持续读取、解码、解析**这些 SSE 事件。每个事件的 `data` 部分是一个 JSON 字符串，代表一个 `SendTaskStreamingResponse` 对象。
    * 客户端解析 `SendTaskStreamingResponse`，提取其中的 `result`（即 `TaskStatusUpdateEvent` 或 `TaskArtifactUpdateEvent`）。
    * 根据事件内容更新 UI（显示进度、最终报告）。
    * 直到收到带有 `final: true` 标志的事件或流被服务器关闭。

### 3. 技术选型: 为什么用 `Workspace` + ReadableStream 而不是 `EventSource`？

* 浏览器内置的 `EventSource` API 是处理 SSE 的标准方式，非常简洁易用。
* **但是，`EventSource` API 通常只能发起 `GET` 请求。** 而 A2A 协议规定 `tasks/sendSubscribe` 方法需要通过 `POST` 请求发送，因为需要传递包含 `message` 等信息的复杂 `params` 对象在请求体中。
* 因此，为了在**不修改标准 A2A 服务器行为**（即保持 `tasks/sendSubscribe` 为 POST）的情况下处理 SSE，我们需要使用更底层的 `Workspace` API。`Workspace` 可以发送 POST 请求，并且其返回的 `Response` 对象的 `.body` 属性是一个 `ReadableStream`，我们可以手动读取和解析这个流来处理 SSE 事件。

### 4. 实现步骤详解 (React/TypeScript 示例)

假设你在一个 React 组件（或自定义 Hook）中实现这个逻辑。

**步骤 1: 发起流式请求 (`tasks/sendSubscribe`)**

```typescript
import { useState, useCallback, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid'; // 用于生成 Task ID
// ... import 其他类型 ...

// 在你的组件或 Hook 中
const [isLoading, setIsLoading] = useState(false);
const [error, setError] = useState<string | null>(null);
const [progressUpdates, setProgressUpdates] = useState<any[]>([]); // 存储解析后的事件数据
const [finalReport, setFinalReport] = useState<string | null>(null);
const abortControllerRef = useRef<AbortController | null>(null); // 用于中止 fetch 请求

const startStreamingResearch = useCallback(async (topic: string) => {
  setIsLoading(true);
  setError(null);
  setProgressUpdates([]);
  setFinalReport(null);

  // 确保之前的请求被中止（如果需要）
  if (abortControllerRef.current) {
    abortControllerRef.current.abort();
  }
  abortControllerRef.current = new AbortController();
  const signal = abortControllerRef.current.signal;


  const taskId = "deep_research_" + uuidv4();
  const message: Message = {
    role: "user",
    parts: [{ type: "text", text: topic }],
  };
  const payload = {
    id: taskId,
    sessionId: "web_session_" + uuidv4(), // 每次可以生成新的 Session
    message: message, // 注意：实际发送时 message 可能需要 .model_dump()，但 fetch 的 body 会 JSON.stringify
    acceptedOutputModes: ["text"],
    metadata: { skill_name: "deep_research" }
  };

  const requestBody = {
    jsonrpc: "2.0",
    method: "tasks/sendSubscribe",
    id: "req-" + taskId, // 请求本身的 ID
    params: payload
  };

  try {
    const response = await fetch(`http://127.0.0.1:8000`, { // 你的 A2A 服务器地址
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream', // 明确告诉服务器期望 SSE
      },
      body: JSON.stringify(requestBody),
      signal: signal, // 允许中止请求
    });

    // 步骤 2: 处理 Fetch 响应 & 获取 ReadableStream
    if (!response.ok) {
      // 如果 HTTP 状态码不是 2xx
      let errorMsg = `HTTP error! status: ${response.status}`;
      try {
        const errorJson = await response.json(); // 尝试解析错误 JSON 体
        errorMsg = errorJson?.error?.message || errorJson.detail || JSON.stringify(errorJson);
      } catch (e) {
        // 解析 JSON 失败，使用状态文本
        errorMsg = `${response.status} ${response.statusText}`;
      }
      throw new Error(errorMsg);
    }

    const contentType = response.headers.get('content-type');
    if (!contentType || !contentType.includes('text/event-stream')) {
      // 服务器没有返回 SSE 流！
      let errorMsg = `Expected Content-Type 'text/event-stream', but got '${contentType}'`;
       try {
        const errorJson = await response.json(); // 可能是 JSONRPC 错误
        errorMsg += ` - Body: ${errorJson?.error?.message || JSON.stringify(errorJson)}`;
      } catch (e) {
         // Try reading as text if not JSON
          errorMsg += ` - Body: ${await response.text()}`;
      }
      throw new Error(errorMsg);
    }

    // 获取 ReadableStream 读取器
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Failed to get response body reader');
    }

    // 步骤 3 & 4 & 5 & 6: 读取、解析 SSE 流并更新状态
    await processStream(reader);

  } catch (err: any) {
    if (err.name === 'AbortError') {
      console.log('Fetch aborted');
      setError('请求已中止');
    } else {
      console.error("Error during streaming request:", err);
      setError(`请求失败: ${err.message}`);
    }
    setTaskStatus('IDLE'); // 或者 'FAILED'
  } finally {
    setIsLoading(false);
     abortControllerRef.current = null; // 清理 AbortController
  }
}, []); // useCallback 依赖项根据实际情况添加

// 独立的流处理函数
const processStream = async (reader: ReadableStreamDefaultReader<Uint8Array>) => {
  const decoder = new TextDecoder();
  let buffer = '';
  let streamEnded = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        console.log("Stream finished.");
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      // 按 SSE 事件分隔符处理 buffer
      const events = buffer.split('\n\n');
      buffer = events.pop() || ''; // 保留最后不完整的部分

      for (const eventString of events) {
        if (!eventString.trim()) continue; // 跳过空事件

        // 解析 SSE 消息 (data: <JSON>)
        if (eventString.startsWith('data:')) {
          const jsonData = eventString.substring(5).trim();
          try {
            const eventResponse = JSON.parse(jsonData) as SendTaskStreamingResponse;

            if (eventResponse.error) {
              const error = eventResponse.error;
              console.error("Received SSE Error:", error);
              setError(`流式错误: Code=${error.code}, Msg=${error.message}`);
              streamEnded = true; // 出现错误，通常流会中断
              break; // 停止处理此流
            }

            const eventData = eventResponse.result; // TaskStatusUpdateEvent or TaskArtifactUpdateEvent
            if (!eventData) continue;

            // 更新状态 (示例：将整个事件数据存入列表)
            setProgressUpdates(prev => [...prev, eventData]);

            // 可以在这里根据 eventData 的类型做更精细的状态更新
            if ('status' in eventData) { // TaskStatusUpdateEvent
               setTaskStatus(eventData.status.state as TaskState || 'WORKING'); // 更新宏观状态
            }
            if ('artifact' in eventData) { // TaskArtifactUpdateEvent
                 // 假设最终报告在 TextPart
                 const reportPart = eventData.artifact.parts?.find(p => p.type === 'text') as TextPart | undefined;
                 if(reportPart) {
                     setFinalReport(prev => (prev || '') + reportPart.text); // 可以累积或直接设置
                 }
            }


            // 检查是否是最终事件
            if (eventData.final === true) {
              console.log("Final event flag received from server.");
              streamEnded = true;
              // 最终状态应该由事件本身携带的状态决定
              if ('status' in eventData) {
                  setTaskStatus(eventData.status.state as TaskState);
              } else {
                   setTaskStatus(TaskState.COMPLETED); // 假定 Artifact 事件也是完成
              }
               break; // 收到 final=true，我们可以停止读取这个流了
            }

          } catch (e) {
            console.error("Failed to parse SSE event data:", e, jsonData);
            // 可以选择设置错误状态或继续处理下一个事件
          }
        } else {
            // 处理其他 SSE 行 (如 event:, id:, retry:)，如果需要的话
             console.log("Received non-data SSE line:", eventString);
        }
      } // end for eventString in events
       if (streamEnded) break; // 如果内部逻辑判断流应结束，则跳出外层循环
    } // end while reader
  } catch (err: any) {
      console.error("Error reading stream:", err);
      setError(`读取流失败: ${err.message}`);
      setTaskStatus('FAILED'); // 流读取出错，标记失败
  } finally {
     // 确保 reader 被释放 (如果需要， though exiting loop usually suffices)
     // reader.releaseLock(); ? (Check MDN docs if needed)
     setIsLoading(false); // 确保加载状态结束
     if (!streamEnded && taskStatus !== TaskState.COMPLETED && taskStatus !== TaskState.FAILED) {
         // 如果流意外中断，设置一个合适的最终状态
         setError("流连接意外断开");
         setTaskStatus('FAILED'); // Or 'UNKNOWN'
     }
      console.log("Stream processing function finished.");
  }
};

// 在你的 React 组件的 JSX 中:
// <TopicInputForm onSubmit={startStreamingResearch} disabled={isLoading} />
// <StatusBar status={taskStatus} />
// <ErrorMessage error={error} />
// <ProgressDisplay updates={progressUpdates} />
// <ReportDisplay markdownContent={finalReport} />

```

**5. 处理 `DataPart` (在 `ProgressDisplay` 组件中):**

```typescript
// 假设 ProgressDisplay 组件接收 updates: any[]
const ProgressDisplay = ({ updates }: { updates: any[] }) => {
  return (
    <div className="progress-log mt-4 p-4 border rounded bg-gray-50 h-64 overflow-y-auto font-mono text-sm">
      {updates.map((eventData, index) => {
        let content = null;
        // 确定事件类型并提取 Parts
        let parts: Part[] | undefined = undefined;
        if (eventData && 'status' in eventData && eventData.status?.message?.parts) {
           parts = eventData.status.message.parts;
        } else if (eventData && 'artifact' in eventData && eventData.artifact?.parts) {
           // 注意：通常最终报告才放在 artifact 里，但这里也检查一下
           parts = eventData.artifact.parts;
        }

        if (parts) {
          content = parts.map((part, partIndex) => {
            if (part.type === 'text') {
              // 渲染 TextPart
              return <p key={`${index}-${partIndex}`} className="whitespace-pre-wrap">{part.text}</p>;
            } else if (part.type === 'data') {
              // 渲染 DataPart (示例：格式化 JSON)
              const data = part.data;
              // 尝试更友好的展示
              const step = data?.step || data?.step_name;
              const status = data?.status;
              const detail = data?.detail || data?.message;
              const query = data?.query;
              const source = data?.source;
              const count = data?.results_count;

              let friendlyText = `[${step || '步骤未知'}] ${status ? '(' + status + ')' : ''}`;
              if(source) friendlyText += ` 来源:${source}`;
              if(query) friendlyText += ` 查询:'${query}'`;
              if(count !== undefined) friendlyText += ` (${count}条结果)`;
              if(detail && detail !== readable_summary) friendlyText += ` - ${detail}`; // 避免重复


              return (
                <details key={`${index}-${partIndex}`} className="my-1 p-1 border-l-2 border-blue-300 bg-blue-50 text-xs">
                   <summary className="cursor-pointer text-blue-800">{friendlyText || `收到结构化数据 (点击展开)`}</summary>
                   <pre className="mt-1 text-gray-600 bg-white p-1 rounded overflow-x-auto">
                     {JSON.stringify(data, null, 2)}
                   </pre>
                </details>
              );
            }
            // 可以添加对 FilePart 的处理
            return null;
          });
        } else {
           // 如果无法解析 parts，显示原始事件数据（用于调试）
           content = <pre className="text-xs text-red-500">未知事件结构: {JSON.stringify(eventData)}</pre>;
        }

        // 用一个容器包裹每次更新的内容
        return <div key={index} className="update-event py-1 border-b border-gray-200">{content}</div>;
      })}
    </div>
  );
};
```

**6. 注意事项和进一步优化:**

* **错误处理:** 上述代码包含了基本的错误处理，但生产环境需要更细致的处理，例如区分网络错误、服务器错误、JSON 解析错误等。
* **SSE 解析健壮性:** 手动解析 SSE 流需要仔细处理边界情况，例如事件跨多个 `read()` 调用到达、`retry:` 指令等。可以考虑使用成熟的前端 SSE 客户端库（如果它们支持通过 `Workspace` 的 `ReadableStream` 或允许自定义请求方式）。
* **状态更新频率:** 如果服务器发送更新过于频繁，可能会导致 React 状态更新过多影响性能。可以考虑进行节流 (throttling) 或批处理 (batching) 更新。
* **`DataPart` 的约定:** 为了让前端能“理解”并友好地展示 `DataPart` 的内容，前后端需要约定好 `data` 字段中可能包含的键名和结构。
* **中止请求:** 代码中加入了 `AbortController`，允许在用户发起新的请求或离开页面时中止正在进行的 `Workspace` 请求和流式读取。
* **类型安全:** 强烈建议在前端项目中也维护一套与 `core/a2a/types.py` 同步的 TypeScript 接口定义，以获得完整的类型检查好处。