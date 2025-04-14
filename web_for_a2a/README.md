# DeepResearch A2A Web UI

## 概述

本项目是一个基于 **Next.js**, **React**, **TypeScript** 和 **Tailwind CSS** 构建的 Web 用户界面 (UI)，旨在与 **DeepResearch A2A (Agent-to-Agent) 服务器** 进行交互。用户可以通过此界面发起深度研究任务，并**实时查看**由服务器通过 Server-Sent Events (SSE) 推送的研究进度更新和最终生成的报告。

这个项目的主要目的是演示如何在现代 Web 前端应用中，使用浏览器原生 API (`Workspace`, `ReadableStream`) 来对接和处理符合 A2A 协议规范的流式响应。

## 特性

* **连接 A2A 服务:** 通过 HTTP 与指定的 DeepResearch A2A 服务器通信。
* **发起研究任务:** 向服务器发送符合 A2A `tasks/sendSubscribe` 规范的请求以启动流式研究任务。
* **实时流式更新:** 使用 `Workspace` API 的 `ReadableStream` 接收并解析来自服务器的 Server-Sent Events (SSE)，实时展示任务进度。
* **结构化数据显示:** 能够区分并展示 A2A 事件中的 `TextPart` 和 `DataPart`。
* **最终报告展示:** 在任务完成后，提取并展示最终的研究报告。
* **基础状态与错误显示:** 提供简单的 UI 反馈，显示任务的当前状态（空闲、进行中、完成、错误）和遇到的问题。

## 技术栈

* **框架:** Next.js (App Router)
* **UI 库:** React
* **语言:** TypeScript
* **样式:** Tailwind CSS
* **核心 API:** Browser `Workspace` API, `ReadableStream`, `TextDecoder`
* **辅助库:** `uuid` (用于生成客户端 Task ID 示例)

## 目录结构 (相关部分)

```
mentis/
└── web_for_a2a/            # Web UI 项目根目录
    ├── app/                # Next.js App Router 目录
    │   ├── api/
    │   │   └── a2a/        # （可选）API Route 代理目录
    │   │       └── [[...slug]]/
    │   │           └── route.ts
    │   ├── deepresearch/   # DeepResearch Agent 的 UI 页面
    │   │   └── page.tsx    # ★ UI 界面的核心实现文件
    │   └── layout.tsx      # 根布局
    │   └── page.tsx        # 根页面 (可能重定向或包含链接)
    ├── public/             # 静态资源
    ├── .env.local          # (可选) 本地环境变量配置文件
    ├── next.config.js      # Next.js 配置文件 (可能包含代理设置)
    ├── package.json
    ├── tailwind.config.ts
    └── tsconfig.json
```
*(★ 表示本文档重点关注的文件)*

## 前提条件

* Node.js (推荐 LTS 版本) 和 npm / yarn / pnpm / uv 等包管理器。
* **DeepResearch A2A 后端服务器** 必须正在运行，并且其地址可访问（默认为 `http://127.0.0.1:8000`）。
* 对 React, Next.js, TypeScript 和 `Workspace` API 有基本了解。

## 安装与设置

1.  **导航到目录:**
    ```bash
    cd mentis/web_for_a2a
    ```
2.  **安装依赖:** (根据你项目使用的包管理器选择)
    ```bash
    npm install
    # yarn install
    # pnpm install
    # uv sync
    ```
3.  **(可选) 配置后端服务器地址:**
    * 默认情况下，前端会尝试连接 `http://127.0.0.1:8000`。
    * 如果你使用了 API Route 代理（如 `/api/a2a`），或者你的 A2A 服务器地址不同，可以在 `web_for_a2a` 目录下创建一个 `.env.local` 文件，并设置环境变量：
        ```dotenv
        # .env.local
        NEXT_PUBLIC_A2A_SERVER_URL=/api/a2a # 指向代理
        # 或者
        # NEXT_PUBLIC_A2A_SERVER_URL=http://your-backend-address:port # 直接指向后端
        ```
    * **注意:** 环境变量名必须以 `NEXT_PUBLIC_` 开头，才能在浏览器端的代码中访问。`page.tsx` 中的代码 `process.env.NEXT_PUBLIC_A2A_SERVER_URL` 会读取这个值。

## 运行

1.  **确保后端 A2A 服务器已启动。**
2.  **启动 Next.js 开发服务器:**
    ```bash
    npm run dev
    # yarn dev
    # pnpm dev
    # uv run dev (如果配置了脚本)
    ```
3.  **访问页面:** 在浏览器中打开 Next.js 应用的地址（通常是 `http://localhost:3000`），并导航到 DeepResearch 页面（例如 `http://localhost:3000/deepresearch`）。

## 使用说明

当前示例 UI 非常简单：

1.  页面加载后，你会看到一个标题和一个按钮。
2.  点击 **"开始流式研究 (特斯拉主题)"** 按钮。
3.  按钮会变为 "研究进行中..." 并禁用。
4.  页面上的 **"当前状态"** 会变为 `streaming`。
5.  **"流式内容输出:"** 区域会开始实时显示从服务器推送过来的进度更新。你会看到 `[状态更新]` 或 `[收到报告片段]` 的标记，后面跟着相应的文本或结构化数据 (JSON 格式)。
6.  当研究完成或出错时，**"当前状态"** 会更新为 `completed` 或 `error`，按钮会重新启用。
7.  如果成功，最终的**研究报告**会显示在页面底部。
8.  如果过程中出现错误，错误信息会显示在状态下方。

## 核心实现：处理 A2A 流 (Fetch API + ReadableStream)

这是前端实现中最关键的部分，位于 `app/deepresearch/page.tsx` 的 `startStream` 和 `processStream` 函数中。

**为什么不直接用 `EventSource` API?**

标准的 `EventSource` 浏览器 API 非常适合接收 SSE，但它通常只能发起 `GET` 请求。而 A2A 协议规定启动流式任务 (`tasks/sendSubscribe`) 需要使用 `POST` 请求（因为要传递包含研究主题的 `message` 等参数）。为了在不修改标准 A2A 服务器行为的前提下实现此功能，我们选用了更底层的 `Workspace` API。

**`startStream` 函数主要流程:**

1.  **重置状态:** 清空之前的输出、错误，设置状态为 `streaming`。
2.  **创建 `AbortController`:** 用于在需要时（例如发起新请求或组件卸载）中止当前的 `Workspace` 请求。
3.  **构建请求体:** 创建符合 A2A `tasks/sendSubscribe` 方法要求的 JSON-RPC 请求对象，包含 `method`, `id`, 以及 `params` (内含客户端生成的 `taskId`, `sessionId`, `message` 等)。
4.  **发送 `Workspace` 请求:**
    * 使用 `POST` 方法。
    * 设置 `Content-Type: application/json` 和 `Accept: text/event-stream` 请求头。
    * 将 JSON-RPC 对象字符串化后作为 `body`。
    * 传入 `AbortController` 的 `signal`。
5.  **检查初始响应:**
    * 确认 `response.ok` (HTTP 状态码 2xx)。
    * **关键检查:** 确认 `response.headers.get('content-type')` 包含 `text/event-stream`。如果不是，说明服务器未能成功建立 SSE 连接（可能是服务器端错误或未正确返回流类型），此时应抛出错误。
    * **(调试日志)** 添加了打印所有响应头和 CORS 头 (`access-control-allow-origin`) 的日志，用于诊断连接问题。
6.  **获取 `ReadableStream`:** 从 `response.body` 获取流式读取器 `reader`。
7.  **调用 `processStream`:** 将 `reader` 传递给专门处理流的异步函数。

**`processStream` 函数主要流程 (SSE 解析核心):**

1.  **初始化:** 创建 `TextDecoder` 用于将服务器发送的 `Uint8Array` 数据块解码为文本；创建一个 `buffer` 字符串用于处理跨数据块的、不完整的 SSE 消息。
2.  **循环读取:** 使用 `while (true)` 和 `await reader.read()` 不断读取数据块。
3.  **解码与缓冲:** 将读取到的 `value` (Uint8Array) 解码并追加到 `buffer`。
4.  **分割 SSE 事件:** **关键步骤！** SSE 事件由两个连续的换行符 (`\n\n`, `\r\r`, 或 `\r\n\r\n`) 分隔。代码使用正则表达式 `/\r\n\r\n|\n\n|\r\r/` 来查找并分割出 buffer 中完整的事件字符串 (`eventString`)。未处理完的部分保留在 `buffer` 中供下次 `read()` 后拼接。
5.  **解析单个 SSE 事件:**
    * 对每个分割出的 `eventString` 进行处理。
    * 按行 (`\n`, `\r`, `\r\n`) 分割事件内部。
    * 遍历每一行，主要查找以 `data:` 开头的行，提取其后的 JSON 字符串 (`jsonData`)。SSE 事件可能包含多行 `data:`，代码会将其拼接起来。同时也处理 `event:`, `id:`, `retry:` 等标准 SSE 字段（虽然本示例主要关心 `data:`）。
    * **关键解析:** 使用 `JSON.parse(jsonData)` 将提取到的字符串解析为 JavaScript 对象 (`eventResponse`，预期符合 `SendTaskStreamingResponse` 接口)。
    * **添加了详细日志:** 在解析前后都打印了原始数据和解析结果，便于调试。
    * **错误处理:** 如果 `JSON.parse` 失败，会捕获异常，调用 `setError` 更新 UI，并停止处理流。
6.  **处理解析后的数据:**
    * 检查 `eventResponse.error`，如果存在则报告错误并停止。
    * 获取 `eventData = eventResponse.result` (即 `TaskStatusUpdateEvent` 或 `TaskArtifactUpdateEvent`)。
    * **更新 React 状态:** 调用 `setStreamedContent(prev => [...prev, eventData])` 将新的事件数据添加到状态数组中，这将触发 UI 重新渲染。
    * **检查结束标志:** 检查 `eventData.final === true`。如果为 `true`，则设置状态为 `completed` 并标记流结束。
7.  **循环与退出:** `while` 循环会持续进行，直到 `reader.read()` 返回 `done: true`，或者内部处理（如解析错误、收到 `final: true`）决定中断。

**`useEffect` 处理最终报告:**

* 当 `status` 变为 `'completed'` 时，此 Hook 会运行。
* 它会反向遍历 `streamedContent` 数组，查找最后一个包含 `artifact` 的事件。
* 如果找到，则从中提取 `TextPart` 的内容并设置到 `finalReport` 状态，用于在页面底部单独展示完整报告。

## 状态管理

主要使用 `useState` 管理以下关键状态：

* `status`: `'idle' | 'streaming' | 'completed' | 'error' | 'aborted'` - UI 的宏观状态。
* `streamedContent`: `StreamEventResult[]` - 存储从 SSE 流接收并解析出的所有事件 `result` 对象。
* `error`: `string | null` - 存储发生的错误信息。
* `finalReport`: `string | null` - 存储从最终 Artifact 中提取的报告文本。

## 数据展示

* **流式内容输出:** 通过 `.map()` 遍历 `streamedContent` 数组。
    * 根据每个 `eventData` 是 `TaskStatusUpdateEvent` 还是 `TaskArtifactUpdateEvent` 来决定显示标记（"[状态更新]" 或 "[收到报告片段]")。
    * 再遍历事件中的 `parts` 数组。
    * 对 `TextPart`，直接显示 `part.text`。
    * 对 `DataPart`，使用 `<pre>{JSON.stringify(part.data, null, 2)}</pre>` 格式化显示其 `data` 对象。**（优化点：可以根据 `data` 内部约定的字段进行更友好的渲染）**
* **最终报告:** 当 `finalReport` 有值时，在页面底部使用 `<pre>` 标签展示（可以替换为 Markdown 渲染器）。

## 限制与未来工作

* **UI 基础:** 当前 UI 非常简化，仅用于演示核心流式逻辑。需要构建更完善的组件、布局和样式。
* **仅流式:** 未包含发送同步任务 (`tasks/send`) 和轮询 (`tasks/get`) 的逻辑。
* **硬编码主题:** 研究主题是硬编码的，需要改为用户输入。
* **DataPart 展示:** 当前对 `DataPart` 只是简单显示 JSON，可以根据与后端约定的数据结构进行更丰富的可视化展示。
* **Markdown 渲染:** 最终报告目前使用 `<pre>` 显示，应替换为真正的 Markdown 渲染组件（如 `react-markdown`）。
* **错误处理:** 可以进一步细化错误处理和用户提示。
* **多轮对话/状态保持:** 当前实现不支持需要 Agent 保持状态的多轮对话。
* **真实推送通知:** 前端未处理 A2A 的推送通知逻辑。


## 后续步骤

1.  **构建更丰富的 UI 组件:** 将输入、状态、进度、报告显示拆分成独立的、样式更美观的 React 组件。
2.  **美化 `DataPart` 展示:** 根据你和后端约定好的 `DataPart` 结构，更有意义地展示结构化信息，而不是只显示 JSON。
3.  **实现用户输入:** 将硬编码的研究主题替换为真正的用户输入。
4.  **添加更完善的错误处理和用户反馈:** 例如，区分不同类型的错误，提供重试按钮等。
5.  **管理 AbortController:** 确保在组件卸载或发起新请求时，之前的 `Workspace` 请求能被正确中止。
6.  **状态管理库 (可选):** 如果应用变得复杂，可以引入 Zustand, Jotai, Redux 等状态管理库。
7.  **添加同步任务逻辑:** 如果需要，可以添加调用 `tasks/send` 和轮询 `tasks/get` 的逻辑。