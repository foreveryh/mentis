n# Browser Agent (基于 LangGraph) - super_agents/browser_use

## 概述

本项目实现了一个基于 LangGraph 框架的 Web 浏览和交互 Agent。其核心目标是让一个大型语言模型 (LLM) 能够像人一样理解任务指令，自主地控制浏览器（通过 Playwright）来访问网页、分析内容、与页面元素交互（点击、输入、滚动等），并最终完成用户指定的任务，例如信息提取、表单填写、在线搜索等。

该 Agent 采用了多模态感知的设计思路，结合了传统的 DOM/Accessibility Tree 分析和可选的视觉语言模型 (VLM) 分析，以期在复杂网页上获得更鲁棒的理解和定位能力。

## 核心技术栈

* **流程编排:** LangGraph (LangChain 的状态图编排库)
* **浏览器自动化:** Playwright (异步 Python 版本)
* **模型调用:** LangChain ChatModels (`langchain-openai`, `langchain-community` 等)
* **语言模型 (LLM/VLM):**
    * **规划/决策 LLM:** 可配置，支持 OpenAI, Groq, xAI (Grok), 及其他 OpenAI 兼容 API (通过 `llm.py` 和 `.env` 配置)。
    * **视觉分析 VLM:** 可选，通过 OpenRouter 调用支持 Vision 的模型 (如 Qwen-VL, GPT-4o, Claude 3.5 Sonnet 等) (通过 `detector.py` 和 `.env` 配置)。
* **依赖管理:** `uv` (或 `pip`)
* **配置:** `.env` 文件

## 项目架构

项目主要文件和目录结构如下：

```
super_agents/
└── browser_use/              # Agent 根目录
    ├── agent/                # LangGraph 核心实现
    │   ├── __init__.py
    │   ├── graph.py          # 定义 LangGraph 图结构、节点连接、条件边
    │   ├── nodes.py          # 定义图中各节点 (Node) 的具体执行逻辑 (AgentNodes 类)
    │   ├── state.py          # 定义 Agent 在图中流转的状态 (AgentState)
    │   ├── schemas.py        # 定义数据模型 (如动作指令 Action Schema, VLM 输出 Schema)
    │   └── prompts.py        # 管理发送给规划 LLM 和 VLM 的 Prompt 模板
    │
    ├── browser/              # 浏览器交互底层实现 (基于原始项目代码)
    │   ├── __init__.py
    │   ├── browser.py        # 核心 Browser 类，封装 Playwright 操作、感知方法 (get_content, update_state)
    │   ├── detector.py       # 视觉检测器类，实现 VLM 调用逻辑
    │   ├── models.py         # 定义浏览器状态、元素等 Pydantic 模型
    │   ├── utils.py          # 浏览器相关的工具函数
    │   └── findVisibleInteractiveElements.js # 用于 DOM 元素检测的 JS 脚本
    │
    ├── llm/                  # LLM 相关实现
    │   ├── __init__.py
    │   └── llm.py            # 定义 ChatOpenRouter (VLM 调用), initialize_llms (规划 LLM 初始化), generate_structured_output
    │
    ├── main.py               # Agent 的主入口脚本
    ├── requirements.txt      # Python 依赖列表
    ├── README.md             # 本文件
    └── .env                  # 环境变量配置文件 (需要手动创建)
```

## 核心概念与设计

### 1. LangGraph 状态机

Agent 的核心控制流由 LangGraph 管理。它被实现为一个状态机 (`StateGraph`)：

* **状态 (State):** `agent/state.py` 中的 `AgentState` (TypedDict) 定义了在节点间传递的数据，包含当前任务、浏览器内容/状态、LLM 解析出的动作、历史记录、错误信息等。
* **节点 (Nodes):** `agent/nodes.py` 中的 `AgentNodes` 类定义了主要的处理步骤，作为图的节点：
    * `get_browser_state`: 调用 `Browser` 类的感知方法 (当前是 `get_content`) 获取页面信息。
    * `plan_action`: 将感知信息和任务包装成 Prompt，调用**规划 LLM** (通过 `llm.py` 的 `generate_structured_output`) 获取结构化的下一步动作 JSON。
    * `execute_action`: 解析 `plan_action` 返回的动作 JSON，并调用 `Browser` 类中相应的交互方法 (如 `Maps_to`, `click`, `type`, `scroll`, `wait`) 执行操作。
* **边 (Edges):** `agent/graph.py` 定义了节点间的固定跳转（如 `get_browser_state` -> `plan_action`）和条件跳转（如 `execute_action` 后根据 `should_end` 函数判断是结束 `END` 还是回到 `get_browser_state`）。

### 2. 感知 (Perception)

Agent 通过 `browser.py` 中的 `Browser.get_content()` 方法（被 `get_browser_state` 节点调用）来理解当前网页状态。该方法整合了多种信息源，旨在为 LLM 提供丰富且相对简洁的页面表示：

* **简化 DOM:** 通过注入并执行 `SIMPLIFY_PAGE_SCRIPT` JavaScript，移除无关标签（脚本、样式等），提取关键交互元素及其属性，并为这些元素添加 `x-pw-id` 唯一标识。结果以伪 HTML 字符串形式返回。
* **可访问性树 (AX Tree):** (当前实现中暂时禁用/存在错误) 理论上通过 `page.accessibility.snapshot()` 获取页面的语义结构信息（角色、名称等），以 JSON 字符串形式返回。
* **视觉元素 (VLM):** (可选，需配置)
    * 如果 `.env` 文件中配置了 VLM (`OPENROUTER_API_KEY`, `VLM_API_MODEL`)，`get_content` 会调用 `Detector` 实例。
    * `Detector` (在 `browser/detector.py` 中) 使用 LangChain 的 `ChatOpenRouter` (在 `llm.py` 中定义) 调用配置的 VLM API。
    * 通过精心设计的 Prompt (`VLM_PROMPT_TEMPLATE`) 请求 VLM 返回页面交互元素的**描述、类型和边界框百分比坐标** (JSON 格式)。
    * `Detector` 解析 VLM 返回的 JSON，创建 `InteractiveElement` 对象列表（目前坐标是占位符）。
    * `get_content` 将这些视觉元素信息格式化为**文本摘要** (包含 VLM 分配的 ID 和边界框信息)。
* **合并与截断:** `get_content` 将 URL、简化 DOM、AX Tree (如果成功)、视觉元素摘要合并为一个长的文本字符串，并在超过 `max_length` 时进行截断，最后返回给 `plan_action` 节点。

### 3. 规划 (Planning)

* `plan_action` 节点接收 `get_content` 返回的**混合文本字符串**。
* `agent/prompts.py` 中的 `create_agent_prompt` 函数将任务描述、历史记录、错误信息（如果有）和这段混合文本整合成一个 Prompt。
* 该 Prompt 被发送给**规划 LLM**（通过 `llm.py` 中的 `generate_structured_output` 函数，该函数使用 LangChain 的 `.with_structured_output()` 功能）。
* LLM 被要求分析输入信息，决定下一步动作，并**严格按照 `agent/schemas.py` 中定义的 `LLMResponse` Pydantic 模型返回一个包含具体动作指令的 JSON**。Prompt 中包含了对生成**健壮 CSS 选择器**（优先使用稳定 ID、aria-label、文本内容，结合 `x-pw-id`）的明确指导。

### 4. 行动 (Action Execution)

* `execute_action` 节点接收规划 LLM 返回的结构化动作 JSON (存储在 `state['parsed_action']`)。
* 它解析出动作类型 (`type`) 和参数 (`selector`, `url`, `text`, `direction` 等)。
* 根据动作类型，调用 `browser/browser.py` 中 `Browser` 类对应的**简单交互方法**:
    * `Maps_to(url)`
    * `click(selector)`
    * `type(selector, text)`
    * `scroll(direction)`
    * `wait(milliseconds)`
* 这些方法内部使用 Playwright 的 `page.goto`, `page.locator(...).click`, `page.locator(...).fill`, `page.evaluate(...)` 等函数执行实际的浏览器操作。
* 如果动作是 `finish` 或 `error`，图流程会根据 `graph.py` 中的 `should_end` 函数判断并终止。

## 安装与配置

1.  **环境:** 推荐使用 Python 3.10+。
2.  **依赖安装:**
    * 克隆项目。
    * 进入 `super_agents/browser_use/` 目录。
    * 创建并激活虚拟环境 (使用 uv):
        ```bash
        uv venv
        source .venv/bin/activate  # Linux/macOS
        # 或者 .venv\Scripts\activate # Windows
        ```
    * 安装依赖项 (使用 uv):
        ```bash
        uv sync
        ```
3.  **Playwright 浏览器:** 运行 `playwright install` (至少需要 `playwright install chromium`) 来下载浏览器驱动。
4.  **环境变量 (`.env` 文件):**
    * 在 `super_agents/browser_use/` 目录下创建一个名为 `.env` 的文件。
    * 参考我们之前讨论的 `.env` 示例，**至少需要配置**：
        * **规划 LLM:** 选择一个 Provider (如 `openai`), 设置 `LLM_PROVIDER`, `LLM_MODEL_NAME`, 以及对应的 API Key (如 `OPENAI_API_KEY`)。
        * **VLM (可选):** 如果要启用视觉分析，设置 `OPENROUTER_API_KEY` 和 `VLM_API_MODEL` (设置为 OpenRouter 上支持视觉的模型 ID，如 `openai/gpt-4.1`等)。
    * 确保 `.env` 文件被正确加载（`main.py` 和 `llm.py` 中包含 `load_dotenv()`）。

## 如何运行

1.  确保已完成安装和配置。
2.  激活虚拟环境。
3.  从 `super_agents/` 目录（即 `browser_use` 的**上级**目录）运行 `main.py`：

    ```bash
    # 基本运行
    python -m browser_use.main "您的任务描述"

    # 示例：访问 Hacker News 并获取导航栏信息
    python -m browser_use.main "访问 news.ycombinator.com，返回页面导航栏信息"

    # 示例：使用其他命令行参数（如果有定义，如下面的最大步骤数）
    python -m browser_use.main "您的任务描述" --max-steps 30
    ```

## 当前状态、局限性与未来工作

* **核心流程:** Agent 的基本 LangGraph 流程（感知-规划-行动循环）、浏览器操作（导航、点击、输入、滚动、等待）、规划 LLM 调用、可选的 VLM 调用**已经跑通**，能够完成一些多步骤的 Web 任务。
* **视觉集成 (部分):** VLM 调用流程已集成到 `Detector` 类并通过 `get_content` 触发（需配置 API Key 和 Model）。VLM 能够返回 JSON 格式的检测结果，并且可以被成功解析为内部数据结构 (`InteractiveElement`)。
* **局限性 & 待完善:**
    1.  **VLM 坐标处理:** VLM 返回的是百分比坐标，但在解析时 (`_parse_vlm_detections`) 目前使用的是**占位符像素坐标**。需要获取截图的实际尺寸，实现准确的百分比到像素的转换，才能真正利用视觉信息进行定位。
    2.  **动作执行方式:** 当前 `execute_action` 仍然**完全依赖规划 LLM 生成的 CSS 选择器**。尚未实现基于 VLM 的元素 ID 或坐标进行点击/输入的操作，这限制了视觉能力的实际应用，特别是在 CSS 选择器不可靠的复杂页面上。
    3.  **感知信息完整性:**
        * **内容截断:** `get_content` 方法返回的内容会因为 `max_length` 限制而被截断，影响需要完整页面信息的任务（如“摘录全文”）。需要增大 `max_length` 或实现更智能的内容提取/滚动策略。
        * **AX Tree 缺失:** 获取 Accessibility Tree 的代码目前被注释或存在错误，导致缺少重要的语义信息。需要修复 `page.accessibility.snapshot()` 调用。
    4.  **滚动策略:** 当前依靠 Prompt 指示 LLM 进行滚动。可能需要更鲁棒的机制来处理长页面，例如 Agent 内部判断是否需要滚动，或者让 LLM 能获取滚动状态信息。
    5.  **Pydantic V1 警告:** 调用规划 LLM 的 `with_structured_output` 时仍然出现 Pydantic V1 警告，建议保持 LangChain 相关库和 Pydantic 为最新版本。
    6.  **错误处理:** 当前错误处理相对简单（例如 VLM 解析失败直接跳过，执行错误直接终止图），可以增加更复杂的重试、回退或用户介入机制。
    7.  **VLM 稳定性:** VLM 能否稳定、准确地返回所需的 JSON 格式和边界框，高度依赖所选模型和 Prompt，可能需要进一步调优。

* **未来工作:**
    * 修复 AX Tree 获取。
    * 实现 VLM 百分比坐标到像素坐标的准确转换。
    * 增强 `execute_action` 和 `Browser` 类以支持基于坐标的交互。
    * 优化 Prompt，指导 LLM 输出 VLM 元素 ID 或在 CSS 选择器失败时提供坐标作为备选。
    * 实现更智能的滚动策略以处理长页面和完整内容提取。
    * 持续更新依赖库，解决 Pydantic 警告。
    * 增强错误处理和恢复能力。