# LangGraph Agent 与 A2A 协议集成框架

## 概述

本项目提供了一个将 **LangGraph Agent**（特别是基于 ReAct 模式并能调用工具的 Agent）与 **A2A (Agent-to-Agent) 协议** 相集成的框架和示例。目标是展示如何将一个用 LangGraph 构建的复杂 Agent 能力，通过标准化的 A2A 接口暴露给外部客户端或其他 Agent。

此框架的核心在于 `AgentTaskManager`，它充当了 A2A 协议层与具体 Agent 实现之间的桥梁。项目包含了一个完整的端到端示例，其中 `CurrencyAgent`（使用 `create_react_agent` 构建，并带有计算器和搜索工具）通过 `A2AServer` 提供服务，并提供了两个不同的客户端示例 (`client_example.py` 和 `currency_agent_test.py`) 来演示如何与之交互。

关键技术栈包括：
* **A2A 协议:** 定义交互规范。
* **LangGraph:** 用于构建具备状态管理和工具调用能力的 Agent。
* **`create_react_agent`:** LangGraph 提供的预构建 ReAct Agent 实现（作为示例）。
* **Pydantic:** 用于定义和验证 A2A 协议中的数据结构 (`core/a2a/types.py`)。
* **Starlette/Uvicorn:** 作为底层 Web 框架运行 A2A 服务器 (`core/a2a/server/server.py`)。
* **OpenAI API:** 作为 LangGraph Agent 使用的后端大语言模型（可替换）。

## 特性

* **A2A 协议兼容:** 提供符合 A2A 规范的服务端点 (`/.well-known/agent.json` 和主任务端点)。
* **LangGraph Agent 集成:** 可将任意（满足特定接口要求的）LangGraph Agent 作为 A2A 服务的核心处理逻辑。
* **工具使用:** 集成的 Agent 能够根据需要调用外部工具（示例中为计算器和搜索）。
* **同步任务处理:** 支持客户端发送任务并等待最终结果。
* **流式基础:** 包含了处理流式请求和响应的框架（Agent 端流式逻辑需开发者实现）。
* **类型安全:** 使用 Pydantic 进行严格的数据校验。
* **环境配置:** 支持通过 `.env` 文件配置 API 密钥等敏感信息。
* **客户端示例:** 提供了基础和场景化的客户端示例代码。

## 目录结构

```
.
├── core/                           # 核心 A2A 协议实现
│   └── a2a/
│       ├── client/
│       │   └── client.py           # A2AClient 客户端库实现
│       ├── server/
│       │   ├── server.py           # A2AServer HTTP 服务器实现
│       │   └── task_manager.py     # TaskManager 基础接口 (被 AgentTaskManager 使用)
│       ├── agent_task_manager.py     # AgentTaskManager 实现 (连接 A2A 与 LangGraph)
│       └── types.py                # A2A 协议的 Pydantic 模型定义
├── examples/                       # 示例代码
│   └── a2a/
│       ├── langgraph_integration.py # 服务端设置和示例 LangGraph Agent (CurrencyAgent) 定义
│       ├── client_example.py          # 基础 A2A 客户端使用示例脚本
│       └── currency_agent_test.py     # 场景化 A2A 客户端测试脚本
├── .env                            # 存储环境变量 (例如 OPENAI_API_KEY) - *需要自行创建*
├── requirements.txt                # Python 依赖项列表 (假设存在)
└── README.md                       # 本文档
```

## 核心组件说明

* **`core/a2a/types.py`:** 定义所有 A2A 数据结构，是协议的基础和校验依据。
* **`core/a2a/server/server.py` (`A2AServer`):** 基于 Starlette 的 HTTP 服务器，处理 A2A JSON-RPC 请求路由，将请求交给 `AgentTaskManager`。通过 `.start()` 方法启动。
* **`core/a2a/agent_task_manager.py` (`AgentTaskManager`):** **核心适配器**。连接 A2A 层和 Agent 层。它接收来自 `A2AServer` 的请求，管理任务状态，并调用注入的 Agent 实例的 `invoke` 或 `stream` 方法。
* **`examples/a2a/langgraph_integration.py`:** 包含 `CurrencyAgent` (使用 `create_react_agent` 的示例 Agent) 的定义，以及如何配置和启动 `A2AServer` 来运行这个 Agent 的完整脚本。
* **`core/a2a/client/client.py` (`A2AClient`):** 基础 A2A 客户端库。
* **`examples/a2a/client_example.py`:** 一个简单的脚本，演示如何使用 `A2AClient` 发送基本请求。
* **`examples/a2a/currency_agent_test.py`:** 一个更复杂的客户端脚本，包含多个测试场景，用于测试服务器端 Agent 的不同交互模式。

## 先决条件

* Python (推荐 3.10 或更高版本)
* `pip` (Python 包安装器)
* 虚拟环境 (强烈推荐)
* 大语言模型 API Key (例如 OpenAI API Key)

## 安装与设置

1.  **克隆仓库:**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-directory>
    ```
2.  **创建并激活虚拟环境:**
    ```bash
    uv venv
    source .venv/bin/activate
    ```
3.  **安装依赖项:**
    ```bash
    uv sync
    ```
4.  **设置环境变量:**
    * 在项目根目录下创建 `.env` 文件。
    * 添加所需的 API Key，例如：
        ```dotenv
        OPENAI_API_KEY="sk-..."
        ```

## 运行示例

1.  **启动 A2A 服务器:**
    * 在终端中，激活虚拟环境后运行：
        ```bash
        python -m examples.a2a.langgraph_integration
        ```
    * 服务器将在 `http://127.0.0.1:8000` 启动并监听。

2.  **运行 A2A 客户端:**
    * 打开**新的**终端，激活虚拟环境。
    * 你可以选择运行任一客户端示例：
        * **基础示例:**
            ```bash
            python -m examples.a2a.client_example
            ```
        * **场景化测试:**
            ```bash
            python -m examples.a2a.currency_agent_test
            ```

3.  **预期输出:**
    * **服务器终端**会显示接收请求、调用 LLM 和工具（如果被触发）的日志。
    * **客户端终端**会显示发送任务、轮询状态（对于同步任务）、接收结果或（模拟的）流式事件的输出。`currency_agent_test.py` 会按场景输出结果。

---

## **重要：集成新的 LangGraph Agent 指南**

如果你创建了一个新的基于 LangGraph 的 Agent，并希望将其接入到这个 A2A 框架中，你需要遵循以下步骤和约定：

### 1. Agent 类必须实现的接口

你的新 Agent 类（例如 `MyNewAgent`）需要被 `AgentTaskManager` 调用。为此，它**必须**实现以下方法和属性：

* **`__init__(self, llm, ...)`:**
    * 构造函数，用于初始化 Agent 所需的资源，例如 LLM 实例、工具列表等。
    * **关键:** 在这里构建或获取你的 LangGraph **Runnable** 实例（例如通过 `create_react_agent` 或手动构建 `StateGraph().compile()`），并将其存储为类的成员（例如 `self.agent_runnable`）。

* **`invoke(self, query: str, session_id: Optional[str] = None) -> str:`**
    * 处理 A2A 的**同步** `tasks/send` 请求。
    * 接收从 `AgentTaskManager` 传递过来的纯文本用户查询 `query` 和可选的 `session_id`。
    * **内部逻辑:**
        * 将 `query` 包装成你的 LangGraph Runnable 所需的输入格式。对于基于 `create_react_agent` 或类似使用消息列表的 Agent，通常是 `{"messages": [("user", query)]}`。如果需要 `session_id`，也应包含在内。
        * 调用 LangGraph Runnable 的 `.invoke()` 方法，传入构造好的输入字典。
        * 处理 Runnable 返回的结果字典。对于 ReAct Agent，最终的文本答案通常位于结果字典内 `messages` 列表的最后一条消息的内容中。你需要编写逻辑来提取这个最终答案。
    * **返回值:** **必须**返回一个包含最终答案的**字符串**。

* **`stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:`**
    * 处理 A2A 的**流式** `tasks/sendSubscribe` 请求。
    * 接收 `query` 和 `session_id`。
    * **必须**是一个**异步生成器** (`async def` 包含 `yield`)。
    * **内部逻辑:**
        * 准备 LangGraph Runnable 流式调用所需的输入（通常与 `invoke` 类似，例如 `{"messages": [("user", query)]}`）。
        * 调用 LangGraph Runnable 的流式方法，例如 `self.agent_runnable.astream(...)` 或 `self.agent_runnable.astream_log(...)`。
        * 使用 `async for chunk in ...:` 迭代 LangGraph Runnable 返回的流式数据块 (`chunk`)。
        * **解析 `chunk`**: LangGraph 流式输出的 `chunk` 格式取决于你调用的方法（`astream` vs `astream_log`）和图的结构。你需要解析这些 `chunk`（可能是状态变更、日志补丁等）来获取有意义的中间或最终内容。
        * **`yield` 符合格式的字典**: 对于每个希望发送给客户端的更新，你需要 `yield` 一个字典。这个字典**必须**包含以下键（供 `AgentTaskManager._run_streaming_agent` 使用）：
            * `"content"`: `str` - 当前步骤生成的文本内容。
            * `"is_task_complete"`: `bool` - 指示这是否是任务的最终产物/结束信号。
            * `"require_user_input"`: `bool` - 指示任务是否暂停并需要用户输入。
    * **返回值:** 返回一个异步可迭代对象（由 `async def` + `yield` 自动创建）。

* **`SUPPORTED_CONTENT_TYPES: List[str]` (类属性):**
    * 一个包含 Agent 支持的输出内容类型的列表。对于主要处理文本的 Agent，通常是 `["text"]`。`AgentTaskManager` 会用它来验证客户端请求的 `acceptedOutputModes`。

### 2. `AgentState` 的一致性

如果你手动构建 LangGraph 图，你定义的 `AgentState`（传递给 `StateGraph`）需要与你的 `invoke` 和 `stream` 方法处理输入/输出的方式保持一致。特别是，如果你依赖 `messages` 列表来管理对话历史或传递输入/输出，`AgentState` 中需要正确定义它。

### 3. 集成步骤

1.  **创建 Agent 类:**
    * 在你的项目中创建一个新的 Python 文件（例如 `my_new_agent.py`）。
    * 定义你的 Agent 类（例如 `MyNewAgent`），确保它实现了上面描述的 `__init__`, `invoke`, `stream` 方法和 `SUPPORTED_CONTENT_TYPES` 属性。
    * 在 `__init__` 中构建或加载你的 LangGraph Runnable。

2.  **修改服务器启动脚本 (例如 `examples/a2a/langgraph_integration.py`):**
    * **导入**你的新 Agent 类：`from my_new_agent import MyNewAgent`。
    * **实例化**你的新 Agent：`my_agent = MyNewAgent(llm)` (确保传递了所需的依赖，如 `llm`)。
    * **更新 `AgentCard`**: 修改 `name`, `description` 和 `skills` 列表以反映新 Agent 的信息。确保 `AgentSkill` 具有唯一的 `id` 和正确的 `name`。
    * **实例化 `AgentTaskManager`**: 使用你的新 Agent 实例：`task_manager = AgentTaskManager(my_agent)`。
    * **实例化 `A2AServer`**: 使用更新后的 `agent_card` 和 `task_manager`。

3.  **运行服务器:**
    * 启动修改后的服务器脚本：`python -m examples.a2a.your_server_script`。

4.  **测试:**
    * 使用 `client_example.py` 或 `currency_agent_test.py`（可能需要修改发送的查询或 `metadata` 中的 `skill_name`）来向新启动的服务器发送请求，验证你的新 Agent 是否能通过 A2A 协议正常工作。

### 示例 Agent 骨架

```python
# my_new_agent.py
import logging
from typing import List, Optional, AsyncIterable, Dict, Any, Tuple
from langchain_core.language_models import BaseChatModel # 示例 LLM 类型
from langgraph.graph.state import StateGraph # 如果手动构建图
# from langgraph.prebuilt import create_some_agent # 如果使用预构建
from typing import TypedDict

logger = logging.getLogger(__name__)

# 1. 定义你 Agent 使用的 State (如果需要)
class MyAgentState(TypedDict):
    messages: List[Tuple[str, str]]
    # ... 其他状态字段

class MyNewAgent:
    SUPPORTED_CONTENT_TYPES: List[str] = ["text"]

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        # TODO: 在这里构建或加载你的 LangGraph Runnable
        # 例如: self.agent_runnable = self._build_my_graph()
        # 或者: self.agent_runnable = create_some_agent(llm, tools)
        self.agent_runnable = self._get_placeholder_runnable() # 示例
        logger.info("MyNewAgent initialized.")

    def _get_placeholder_runnable(self):
        # 这是一个模拟的 Runnable，你需要替换成真实的 LangGraph Runnable
        class PlaceholderRunnable:
            def invoke(self, input_dict):
                logger.info(f"PlaceholderRunnable received invoke: {input_dict}")
                query = input_dict.get("messages", [("", "")])[-1][1]
                return {"messages": [("assistant", f"模拟回应 '{query}'")]}
            async def astream(self, input_dict):
                logger.info(f"PlaceholderRunnable received astream: {input_dict}")
                query = input_dict.get("messages", [("", "")])[-1][1]
                yield {"messages": [("assistant", f"模拟流式回应1 '{query}' ...")]}
                await asyncio.sleep(0.5)
                yield {"messages": [("assistant", f"模拟流式回应2 '{query}' 完毕。")]}
        return PlaceholderRunnable()

    # def _build_my_graph(self):
    #     # 如果你手动构建图，在这里实现
    #     # workflow = StateGraph(MyAgentState)
    #     # ... add nodes, edges ...
    #     # return workflow.compile()
    #     pass

    def invoke(self, query: str, session_id: Optional[str] = None) -> str:
        logger.debug(f"[MyNewAgent.invoke] query: '{query}', session_id: '{session_id}'")
        # 1. 准备输入
        invoke_input = {"messages": [("user", query)]}
        # 2. 调用 Runnable
        try:
            result = self.agent_runnable.invoke(invoke_input)
            logger.debug(f"[MyNewAgent.invoke] Runnable result: {result}")
            # 3. 解析结果
            final_output = "错误：未能解析 Agent 响应。"
            if isinstance(result, dict) and isinstance(result.get("messages"), list) and result["messages"]:
                 last_message = result["messages"][-1]
                 if isinstance(last_message, tuple) and len(last_message) == 2:
                     final_output = last_message[1]
                 elif hasattr(last_message, 'content'):
                      final_output = last_message.content
            return str(final_output)
        except Exception as e:
            logger.error(f"[MyNewAgent.invoke] Error: {e}", exc_info=True)
            raise # 重新抛出异常，让 TaskManager 处理

    async def stream(self, query: str, session_id: Optional[str] = None) -> AsyncIterable[Dict[str, Any]]:
        logger.debug(f"[MyNewAgent.stream] query: '{query}', session_id: '{session_id}'")
        # 1. 准备输入
        stream_input = {"messages": [("user", query)]}
        # 2. 调用 Runnable 的流式方法
        try:
            # 使用 astream 或 astream_log
            async for chunk in self.agent_runnable.astream(stream_input):
                logger.debug(f"[MyNewAgent.stream] Received chunk: {chunk}")
                # 3. 解析 chunk 并 yield 符合格式的字典
                #    这里的解析逻辑高度依赖于你的图和使用的流式方法
                #    你需要根据实际的 chunk 内容提取 content, is_task_complete, require_user_input
                # --- 这是一个 **高度简化** 的示例解析 ---
                content_to_yield = ""
                is_complete = False # 你需要根据 chunk 判断任务是否真的结束
                is_input_required = False # 你需要根据 chunk 判断是否需要输入

                # 尝试从 chunk 中提取 'messages' 的最新内容作为 content
                if isinstance(chunk, dict) and isinstance(chunk.get("messages"), list) and chunk["messages"]:
                    last_message = chunk["messages"][-1]
                    if isinstance(last_message, tuple) and len(last_message) == 2:
                        content_to_yield = last_message[1]
                    elif hasattr(last_message, 'content'):
                        content_to_yield = last_message.content

                if content_to_yield: # 只在有内容时 yield
                    # 在实际应用中，你需要更复杂的逻辑判断 is_task_complete
                    # 例如，检查 LangGraph 图是否到达了 END 节点，或者某个特定的最终节点状态
                    # is_complete = ???
                    yield {
                        "content": content_to_yield,
                        "is_task_complete": is_complete, # 需要正确设置
                        "require_user_input": is_input_required # 需要正确设置
                    }
                # --- 简化示例结束 ---

            # **重要**: 在循环结束后，如果任务确实完成了，需要再 yield 一个最终状态
            # (除非上面的循环中最后一个 yield 的 is_task_complete 已经是 True)
            # 例如:
            # final_result = await self.agent_runnable.ainvoke(stream_input) # 可能需要再调用一次 invoke 获取最终确认状态
            # final_text = ... # 解析最终文本
            # yield {"content": final_text, "is_task_complete": True, "require_user_input": False}

        except Exception as e:
            logger.error(f"[MyNewAgent.stream] Error: {e}", exc_info=True)
            # 在流中抛出异常可能会中断 SSE 连接，或者你可以 yield 一个错误信息
            yield {
                "content": f"处理流式请求时出错: {e}",
                "is_task_complete": True, # 标记任务失败并结束
                "require_user_input": False
            }
```

## 当前状态与限制

* 同步任务执行，包括 LangGraph Agent 调用 LLM 和工具，已成功实现并验证。
* A2A 协议的服务端和客户端基础结构已建立。
* **Agent 端的流式处理 (`CurrencyAgent.stream`) 目前是模拟的**，并未真正调用 LangGraph 的流式接口。真实的流式更新尚未实现。
* 当前 Agent 实现 (`CurrencyAgent`) 不支持需要跨请求保持状态的多轮对话澄清。
* 错误处理可以进一步增强。
* 任务存储仅在内存中 (`InMemoryTaskManager`)。

## 未来方向

* **实现真实流式输出:** 按照上述指南，在 Agent 类中实现 `stream` 方法，调用 LangGraph 的 `astream` 或 `astream_log`，并正确解析和 `yield` A2A 所需格式的字典。
* **支持多轮对话:** 修改 `AgentState` 以包含可累加的消息历史 (例如使用 `Annotated[List[BaseMessage], operator.add]`)，并调整 Agent 的 `invoke` 和 `stream` 方法以处理和利用这个历史记录。可能还需要 Agent 能返回 `input-required` 状态。
* **增强错误处理:** 为网络问题、Agent 执行错误、工具调用失败、类型验证错误等提供更详细、用户友好的错误报告。
* **持久化任务存储:** 替换 `InMemoryTaskManager`。
* **配置管理:** 外部化配置。
* **多技能支持:** 添加路由逻辑。
