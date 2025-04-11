# Mentis MCP 客户端与配置指南

本目录 (`core/mcp/`) 包含用于与模型上下文协议 (MCP - Model Context Protocol) 服务器进行交互的 Python 客户端实现。

## 背景

MCP 旨在为 AI 模型（如 LLM Agent）提供一个标准的、与外部工具或服务进行交互的协议。本客户端的目标是提供一种灵活、可配置的方式来连接这些 MCP 服务器，并将它们提供的工具集成到 LangChain Agent 中。

## 客户端 (`MCPClient`)

核心实现是 `MCPClient` 类 (位于 `client.py`)，它具备以下特性：

* **配置驱动:** 通过读取一个位于 `core/mcp/config.json` 的 JSON 文件来管理一个或多个服务器的连接/启动信息。兼容 "Cursor 风格" 的配置格式。
* **灵活连接:**
    * **启动本地服务 (stdio):** 如果配置文件中提供了 `command` 和 `args`，客户端会尝试执行该命令启动服务器进程，并通过 **STDIO** 建立通信。这对于使用 `uvx` 或 `python -m` 启动的标准 MCP 服务器很有用。
    * **连接远程服务 (sse):** 如果配置文件中提供了 `url`，客户端会直接通过 **SSE** 连接到该 URL 对应的、已在运行的 MCP 服务器。
* **异步架构:** 基于 `asyncio` 构建，适合异步应用。
* **健壮的资源管理:** 使用 `contextlib.AsyncExitStack` 管理连接和会话，旨在提高关闭时的稳定性。
* **LangChain 集成支持:** 提供了加载 MCP 工具为 LangChain `BaseTool` 对象的基础（尽管存在适配器问题，见下文）。

## 如何使用

### 1. 配置服务器 (`core/mcp/config.json`)

你需要在此目录下创建一个 `config.json` 文件，定义你想要连接的 MCP 服务器。文件是一个 JSON 对象，键是服务器的逻辑名称，值是该服务器的配置详情。

**示例 `config.json` (只包含外部标准服务器):**

```json
{
  "fetch_via_uvx": {
    "id": "fetch-uvx-stdio",
    "type": "mcp-server",
    "description": "Fetch Server launched by uvx via stdio",
    "connection": {
      "transport": "stdio",
      "command": "uvx",
      "args": [ "mcp-server-fetch" ],
      "timeout": 45
    }
  },
  "everything": {
    "id": "everything-stdio",
    "type": "mcp-server",
    "description": "Everything Server launched by npx via stdio",
    "connection": {
      "transport": "stdio",
      "command": "npx",
      "args": [ "-y", "@modelcontextprotocol/server-everything" ],
      "env": {
        // 如果 Everything Server 需要 API Keys, 在此添加
        // 或确保运行客户端脚本的环境变量会被继承
        // "OPENAI_API_KEY": "YOUR_KEY",
        // "TAVILY_API_KEY": "YOUR_KEY"
      },
      "timeout": 60
    }
  },
  "external_sse_example": {
    "id": "external-sse",
    "type": "mcp-server",
    "description": "Connect to a pre-running SSE server (Example)",
    "connection": {
        "transport": "sse",
        "url": "http://localhost:9001/sse" // 假设有服务器在此运行
    }
  }
}
```

**重要:**

* 使用 `command` 启动服务器时，确保 `command` (如 `uvx`, `npx`, `python`) 在你的环境中可用。
* 如果服务器需要 API Keys，请通过 `env` 字段或系统环境变量提供。
* `transport: "stdio"` 告诉我们的客户端使用 stdio 连接，`transport: "sse"` 告诉它使用 sse 连接。

### 2. 客户端代码示例

使用 `config_loader.py` 加载配置，并通过 `async with` 语句使用 `MCPClient`。

```python
import asyncio
import os
from core.mcp.client import MCPClient
from core.mcp.config_loader import load_config
# 导入 LangChain 相关 (如果需要 Agent)
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import BaseTool, Tool
# 导入工具的 Pydantic Schema (用于手动创建 Tool)
from pydantic.v1 import BaseModel, Field # 或 v2

# --- Fetch Schema 示例 ---
class FetchInputSchema(BaseModel):
     url: str = Field(..., description="URL to fetch")
     # ... 其他字段 ...

async def main():
    # --- 加载配置 ---
    config_path = os.path.join(os.path.dirname(__file__), "config.json") # 假设 config 在同目录
    try:
        all_configs = load_config(config_path)
        # 选择要使用的配置
        server_key = "fetch_via_uvx" # 或 "everything", "e2b_stdio" 等
        mcp_config = all_configs.get(server_key)
        if not mcp_config:
            print(f"Config '{server_key}' not found.")
            return
    except Exception as e:
        print(f"Failed to load config: {e}")
        return

    # --- 使用 MCPClient ---
    async with MCPClient(mcp_config) as client:
        print(f"Connected to MCP Server '{server_key}'. Session active: {client.session is not None}")
        if not client.session: return

        # --- 获取和使用工具 ---

        # 方式一: 标准方式 (但存在已知问题)
        # print("\nAttempting standard tool loading via load_mcp_tools...")
        # loaded_tools = client.get_tools() # 内部调用 load_mcp_tools
        # print(f"load_mcp_tools returned {len(loaded_tools)} tools.")
        # # !! 注意：对于某些服务器实现 (如此处之前的 MentisMCPServer),
        # # !! load_mcp_tools 返回的工具对象的 args_schema 可能是错误的！
        # # !! 这会导致 Agent 调用失败。但对于 Fetch Server 这样的标准服务器，
        # # !! 它加载的 Schema 可能是正确的。需要根据打印的 Schema 判断。

        # 方式二: 【当前推荐】手动创建 Tool 对象 (绕过 load_mcp_tools 问题)
        print("\nManually creating Tool object with correct schema...")
        tool_name = "fetch" # 假设测试 Fetch Server
        tool_description = "Fetches URL content." # 可以从服务器获取或手写
        correct_schema = FetchInputSchema # 使用正确的 Pydantic 模型

        # 定义调用逻辑
        async def call_mcp_tool_wrapper(**kwargs) -> str:
             # ... (内部使用 client.session.call_tool 发送正确请求) ...
            # 参考 examples/14_mcp_fetch_test.py 中的实现
            if not client or not client.session: return "ERROR: Session lost."
            try:
                req_params = {"name": tool_name, "arguments": kwargs}
                from mcp.types import CallToolRequest # 需要导入
                request = CallToolRequest(method='tools/call', params=req_params)
                result = await client.session.call_tool(request)
                if hasattr(result, 'result'): return str(result.result)
                elif hasattr(result, 'error'): return f"Tool Error: {result.error.message}"
                else: return "Unknown response"
            except Exception as e: return f"Error: {e}"

        # 创建 LangChain Tool
        manual_tool = Tool.from_function(
            name=tool_name,
            description=tool_description,
            args_schema=correct_schema,
            coroutine=call_mcp_tool_wrapper
        )
        tools_for_agent = [manual_tool]
        print(f"Manual tool '{manual_tool.name}' created.")

        # --- 使用 Agent ---
        try:
            # model = llm_manager.get_model("openai_gpt4o_mini") # 获取 LLM
            # agent = create_react_agent(model, tools_for_agent)
            # response = await agent.ainvoke(...)
            # print("Agent Response:", response)
            print("\nAgent execution part skipped in README example.")
            print("Refer to examples/14_mcp_fetch_test.py for full Agent integration.")
        except Exception as e:
            print(f"Agent execution error: {e}")

# if __name__ == "__main__":
#     asyncio.run(main())
```

## 关于自建 MCP Server (MentisMCPServer)

我们在之前的开发中，尝试在 `core/mcp/server.py` 中构建了一个 `MentisMCPServer` 类，目的是将我们内部工具注册表 (`core/tools/registry.py`) 中的 LangChain `BaseTool` 动态包装成 MCP 工具。

**当前遇到的主要挑战：**

我们发现，当使用 `FastMCP` 库的 `@mcp.tool` 装饰器来动态注册这些包装器时，服务器未能正确地向客户端广播这些工具的**输入模式 (Schema)**。这导致客户端的 `load_mcp_tools` 收到了错误的 Schema 信息，进而使 LangChain Agent 在调用工具时因参数错误而失败。

虽然我们通过重构服务器的注册逻辑（改为在 `run_server.py` 中直接使用 `FastMCP` 实例注册顶层包装函数）**成功解决**了 Schema 广播的问题，使得 `load_mcp_tools` 能够获取到正确的 Schema，但后续测试发现 Agent (`create_react_agent`) 在调用这些工具时仍可能出现内部错误 (`TypeError`)。

**结论与建议：**

由于在结合 LangChain 工具、动态包装、`FastMCP` 和 LangChain Agent 时遇到了较深的库交互和调试障碍，我们**目前不建议**将 `MentisMCPServer` 作为稳定可靠的方案对外提供服务。

**推荐使用以下方式来提供或使用 MCP Server:**

1.  **使用社区标准服务器:** 直接使用像 `mcp-server-fetch`, `@modelcontextprotocol/server-everything` 这样由社区或官方提供的、预构建好的 MCP 服务器。通过 `config.json` 配置 `command` (如 `uvx`, `npx`, `python -m`) 或 `url` 来使用它们。
2.  **采用简单服务器模式:** 如果你需要自己实现 MCP Server 来暴露特定功能，建议参考 `modelcontextprotocol/servers` 仓库中的简单示例（如 `math_server`, `time_server`），采用**直接注册工具函数**（用 `@mcp_instance.tool` 装饰顶层 `async def` 函数）的模式，避免复杂的动态包装层。