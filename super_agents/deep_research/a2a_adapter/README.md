# DeepResearch A2A 适配器

## 概述

本模块提供了一个将 **DeepResearch Agent**（一个基于 LangGraph 构建的、能够执行深度研究并调用外部工具的复杂 Agent）与 Google 的 **Agent-to-Agent (A2A) 协议** 进行集成的适配层。通过这个适配器，强大的 DeepResearch Agent 可以作为一个标准的 A2A 服务被发现和调用，响应 A2A 请求，并通过同步或流式方式返回结构化的研究结果。

## 特性

* **解耦设计:** 适配器层 (`AgentTaskManager`) 与 DeepResearch 核心 Agent 逻辑分离，方便维护和扩展。
* **A2A 协议兼容:** 实现了 A2A 协议的核心方法，如 `tasks/send`, `tasks/sendSubscribe`, `tasks/get` 等，并提供 `/.well-known/agent.json` 服务发现端点。
* **类型安全:** 基于 `core/a2a/types.py` 中的 Pydantic 模型进行严格的请求/响应校验。
* **工具集成:** 支持 DeepResearch Agent 在执行任务时调用外部工具 (如 Tavily, Exa API, LLM)。
* **流式响应:** 支持通过 Server-Sent Events (SSE) 实时返回研究进度和中间状态更新。*(当前版本的更新详细程度取决于 `_process_stream_updates` 的实现)*
* **推送通知框架:** 包含了处理和发送推送通知的逻辑框架。*(需要配置真实的推送发送器才能实际发送)*

## 目录结构 (相关部分)

```
.
├── core/                           # 核心 A2A 协议实现 (复用)
│   └── a2a/
│       ├── client/
│       │   └── client.py           # A2AClient 客户端库实现
│       ├── server/
│       │   ├── server.py           # A2AServer HTTP 服务器实现
│       │   └── task_manager.py     # TaskManager 基础接口
│       ├── agent_task_manager.py     # (之前的 LangGraph Agent 任务管理器示例)
│       └── types.py                # A2A 协议的 Pydantic 模型定义
├── super_agents/                   # 可能包含多个 Super Agent
│   └── deep_research/              # DeepResearch Agent 核心代码
│       ├── a2a_adapter/            # DeepResearch 的 A2A 适配层
│       │   ├── deep_research_task_manager.py # ★ 本适配器的核心逻辑
│       │   ├── setup.py              # ★ 配置和组装 A2A 服务器
│       │   ├── run_server.py         # ★ 启动服务器的脚本
│       │   └── client_example.py       # ★ 测试本适配器的客户端示例
│       ├── reason_graph/             # DeepResearch 的 LangGraph 图和状态定义 (假设)
│       │   ├── graph.py
│       │   ├── state.py
│       │   └── schemas.py
│       └── ...                     # DeepResearch 的其他模块
├── .env                            # 存储环境变量 - *需要自行创建*
├── requirements.txt                # Python 依赖项列表 (假设存在)
└── README.md                       # 项目主 README (可能)
```
*(★ 表示本文档主要涉及的文件)*

## 安装

确保已安装所有必要的依赖。推荐使用虚拟环境。

1.  **创建并激活虚拟环境 (使用 uv):**
    ```bash
    uv venv
    source .venv/bin/activate  # Linux/macOS
    # 或者 .venv\Scripts\activate # Windows
    ```
    *(如果未使用 uv, 可用 `python -m venv .venv`)*

2.  **安装依赖项 (使用 uv):**
    ```bash
    uv sync
    ```
    *(如果未使用 uv, 可用 `pip install -r requirements.txt`)*

## 配置

1.  在项目**根目录**下创建 `.env` 文件（如果不存在，可以复制 `.env.example` 并重命名）。
2.  确保设置了必要的环境变量。根据服务器日志和 DeepResearch 的可能需求，可能包括：
    ```dotenv
    # A2A 服务器配置
    A2A_HOST=127.0.0.1
    A2A_PORT=8000

    # LLM API 配置 (示例为 OpenAI/XAI, 根据实际使用的 LLM 修改)
    # OPENAI_API_KEY=sk-...
    XAI_API_KEY=your_xai_api_key # 如果使用 Grok
    # GROQ_API_KEY=... # 如果使用 Groq

    # DeepResearch 可能需要的其他工具 API Keys
    TAVILY_API_KEY=tvly-...
    EXA_API_KEY=your_exa_api_key
    # 其他 DeepResearch 可能需要的 Keys...
    ```

## 使用方法

### 启动 A2A 服务器

在项目根目录下，运行：

```bash
python -m super_agents.deep_research.a2a_adapter.run_server
```

服务器将根据 `.env` 文件中的 `A2A_HOST` 和 `A2A_PORT` 启动，默认监听 `http://127.0.0.1:8000`。

### 客户端示例

项目提供了一个专门测试 DeepResearch A2A 适配器的客户端示例。在服务器运行的情况下，打开**新的终端**并运行：

```bash
python -m super_agents.deep_research.a2a_adapter.client_example
```

它会连接服务器，获取 Agent 信息，然后提示你输入研究主题（或使用默认的特斯拉主题），并通过流式方式（如果 AgentCard 声明支持）显示研究进度和最终报告。

### 在代码中集成（服务端）

如果你想在其他 Python 代码中启动这个服务，可以导入并使用 `setup` 模块：

```python
# 导入设置函数
from super_agents.deep_research.a2a_adapter.setup import setup_a2a_server

# 配置并获取服务器实例 (host/port 可选，会使用 setup 中的默认值或环境变量)
server = setup_a2a_server(host="127.0.0.1", port=8000)

# 启动服务器 (这是一个阻塞调用)
server.start()
```

## 架构与核心组件

此 A2A 适配器主要由以下几部分协作完成：

1.  **`core/a2a/types.py`**: 定义 A2A 协议数据结构的 Pydantic 模型，确保类型安全和数据校验。
2.  **`core/a2a/server/server.py` (`A2AServer`)**: 通用的 A2A HTTP 服务器，负责接收请求、解析 JSON-RPC、验证方法、调用 TaskManager 处理，并根据 TaskManager 的返回类型（`JSONRPCResponse` 或 `AsyncIterable`）发送正确的 HTTP 响应（`application/json` 或 `text/event-stream`）。
3.  **`super_agents/deep_research/a2a_adapter/deep_research_task_manager.py` (`DeepResearchTaskManager`)**:
    * **核心适配器**，继承自通用的 `InMemoryTaskManager`（提供内存任务存储和基础方法）。
    * 实现了处理 A2A 请求（如 `on_send_task`, `on_send_task_subscribe`）的具体逻辑。
    * **关键职责:**
        * 将传入 A2A 请求中的用户查询 (`message.parts`) 转换为 DeepResearch Agent (`research_app`) 需要的输入格式（目前是提取文本放入 `initial_state["topic"]`）。
        * 调用 DeepResearch Agent 的流式接口 (`research_app.astream`) 来执行研究任务。
        * **处理中间状态:** 在 `_process_stream_updates` 方法中，解析 `research_app` 流式输出的状态更新 (`StreamUpdate` 对象)，提取信息，并将其转换为 A2A 的 `TaskStatusUpdateEvent`（包含 `TextPart` 和 `DataPart`），通过 SSE 推送给客户端。**此方法的实现质量直接决定了客户端收到的进度信息的丰富程度。**
        * **处理最终结果:** 在 `_finalize_task` 方法中，从 Agent 的最终状态提取 Markdown 报告，创建 A2A `Artifact`，更新任务状态为 `COMPLETED`，并通过 SSE 推送 `TaskArtifactUpdateEvent` 和最终的 `TaskStatusUpdateEvent`。
        * **SSE 队列管理:** 实现了 `setup_sse_consumer`, `enqueue_events_for_sse`, `dequeue_events_for_sse` 等方法来管理与客户端的 SSE 连接和事件推送。
        * **推送通知 (框架):** 实现了 `send_task_notification` 方法框架，但需要注入真实的 `notification_sender_auth` 对象才能实际发送。
4.  **`super_agents/deep_research/a2a_adapter/setup.py`**:
    * `setup_a2a_server` 函数：集中配置和组装上述组件。创建 `AgentCard`（描述 Agent 能力，包括是否支持流式和推送），创建 `DeepResearchTaskManager` 实例（并注入模拟的推送通知发送器），最后创建并返回配置好的 `A2AServer` 实例。
    * `run_server` 函数：调用 `setup_a2a_server` 并启动服务器。
5.  **`super_agents/deep_research/a2a_adapter/run_server.py`**: 简单的入口脚本，调用 `setup.py` 中的 `run_server` 函数来启动服务。

## 工作流程 (流式任务示例)

1.  **客户端**: 构造 `payload` (符合 `TaskSendParams`, 含 `id`, `message`), 调用 `client.send_task_streaming(payload)`.
2.  **A2AClient**: 发送 `method: tasks/sendSubscribe` 的 JSON-RPC POST 请求到服务器。
3.  **A2AServer**: 接收请求，验证，调用 `TaskManager.on_send_task_subscribe`.
4.  **DeepResearchTaskManager**: 验证请求，设置任务初始状态为 `WORKING`，**启动后台任务** `_process_research_task(payload)`，设置 SSE 队列，**立即返回 `dequeue_events_for_sse` 异步生成器**。
5.  **A2AServer**: 检测到返回的是 `AsyncIterable`，向客户端发送 HTTP 200 OK 响应，`Content-Type` 为 `text/event-stream`，保持连接。
6.  **客户端**: 收到 200 OK 和正确的 `Content-Type`，建立 SSE 连接，开始 `async for` 循环等待事件。
7.  **服务器 (后台任务 `_process_research_task`)**: 调用 `research_app.astream` 执行 LangGraph 图。
8.  **服务器 (后台任务 `_process_research_task`)**: 每次 `research_app` 产生状态更新，调用 `_process_stream_updates`。
9.  **服务器 (`_process_stream_updates`)**: 解析状态更新，创建 `TaskStatusUpdateEvent` (含 `TextPart`/`DataPart`)，调用 `enqueue_events_for_sse` 将事件放入队列。
10. **服务器 (`dequeue_events_for_sse`)**: 从队列中获取事件，包装成 `SendTaskStreamingResponse`，`yield` 给 `A2AServer`。
11. **A2AServer**: 将 `SendTaskStreamingResponse` 格式化为 SSE 事件 (`data: {...}\n\n`) 发送给客户端。
12. **客户端**: `async for` 循环接收到事件，解析 `SendTaskStreamingResponse`，处理 `result` 中的 `TaskStatusUpdateEvent` 并打印“进度更新”。
13. **服务器 (后台任务 `_process_research_task`)**: 研究完成，调用 `_finalize_task`。
14. **服务器 (`_finalize_task`)**: 创建最终 `Artifact` 和 `COMPLETED` 状态，调用 `enqueue_events_for_sse` 发送 `TaskArtifactUpdateEvent` 和 `TaskStatusUpdateEvent(final=True)`，最后发送 `SSE_CLOSE_SENTINEL`。
15. **客户端**: 接收并处理 `TaskArtifactUpdateEvent`（打印报告），接收到 `final=True` 的状态事件，接收到关闭信号后 `async for` 循环结束。

## 关键实现细节总结

* **Agent 接口:** `AgentTaskManager` 期望注入的 Agent 对象至少实现 `invoke(query, session_id)` 和 `stream(query, session_id)` 方法（后者需为异步生成器）。
* **流式更新内容:** 客户端看到的流式更新的详细程度，完全取决于 `DeepResearchTaskManager._process_stream_updates` 方法如何解析 Agent 内部状态并构造 `TextPart` 或 `DataPart`。
* **Pydantic 严格性:** A2A 交互的健壮性很大程度上依赖于 `types.py` 中模型的准确性和双方对这些模型的遵守。任何必需字段的缺失或类型错误都会导致 `ValidationError`。
* **SSE 实现:** 流式响应依赖于 `AgentTaskManager` 中 SSE 队列的正确实现（`setup_sse_consumer`, `enqueue_events_for_sse`, `dequeue_events_for_sse`）。

## 与其他系统集成

由于实现了标准的 A2A 协议，此 DeepResearch Agent 服务可以方便地集成到：

* Google Assistant 等支持 A2A 的平台。
* 其他实现了 A2A 客户端的 Agent 或应用程序。
* 需要调用强大研究能力的自定义前端或后端系统。

## 故障排除

如果遇到问题：

1.  **检查 `.env` 文件:** 确保所有必需的 API 密钥（OpenAI/XAI, Tavily, Exa 等）都已正确配置且有效。
2.  **检查服务器日志:** `run_server.py` 的输出包含详细的执行信息和错误栈。优先查看 `ERROR` 或 `WARNING` 级别的日志。
3.  **检查客户端日志:** 客户端脚本的输出可以帮助判断问题发生在请求发送阶段还是响应处理阶段。`httpx` 的日志可以确认网络请求是否成功。
4.  **端口冲突:** 确保端口 8000 没有被其他应用程序占用。
5.  **依赖安装:** 确认所有 `requirements.txt` 中的依赖都已在激活的虚拟环境中正确安装。

## 贡献

欢迎对此适配器或 DeepResearch Agent 本身贡献代码、报告问题或提出改进建议。请参考项目（如果公开）的贡献指南。