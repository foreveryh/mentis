# DeepResearch Agent

## 概述

DeepResearch Agent 是一个基于 LangGraph 构建的、能够执行深度研究并调用外部工具的复杂 Agent。它能够针对用户提供的任意主题，自动化地执行一个完整的研究流程，从搜索信息到分析数据，最终生成一份详细的研究报告。

最近，我们还实现了与 Google 的 **Agent-to-Agent (A2A) 协议**的集成，使 DeepResearch Agent 可以作为标准的 A2A 服务被发现和调用，响应 A2A 请求，并通过同步或流式方式返回结构化的研究结果。

## 特性

### 核心功能

* **自动化研究流程**：从主题分析、多源搜索到最终报告生成的端到端流程
* **多工具集成**：集成了 Tavily 搜索、Exa 学术搜索等外部工具
* **结构化报告**：生成包含引用、章节和关键发现的 Markdown 格式研究报告
* **状态驱动**：基于 LangGraph 的状态驱动设计，支持复杂的研究流程管理

### A2A 适配器特性

* **解耦设计:** 适配器层 (`DeepResearchTaskManager`) 与 DeepResearch 核心 Agent 逻辑分离，方便维护和扩展
* **A2A 协议兼容:** 实现了 A2A 协议的核心方法，如 `tasks/send`, `tasks/sendSubscribe`, `tasks/get` 等
* **类型安全:** 基于 Pydantic 模型进行严格的请求/响应校验
* **流式响应:** 支持通过 Server-Sent Events (SSE) 实时返回研究进度和中间状态更新
* **推送通知框架:** 包含了处理和发送推送通知的逻辑框架

## 目录结构

```
.
├── a2a_adapter/                # DeepResearch 的 A2A 适配层
│   ├── README.md              # A2A 适配器的详细文档
│   ├── client_example.py      # 测试 A2A 适配器的客户端示例
│   ├── deep_research_task_manager.py # 核心适配器逻辑
│   ├── run_server.py          # 启动 A2A 服务器的脚本
│   └── setup.py               # 配置和组装 A2A 服务器
├── main.py                    # DeepResearch Agent 的主入口点
├── output/                    # 生成的研究报告输出目录
└── reason_graph/              # DeepResearch 的 LangGraph 图和状态定义
    ├── graph.py               # LangGraph 图定义
    ├── nodes.py               # 图节点实现
    ├── prompt.py              # 提示模板
    ├── schemas.py             # 数据模型定义
    ├── state.py               # 状态定义
    └── tools.py               # 工具实现
```

## 安装

确保已安装所有必要的依赖。推荐使用虚拟环境。

1. **创建并激活虚拟环境 (使用 uv):**
   ```bash
   uv venv
   source .venv/bin/activate  # Linux/macOS
   # 或者 .venv\Scripts\activate # Windows
   ```
   *(如果未使用 uv, 可用 `python -m venv .venv`)*

2. **安装依赖项 (使用 uv):**
   ```bash
   uv sync
   ```
   *(如果未使用 uv, 可用 `pip install -r requirements.txt`)*

## 配置

1. 在项目**根目录**下创建 `.env` 文件（如果不存在，可以复制 `.env.example` 并重命名）。
2. 确保设置了必要的环境变量：
   ```dotenv
   # LLM API 配置 (根据实际使用的 LLM 修改)
   OPENAI_API_KEY=sk-...  # 如果使用 OpenAI
   # XAI_API_KEY=...      # 如果使用 Grok
   # DEEPSEEK_API_KEY=... # 如果使用 DeepSeek
   # GROQ_API_KEY=...     # 如果使用 Groq

   # 研究工具 API Keys
   TAVILY_API_KEY=tvly-...
   EXA_API_KEY=...

   # A2A 服务器配置 (如果使用 A2A 适配器)
   A2A_HOST=127.0.0.1
   A2A_PORT=8000
   ```

## 使用方法

### 直接使用 DeepResearch Agent

在项目根目录下，运行：

```bash
# 从项目根目录 (mentis/) 运行
python -m super_agents.deep_research.main
```

脚本会提示您输入研究主题。输入后，Agent 将开始执行研究流程，并在完成后在 `output/` 目录中生成一份 Markdown 格式的研究报告。

### 使用 A2A 适配器

#### 启动 A2A 服务器

在项目根目录下，运行：

```bash
python -m super_agents.deep_research.a2a_adapter.run_server
```

服务器将根据 `.env` 文件中的 `A2A_HOST` 和 `A2A_PORT` 启动，默认监听 `http://127.0.0.1:8000`。

#### 使用客户端示例

项目提供了一个专门测试 DeepResearch A2A 适配器的客户端示例。在服务器运行的情况下，打开**新的终端**并运行：

```bash
python -m super_agents.deep_research.a2a_adapter.client_example
```

它会连接服务器，获取 Agent 信息，然后提示你输入研究主题（或使用默认的特斯拉主题），并通过流式方式显示研究进度和最终报告。

#### 在代码中集成（服务端）

如果你想在其他 Python 代码中启动这个服务，可以导入并使用 `setup` 模块：

```python
# 导入设置函数
from super_agents.deep_research.a2a_adapter.setup import setup_a2a_server

# 配置并获取服务器实例
server = setup_a2a_server(host="127.0.0.1", port=8000)

# 启动服务器 (这是一个阻塞调用)
server.start()
```

## 内部工作流程

DeepResearch Agent 执行以下研究步骤：

1. **研究规划 (Plan Research)**: 分析主题，生成初步的搜索查询和分析点
2. **多源搜索 (Multi-Source Search)**: 调用网页搜索 (Tavily)、学术搜索 (Exa) 等工具获取信息
3. **(可选) 分析执行 (Perform Analysis)**: 对搜索结果进行初步分析（如情感、SWOT 等）
4. **差距分析 (Gap Analysis)**: 评估已有信息，识别知识空白和局限性
5. **(可选) 补充搜索 (Gap Filling)**: 针对知识空白进行额外的、更具针对性的搜索
6. **最终综合 (Final Synthesis)**: 整合所有信息，提炼关键发现和不确定性
7. **报告生成 (Report Generation)**: 将综合结果和上下文信息，撰写成一份详细的、带引用的 Markdown 研究报告

## A2A 适配器架构

A2A 适配器主要由以下几部分协作完成：

1. **`deep_research_task_manager.py` (`DeepResearchTaskManager`)**:
   * 核心适配器，继承自通用的 `InMemoryTaskManager`
   * 实现了处理 A2A 请求的具体逻辑
   * 将 A2A 请求转换为 DeepResearch Agent 需要的输入格式
   * 调用 DeepResearch Agent 的流式接口来执行研究任务
   * 处理中间状态和最终结果，转换为 A2A 协议格式

2. **`setup.py`**:
   * `setup_a2a_server` 函数：配置和组装 A2A 服务器组件
   * 创建 `AgentCard`（描述 Agent 能力）
   * 创建 `DeepResearchTaskManager` 实例
   * 创建并返回配置好的 `A2AServer` 实例

3. **`run_server.py`**: 
   * 简单的入口脚本，调用 `setup.py` 中的函数来启动服务

## A2A 工作流程 (流式任务示例)

1. **客户端**: 构造请求，调用 `client.send_task_streaming(payload)`
2. **A2AClient**: 发送 `tasks/sendSubscribe` 的 JSON-RPC 请求到服务器
3. **A2AServer**: 接收请求，调用 `TaskManager.on_send_task_subscribe`
4. **DeepResearchTaskManager**: 
   * 验证请求，设置任务初始状态为 `WORKING`
   * 启动后台任务 `_process_research_task(payload)`
   * 设置 SSE 队列，返回 `dequeue_events_for_sse` 异步生成器
5. **A2AServer**: 向客户端发送 HTTP 200 OK 响应，`Content-Type` 为 `text/event-stream`
6. **客户端**: 建立 SSE 连接，开始等待事件
7. **服务器 (后台任务)**: 调用 `research_app.astream` 执行 LangGraph 图
8. **服务器 (后台任务)**: 每次产生状态更新，解析并创建 `TaskStatusUpdateEvent`
9. **服务器**: 将事件放入队列，然后发送给客户端
10. **客户端**: 接收事件，处理并显示进度更新
11. **服务器 (后台任务)**: 研究完成，创建最终 `Artifact` 和 `COMPLETED` 状态
12. **客户端**: 接收并处理最终报告和状态事件

## 与其他系统集成

由于实现了标准的 A2A 协议，DeepResearch Agent 可以方便地集成到：

* Google Assistant 等支持 A2A 的平台
* 其他实现了 A2A 客户端的 Agent 或应用程序
* 需要调用强大研究能力的自定义前端或后端系统

## 故障排除

如果遇到问题：

1. **检查 `.env` 文件:** 确保所有必需的 API 密钥都已正确配置且有效
2. **检查服务器日志:** 优先查看 `ERROR` 或 `WARNING` 级别的日志
3. **检查客户端日志:** 客户端脚本的输出可以帮助判断问题发生在请求发送阶段还是响应处理阶段
4. **端口冲突:** 确保端口 8000 没有被其他应用程序占用
5. **依赖安装:** 确认所有依赖都已在激活的虚拟环境中正确安装

## 贡献

欢迎对 DeepResearch Agent 或 A2A 适配器贡献代码、报告问题或提出改进建议。