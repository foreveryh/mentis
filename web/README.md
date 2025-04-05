# Mentis 的 LangGraph + NextJS 集成演示

Mentis 演示项目展示了如何使用LangGraph创建AI代理并将其集成到NextJS应用程序中。它具体演示了 **ReAct Agent** (用于通用任务) 和 **Deep Research Agent** (用于深度主题探索) 的实现。LangGraph是一个强大的框架，用于构建代理和多代理工作流。它提供了构建复杂逻辑的灵活性，并具有出色的调试工具(LangGraph Studio)和监控功能(LangSmith)。NextJS是一个流行的Web应用程序框架。

## 技术选择

### 为什么选择LangGraph

LangGraph是一个用于构建基于LLM的状态化应用程序的库。它可以用于创建AI代理和多代理系统，或在LLM调用周围建立预定义的代码路径。该框架提供了对流程执行的低级控制，使用灵活。在LangGraph中，您定义图形，其中节点本质上是包含自定义代码的函数。然后，您在这些节点之间建立边缘连接。图形有一个状态，它只是一个键值对字典，在每个节点执行后更新。

### 为什么选择Next.js

Next.js是一个优秀的全栈框架，提供了构建现代Web应用程序所需的一切功能：

-   **服务器端渲染(SSR)**：通过在将页面发送到客户端之前在服务器上渲染页面，提高SEO和性能。
-   **静态站点生成(SSG)**：允许在构建时预渲染页面，从而缩短加载时间。
-   **API路由**：通过允许在同一应用程序中创建API端点，简化后端集成。
-   **自动代码分割**：只加载正在访问的页面所需的JavaScript，提高性能。
-   **基于文件的路由**：通过使用文件系统简化路由，使创建和管理路由变得容易。
-   **内置CSS和Sass支持**：无需额外配置即可支持全局和模块化CSS以及Sass。
-   **图像优化**：自动优化图像以提高性能和用户体验。
-   **丰富的生态系统**：与React良好集成，拥有庞大的社区和插件工具生态系统。

## Agent集成机制

### 图执行与检查点

首先，让我们探讨图（AI代理）执行的含义。LangGraph在应用执行前、每个图节点执行前以及应用执行后创建检查点（checkpoints）。检查点本质上是图状态的快照，指示下一步将执行哪个节点或哪些节点。

检查点机制是LangGraph的核心特性之一，它允许：
-   保存执行历史，便于回溯和调试
-   在任意点暂停和恢复执行
-   从特定状态创建分支执行
-   实现人机交互循环

在客户端应用中，我们需要复制这种架构以获得完全控制并访问图执行数据。这种逻辑封装在`useLangGraphAgent`钩子中，它调用AI服务API并在客户端同步代理状态。

### useLangGraphAgent钩子

`useLangGraphAgent`钩子是前端与LangGraph后端集成的核心。它提供了以下功能：

**属性：**
-   `status`：指示代理的执行状态（idle、running、stopping、error）
-   `appCheckpoints`：图检查点和节点及其状态的列表

**方法：**
-   `run`：使用提供的状态执行代理
-   `resume`：人机交互后继续代理执行
-   `restore`：检索特定代理线程的检查点历史
-   `replay`：从检查点重新执行代理
-   `fork`：使用自定义状态创建检查点的分支并运行代理
-   `stop`：停止正在执行的代理

### 客户端状态同步

钩子通过以下机制与后端同步：

1.  **SSE流处理**：使用Server-Sent Events接收来自LangGraph的实时更新
2.  **事件类型处理**：
    -   `checkpoint`：处理新的检查点和状态更新
    -   `message_chunk`：处理LLM生成的消息片段
    -   `interrupt`：处理需要人机交互的中断
    -   `custom`：处理自定义状态更新
    -   `error`：处理执行错误

3.  **状态差异计算**：计算状态变化以优化UI更新

## 功能特性

-   **多 Agent 示例:** 演示了不同的 Agent 架构，当前包括：
    -   **ReAct Agent:** 一个通用的助手，使用 ReAct 框架进行规划和工具使用。
    -   **Deep Research Agent:** 一个专门用于执行深度研究任务的助手。
-   **流式响应**：代理将LLM生成的内容实时流式传输到客户端应用程序。
-   **生成式UI**：基于代理状态渲染组件，例如天气小部件。
-   **人机交互**：代理可以向用户请求澄清以继续任务，例如确认创建提醒。
-   **状态持久化**：LangGraph具有内置的持久层。它可用于在会话之间持久保存代理状态。在演示应用中，状态保存在内存中。参见[LangGraph持久化](https://langchain-ai.github.io/langgraph/docs/how-tos/persistence/)了解如何使用PostgreSQL或MongoDB。
-   **回复和分支**：可以从任何检查点回复或分支代理。
-   **代理状态复制**：基于图检查点，代理状态在客户端完全复制。
-   **错误处理**：应用程序显示全局代理错误（例如代理不可访问时）以及图节点级别发生的错误。
-   **停止代理**：可以停止代理执行并稍后恢复。
-   **无依赖**：集成不依赖第三方库。您可以根据需要进行调整。
-   **简洁UI**：应用程序基于shadcn组件，支持深色和浅色主题。

## 项目架构

项目分为两个主要部分：

### 1. API服务器 (FastAPI + LangGraph)

位于`/api`目录，包含：
-   `server.py`：FastAPI服务器，提供与LangGraph交互的端点。负责加载和路由到正确的 Agent 图。
-   `agent/` 目录：包含 LangGraph Agent 图的定义。这可能包括为 **ReAct Agent** 和 **Deep Research Agent** 配置或定义的独立模块（例如 `react_graph.py`, `research_graph.py` 或一个可配置的 `graph_factory.py`）。
-   `utils.py`：用于格式化事件和状态的工具函数。

### 2. Web客户端 (NextJS)

位于`/web`目录（或项目根目录，取决于您的结构），包含：
-   `app/`：NextJS应用程序页面和路由。包括用于不同 Agent 类型（如 `app/default/[id]/page.tsx` 和 `app/deep_research/[id]/page.tsx`）的动态路由。
-   `hooks/useLangGraphAgent/`：与LangGraph代理交互的React钩子。
-   `components/`：UI组件，包括 Sidebar 和 Agent 交互界面。
-   `stores/`：使用Zustand的状态管理 (`chat-store.ts`)，用于存储聊天会话列表及其关联的 Agent 类型。

## 技术实现细节

### LangGraph与Next.js的集成

LangGraph是Python框架，而Next.js是JavaScript框架，这使得直接集成变得复杂。我们的解决方案包括：

1.  **FastAPI中间层**：创建一个FastAPI服务器作为中间层，暴露LangGraph功能为REST API。
2.  **SSE（Server-Sent Events）**：使用SSE实现从服务器到客户端的实时数据流。
3.  **状态同步机制**：在客户端复制和维护LangGraph的状态。

### 关键API端点

-   `/agent`：运行代理，支持多种操作模式（run、resume、fork、replay）。服务器端会根据请求路由到正确的 Agent 图。
-   `/history`：获取完整的状态历史，用于恢复图执行。
-   `/state`：获取当前图状态。
-   `/agent/stop`：停止正在运行的代理。

### 数据流程

1.  **客户端请求**：通过 `useLangGraphAgent` 钩子或直接 API 调用发起请求，指定要交互的 Agent。
2.  **服务器处理**：FastAPI 服务器接收请求，加载相应的 LangGraph Agent 图并开始执行。
3.  **流式响应**：服务器通过 SSE 流式传输执行结果（检查点、消息、中断等）。
4.  **客户端处理**：客户端解析事件流并更新本地状态 (`useLangGraphAgent` 钩子内部)。
5.  **UI渲染**：基于更新的状态渲染 UI 组件（聊天消息、状态指示器等）。

### 状态管理

LangGraph的状态是一个键值对字典，在每个节点执行后更新。在客户端，我们使用以下机制管理状态：

1.  **`useChatStore` (Zustand)**：存储聊天会话列表，每个会话包含 `id`, `name`, `agentId`, `agentName` 等信息。
2.  **`useLangGraphAgent` Hook State**：钩子内部维护当前活动 Agent 的检查点 (`appCheckpoints`) 和执行状态 (`status`)。
3.  **事件处理**：钩子处理来自 SSE 的不同类型的事件（checkpoint、message_chunk、interrupt、custom、error）以更新其内部状态。

## 限制

目前有一些尚未实现的功能：

-   并行节点中的图中断（人机交互）
-   从同一并行节点发送自定义事件。例如，同时检查多个城市的天气时，无法在客户端区分它们。
-   Deep Research Agent 的前端渲染机制可能需要根据具体输出进行优化。

## 安装和运行

### 安装依赖

#### API服务器

```bash
# Navigate to your API directory if needed
# cd api/
uv sync # 或者 pip install -r requirements.txt
```

#### Web客户端

```bash
# Navigate to your web client directory if needed (e.g., cd web/)
npm install # 或者 pnpm install 或 yarn install
```

### 环境变量

1.  在项目根目录或 API 服务器目录创建 `.env` 文件（参考 `.env.example`）。
2.  添加必要的API密钥，例如：
    ```
    OPENAI_API_KEY=your_openai_api_key
    # LANGCHAIN_TRACING_V2=true (可选, 用于 LangSmith)
    # LANGCHAIN_API_KEY=your_langsmith_api_key (可选, 用于 LangSmith)
    ```

### 运行项目

#### 启动API服务器

```bash
# Navigate to your API directory if needed
# cd api/
uv run python -m api.server # 或者 python -m api.server
```

API 服务器通常运行在 `http://localhost:8001` (或您配置的端口)。

#### 启动Web客户端

```bash
# Navigate to your web client directory if needed (e.g., cd web/)
pnpm run dev # 或者 npm run dev 或 yarn dev
```

Web 应用程序将在 `http://localhost:3000` 启动。

## 开发指南

### 调整AI代理逻辑

1.  修改 `api/agent/` 目录下相关的 Agent 图定义文件（例如，调整现有 **ReAct Agent** 或 **Deep Research Agent** 的逻辑）。
2.  或者创建一个全新的 Agent 图文件。
3.  确保 `api/server.py` 中的加载和路由逻辑能够识别并调用你的新 Agent 或修改后的 Agent。

### 调整代理状态类型

1.  如果 Agent 的状态结构发生变化，相应地在 `web/app/[agentId]/[id]/page.tsx` (或相关的类型定义文件，如 `agent-types.ts`) 中修改 TypeScript 类型定义。

### 在客户端应用中调用代理

在相关的页面组件 (例如 `app/default/[id]/page.tsx` 或 `app/deep_research/[id]/page.tsx`) 中使用 `useLangGraphAgent` 钩子：

```tsx
import { useLangGraphAgent } from '@/hooks/useLangGraphAgent/useLangGraphAgent';
// Import specific state types for the agent being used
import { AgentState, InterruptValue, ResumeValue } from './agent-types'; // Adjust path as needed

export default function AgentPage({ params }: { params: { id: string } }) {
  const thread_id = params.id; // Get thread_id from route

  const { status, appCheckpoints, run, resume, replay, restore } =
    useLangGraphAgent<AgentState, InterruptValue, ResumeValue>(thread_id); // Pass thread_id

  // 使用钩子方法与代理交互
  // 例如，在组件加载时恢复历史记录:
  // React.useEffect(() => {
  //   restore();
  // }, [restore]);

  // ... rest of your component logic ...
}
```

## 路线图

### 短期目标

1.  **改进错误处理**
    -   实现更详细的错误消息
    -   添加重试机制
2.  **增强UI组件**
    -   为 Deep Research Agent 的输出提供更丰富的渲染组件
    -   改进移动端响应式设计
3.  **添加认证 (可选)**
    -   实现基本的用户认证
    -   添加会话管理

### 中期目标

1.  **持久化存储**
    -   为 LangGraph 检查点集成 PostgreSQL 或 MongoDB
    -   为用户聊天列表添加持久化
2.  **并行节点改进**
    -   实现并行节点中的人机交互
    -   支持从并行节点发送自定义事件
3.  **工具集成**
    -   为 ReAct Agent 添加更多实用的工具
    -   为 Deep Research Agent 集成更多数据源

### 长期目标

1.  **多代理支持**
    -   实现多个协作代理的示例
    -   添加代理间通信的可视化
2.  **高级UI功能**
    -   探索可视化图构建/调试工具集成
3.  **企业功能**
    -   添加团队协作功能
    -   实现角色和权限管理
    -   添加审计和日志记录

## 贡献

欢迎贡献！请随时提交问题或拉取请求。

## 许可

[MIT](LICENSE)