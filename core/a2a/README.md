# Mentis A2A (Agent2Agent) 协议集成

本目录 (`core/a2a/`) 包含用于实现 Agent2Agent (A2A) 协议的客户端和服务器实现，使 Mentis Agents 能够与其他支持 A2A 协议的代理系统进行通信和协作。

## 背景

A2A 是由 Google 发起的开放标准，旨在使不同框架（如 LangGraph、CrewAI、Google ADK、Genkit）或不同供应商构建的 AI 代理能够发现彼此的能力，协商交互模式（文本、文件、数据等），并在任务上进行协作。

## 核心组件

### 1. A2A 客户端 (`A2AClient`)

`A2AClient` 类（位于 `client/client.py`）提供了与支持 A2A 协议的服务器进行交互的功能：

* **代理发现:** 支持通过 `.well-known/agent.json` 端点自动发现代理能力（Agent Card）。
* **任务管理:** 提供发送、获取和取消任务的方法。
* **推送通知:** 支持设置和获取任务的推送通知配置。
* **流式响应:** 支持通过流式API接收任务执行的实时更新。
* **异步架构:** 基于 `asyncio` 和 `httpx` 构建，适合异步应用。

### 2. A2A 服务器 (`A2AServer`)

`A2AServer` 类（位于 `server/server.py`）允许将现有的 Mentis Agent 暴露为支持 A2A 协议的服务：

* **基于 Starlette:** 使用 Starlette 框架提供 HTTP 和 SSE 端点。
* **任务处理:** 支持任务的创建、执行和状态跟踪。
* **流式更新:** 通过 Server-Sent Events (SSE) 提供任务执行的实时更新。
* **Agent Card:** 通过 `.well-known/agent.json` 端点公开代理能力。

### 3. 辅助工具

#### 推送通知认证 (`PushNotificationAuth`)

`PushNotificationAuth` 类（位于 `utils/push_notification_auth.py`）提供了安全的推送通知机制：

* **发送方认证 (`PushNotificationSenderAuth`):** 
  - 生成和管理 JWT 密钥对
  - 验证推送通知 URL
  - 签名并发送推送通知
  - 提供 JWKS 端点供接收方获取公钥

* **接收方认证 (`PushNotificationReceiverAuth`):** 
  - 从 JWKS URL 加载公钥
  - 验证接收到的推送通知的完整性和时效性
  - 防止重放攻击

#### 内存缓存 (`InMemoryCache`)

`InMemoryCache` 类（位于 `utils/in_memory_cache.py`）提供了线程安全的内存缓存实现：

* **单例模式:** 确保应用中只有一个缓存实例
* **TTL 支持:** 支持设置缓存项的过期时间
* **线程安全:** 使用锁机制确保并发安全

## 数据类型

A2A 协议定义了几个关键数据类型（位于 `types.py`）：

* **AgentCard:** 描述代理的元数据，包括名称、描述、URL、能力和技能。
* **Task:** 表示代理执行的任务，包含状态、内容和产物。
* **Part:** 内容的一部分，可以是文本、文件或数据。
* **Artifact:** 代理产生的产物，如结果、生成的文件等。
* **TaskState:** 任务状态枚举（已提交、进行中、需要输入、已完成、已取消、失败）。
* **PushNotificationConfig:** 推送通知配置，包含回调URL和认证信息。

## 如何使用

### 1. 创建和使用 A2A 客户端

```python
import asyncio
from common.types import AgentCard
from core.a2a.client.client import A2AClient

async def main():
    # 方式1：直接指定URL创建客户端
    async with A2AClient(url="http://localhost:8000/a2a") as client:
        # 发送任务
        response = await client.send_task({"text": "请帮我研究人工智能"})
        task_id = response["result"]["taskId"]
        
        # 获取任务结果
        task_response = await client.get_task({"id": task_id})
        
        # 设置推送通知
        await client.set_task_callback({
            "taskId": task_id,
            "callbackUrl": "https://your-callback-url.com/webhook"
        })
        
    # 方式2：通过Agent Card创建客户端
    agent_card = AgentCard(name="Example Agent", url="http://localhost:8000/a2a")
    async with A2AClient(agent_card=agent_card) as client:
        # 使用流式API接收实时更新
        async for update in client.send_task_streaming({"text": "分析最新的AI趋势"}):
            print(update)

# 运行
asyncio.run(main())
```

### 2. 创建 A2A 服务器

```python
from core.a2a.server.server import A2AServer
from core.a2a.server.task_manager import InMemoryTaskManager
from common.types import AgentCard

# 创建Agent卡片
agent_card = AgentCard(
    name="My Agent",
    description="一个示例代理",
    url="http://localhost:5000"
)

# 创建任务管理器
task_manager = InMemoryTaskManager()

# 创建服务器
server = A2AServer(
    host="0.0.0.0",
    port=5000,
    endpoint="/",
    agent_card=agent_card,
    task_manager=task_manager
)

# 启动服务器
server.start()
```

### 3. 配置推送通知

#### 发送方配置

```python
from core.a2a.utils.push_notification_auth import PushNotificationSenderAuth

# 创建发送方认证
sender_auth = PushNotificationSenderAuth()

# 生成密钥对
sender_auth.generate_jwk()

# 添加JWKS端点到你的服务器
app.add_route("/.well-known/jwks.json", sender_auth.handle_jwks_endpoint)

# 验证接收方URL
is_valid = await sender_auth.verify_push_notification_url("https://receiver-url.com/webhook")

# 发送推送通知
if is_valid:
    await sender_auth.send_push_notification(
        "https://receiver-url.com/webhook",
        {"event": "task_completed", "taskId": "123"}
    )
```

#### 接收方配置

```python
from core.a2a.utils.push_notification_auth import PushNotificationReceiverAuth
from starlette.requests import Request

# 创建接收方认证
receiver_auth = PushNotificationReceiverAuth()

# 加载发送方的公钥
await receiver_auth.load_jwks("https://sender-url.com/.well-known/jwks.json")

# 在webhook处理函数中验证推送通知
async def webhook_handler(request: Request):
    is_valid = await receiver_auth.verify_push_notification(request)
    if is_valid:
        # 处理推送通知...
        data = await request.json()
        print(f"收到有效的推送通知: {data}")
```

### 4. 使用内存缓存

```python
from core.a2a.utils.in_memory_cache import InMemoryCache

# 获取缓存实例
cache = InMemoryCache()

# 设置缓存项（带TTL）
cache.set("api_result", {"data": "some_value"}, ttl=300)  # 5分钟过期

# 获取缓存项
result = cache.get("api_result")
if result:
    print(f"从缓存获取结果: {result}")
else:
    print("缓存已过期或不存在")
    
# 删除缓存项
cache.delete("api_result")

# 清空所有缓存
cache.clear()
```

## 完整示例

查看 `examples/16_a2a_integration_test.py` 获取完整的集成示例，包括：

1. 创建 A2A 服务器，将现有 Agent 暴露为 A2A 服务
2. 使用 A2A 客户端连接到 A2A 服务器
3. 创建一个 Agent，使用 A2A 客户端作为工具

运行示例：

```bash
# 启动 A2A 服务器
python -m examples.16_a2a_integration_test server

# 运行 A2A 客户端
python -m examples.16_a2a_integration_test client

# 运行带有 A2A 工具的 Agent
python -m examples.16_a2a_integration_test agent
```

## 与 MCP 的关系

Mentis 同时支持 MCP（Model Context Protocol）和 A2A（Agent2Agent）协议：

* **MCP:** 专注于 AI 模型与外部工具/服务的交互，主要用于扩展单个 Agent 的能力。
* **A2A:** 专注于不同 Agent 之间的通信和协作，使多个 Agent 能够协同工作。

这两个协议是互补的，可以同时使用以构建功能强大的 Agent 系统。