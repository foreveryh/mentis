# Mentis Multi-Agent Framework

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) 
## 概述 (Overview)

Mentis 是一个基于 LangGraph 构建的、可扩展的多 Agent (Multi-Agent) 协作框架。它的核心是一个**状态驱动的规划型 Supervisor Agent**，负责理解用户复杂请求、制定执行计划，并智能地协调一组具有不同专业能力的子 Agent (Specialist Agents) 来共同完成任务。

此框架旨在实现复杂任务的自动化处理，通过 Agent 间的协作提供比单一 Agent 更强大、更灵活的问题解决能力。

## 核心特性 (Core Features)

* **Multi-Agent 架构**: 采用中心化的 Supervisor 协调多个专门的子 Agent (如 Research, Coder, Reporter, Designer, Data Analyst)。
* **State-Based Planning**: 引入独立的 `Planner` 节点负责初始规划，`Supervisor` 专注于基于计划状态的执行和调度，`Evaluator` 节点负责评估子 Agent 结果并更新状态。计划状态通过 LangGraph 持久化（需配置 Checkpointer）。
* **模块化 Agent 设计**: 基于 `BaseAgent` 和 `ReactAgent` 构建，易于添加或修改具有不同能力的子 Agent。
* **工具注册与管理**: 通过 `core/tools/registry.py` 实现工具的集中注册、分类和动态加载。
* **可配置 LLM**: 支持通过 `LLMManager` (或环境变量) 配置和切换不同的 LLM Provider (OpenAI, DeepSeek, XAI Grok via compatible endpoint) 和模型。
* **持久化支持**: 基于 LangGraph 的 Checkpointer 机制，可以实现对话状态和计划的持久化。
* **清晰的执行流程**: Planner -> Supervisor -> (Handoff -> Agent -> Evaluator -> Supervisor 循环) -> 最终输出/Reporter。

## 架构概览 (Architecture Overview)

1.  **用户请求 (Input)**: 用户通过入口点 (`main.py` 或 API) 提交任务请求。
2.  **规划节点 (Planner Node)**: 分析请求，生成一个包含任务步骤、建议 Agent 的初始计划 (`Plan`)，并更新到图状态 (`PlanningAgentState`)。
3.  **主管节点 (Supervisor Node)**: 接收带有计划的状态，根据计划状态和消息历史决定下一步行动：
    * 启动新任务 (标记 'in_progress')。
    * 委派 'in_progress' 的任务给合适的子 Agent (通过 Handoff 工具)。
    * 等待子 Agent 完成。
    * 判断计划是否最终完成。
    * 决定最终输出方式（自己总结或调用 Reporter）。
4.  **切换执行器 (Handoff Executor)**: 处理 Supervisor 发出的 `transfer_to_` 工具调用，并将控制权和状态传递给目标子 Agent。
5.  **子 Agent 节点 (Specialist Agent Nodes)**: 继承自 `ReactAgent` 或 `BaseAgent`，执行具体的任务（研究、编码、生成报告/图像、数据分析），可能调用其自身的工具。
6.  **评估节点 (Evaluate Result Node)**: 接收子 Agent 的执行结果，进行确定性评估（成功/失败），更新对应任务的状态和 Plan 的整体状态。
7.  **循环与结束**: 流程在 Evaluator -> Supervisor 之间循环，直到 Supervisor 判断 Plan 完成，然后路由到 `END` 或 `ReporterAgent`。

## 快速开始 (Getting Started)

### 1. 环境设置 (Prerequisites)

* Python 3.11+
* 使用 `pip` 或 `uv` 等工具管理依赖。

### 2. 安装依赖 (Installation)

在项目根目录运行：
建议使用 uv 管理
```bash
uv venv
source .venv/bin/activate
uv sync
```

```bash
# pip install -r requirements.txt 
# 或者 uv pip install -r requirements.txt
```
(requirements.txt 我没维护，请确保 `requirements.txt` 文件包含了所有必要的库，如 `langchain`, `langgraph`, `langchain-openai`, `e2b` (如果使用 E2B), `replicate` (如果使用 Replicate), `tavily-python`, `exa-py`, `python-dotenv`, `anyio`, `tiktoken` 等)。

### 3. 配置环境 (Configuration)

* 复制 `.env.example` 文件为 `.env`。
* 在 `.env` 文件中填入您所需的 API Keys/Tokens：
    * `OPENAI_API_KEY` (如果使用 OpenAI 模型)
    * `DEEPSEEK_API_KEY` (如果使用 DeepSeek 模型)
    * `XAI_API_KEY` (如果使用 XAI Grok，并确认 Base URL)
    * `REPLICATE_API_TOKEN` (如果使用 Replicate 工具)
    * `E2B_API_KEY` (如果使用 E2B Code Interpreter，推荐！)
    * `TAVILY_API_KEY` (如果使用 Tavily 搜索，推荐！)
    * `EXA_API_KEY` (如果使用 Exa 搜索)
    * `LANGCHAIN_TRACING_V2="true"` (强烈推荐，用于 LangSmith 调试)
    * `LANGCHAIN_API_KEY="ls_..."` (您的 LangSmith Key)
    * `LANGCHAIN_PROJECT="Your_Project_Name"` (您在 LangSmith 上的项目名)
* **LLM 配置**:
    * 如果您使用了 `LLMManager`（如示例所示），请检查并配置其读取的模型配置文件（例如 `config/models.yaml`，路径可能不同）。
    * 如果您在 `tools.py` 中直接根据环境变量初始化 LLM，请确保设置了对应的环境变量，如 `LLM_PROVIDER`, `LLM_MODEL_NAME`, `LLM_BASE_URL` (用于兼容 API)。
* **工具配置**: 确保 `core/tools/__init__.py` 或 `registry.py` 中的工具预注册逻辑能够正确找到并初始化您需要的工具。

### 4. 运行示例 (Running Examples)

项目包含示例脚本以演示框架的使用：
```bash
# 从项目根目录 (mentis/) 运行
python examples/state_based_supervisor_examples/03_multi_agents.py 
```
脚本会提示您输入初始请求。您可以进行简单尝试：

* `"What is the capital of France?"` (简单测试)
* `"Write a short, four-line poem about spring."` (测试 Reporter)
* `"Generate an image of a cat wearing a top hat, oil painting style."` (测试 Designer)
* `"Write a Python function to calculate factorial and run it for 5."` (测试 Coder)

## 项目结构 (Project Structure)

```
mentis/
├── api/             # (可选) API 服务相关代码
├── core/            # 核心框架代码
│   ├── agents/      # Agent 定义 (base, react, supervisor, sub-agents)
│   │   ├── base/
│   │   ├── state_based_supervisor/ # Supervisor 相关 (graph, node, planner, evaluator)
│   │   ├── sub_agents/             # 具体子 Agent 实现 (research, coder, etc.)
│   │   └── sb_supervisor_agent.py  # SupervisorAgent 类定义
│   ├── llm/         # (可选) LLM 管理或配置
│   ├── tools/       # 工具定义和注册表 (registry, e2b, replicate, etc.)
│   └── utils/       # 通用辅助函数
├── examples/        # 示例和测试脚本
│   └── state_based_supervisor_examples/
│       └── 03_multi_agents.py # 我们使用的测试脚本
├── web/             # (可选) Web 客户端代码
├── .env.example     # 环境变量示例
├── requirements.txt # Python 依赖
└── README.md        # 本文件
```

## Super Agents (独立功能型 Agent)

除了由 Supervisor 协调的、专注于单一技能的 Specialist Agents (如 Coder, Researcher) 之外，本框架也支持构建和集成更复杂的 **"Super Agents"**。

Super Agent 可以理解为一个**独立的、具有端到端能力、能够完成一个相对完整且复杂任务的 Agent 图**。它可以包含自己的规划、执行、甚至内部协调逻辑。

这些 Super Agents 既可以**独立运行**以完成特定的大型任务，也可以被更高层的协调者（例如我们的 Supervisor Agent）**视为一种强大的“能力”或“工具”**来调用，以处理其复杂计划中的某个步骤。

### DeepResearch Agent (第一个实例)


https://github.com/user-attachments/assets/2a685709-5be0-43a3-9e2d-934ef5fa3315


`DeepResearch Agent` 是我们在此框架理念下实现的第一个 Super Agent 实例（其早期版本是我们开发此 Multi-Agent 框架的基础）。

* **核心功能**: 旨在针对用户给定的**任意主题**，自动化地执行一个**深度研究**流程。
* **内部工作流**: 它包含自己的一套完整的内部步骤，大致如下：
    1.  **研究规划 (Plan Research)**: 分析主题，生成初步的搜索查询和分析点。
    2.  **多源搜索 (Multi-Source Search)**: 调用网页搜索 (Tavily)、学术搜索 (Exa) 等工具获取信息。
    3.  **(可选) 分析执行 (Perform Analysis)**: 对搜索结果进行初步分析（如情感、SWOT 等）。
    4.  **差距分析 (Gap Analysis)**: 评估已有信息，识别知识空白和局限性。
    5.  **(可选) 补充搜索 (Gap Filling)**: 针对知识空白进行额外的、更具针对性的搜索。
    6.  **最终综合 (Final Synthesis)**: 整合所有信息，提炼关键发现和不确定性。
    7.  **报告生成 (Report Generation)**: 将综合结果和上下文信息，撰写成一份详细的、带引用的 Markdown 研究报告。
* **当前状态**: 该 Agent 的核心逻辑和节点已基本实现（在我们之前的开发过程中）。

**如何体验 DeepResearch Agent (独立运行):**

(注意：以下步骤假设您保留了或可以恢复用于独立运行 DeepResearch Agent 的入口脚本，例如基于我们早期开发的 `main.py` 或创建一个新的 `run_deep_research.py`。您可能需要调整脚本以适应 `core` 代码库的最新更改。)

1.  **确保环境配置**: 确认您的 `.env` 文件中包含了 DeepResearch Agent 所需的所有 API Keys（例如 `OPENAI_API_KEY`/`DEEPSEEK_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`）。
2.  **找到/创建运行脚本**: 找到或创建一个专门用于启动 DeepResearch Agent 的 Python 脚本。
3.  **运行脚本**: 在项目根目录执行：
    ```bash
    python super_agents/deep_research/main.py
    ```
4.  **输入主题**: 根据提示输入您想研究的主题。
5.  **查看结果**: 等待 Agent 执行完毕，它生成的 Markdown 报告通常会保存在目录下的 `output/` 文件夹中。

## 未来工作 (Future Work / Contributing)

* 完善子 Agent 的工具集和 Prompt。
* 增强 Evaluator Node 的评估逻辑。
* 添加更复杂的任务依赖处理。
* 优化长对话历史的管理。
* 集成持久化 Checkpointer (如 SQLite, Redis)。
* 欢迎提出 Issue 或 Pull Request！
* 有问题也可以添加我的微信 brown🩷cony999


## 许可证 (License)

This project is licensed under the MIT License - see the LICENSE file for details.
