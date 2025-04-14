# super_agents/deep_research/a2a_adapter/setup.py

import logging
import asyncio
from typing import Dict, Any, Optional

# 导入A2A相关组件
from core.a2a.types import (
    AgentCard, AgentCapabilities, AgentSkill, Task # Import Task for type hinting
)
from core.a2a.server.server import A2AServer
from starlette.middleware.cors import CORSMiddleware

# 导入DeepResearch适配器
from super_agents.deep_research.a2a_adapter.deep_research_task_manager import DeepResearchTaskManager

# --- Placeholder/Dummy Push Notification Sender ---
# TODO: Replace this with your actual push notification sender implementation
# Your real implementation should likely handle HTTP requests, errors, retries,
# and potentially authentication challenges.
# It needs to be importable, e.g., from core.a2a.server.push_notification_auth import PushNotificationSenderAuth
class DummyPushNotificationSender:
    """这是一个推送通知发送器的占位符/模拟实现，仅记录日志。"""
    async def send_push_notification(self, url: str, data: dict):
        """
        模拟发送推送通知。

        Args:
            url: 目标推送 URL.
            data: 要发送的任务数据 (通常是 Task.model_dump()).
        """
        task_id = data.get("id", "N/A")
        task_state = data.get("status", {}).get("state", "N/A")
        logger.info(
            f"[DummyPushNotificationSender] SIMULATING push notification for task {task_id} "
            f"(State: {task_state}) to URL: {url}"
        )
        # 在这里添加实际的 HTTP POST 请求逻辑
        # 例如:
        # async with httpx.AsyncClient() as client:
        #     try:
        #         response = await client.post(url, json=data, timeout=10.0)
        #         response.raise_for_status()
        #         logger.info(f"Push notification sent successfully for task {task_id}")
        #     except Exception as e:
        #         logger.error(f"Failed to send push notification for task {task_id} to {url}: {e}")
        await asyncio.sleep(0.01) # Simulate tiny async delay

    async def verify_push_notification_url(self, url: str) -> bool:
         """
         模拟验证推送通知URL（例如通过挑战请求）。
         TODO: 实现真实的验证逻辑。
         """
         logger.info(f"[DummyPushNotificationSender] SIMULATING verification for URL: {url} - Returning True")
         return True # 假设总是验证成功
# --- End of Placeholder ---


logger = logging.getLogger(__name__)

def setup_a2a_server(host: str = "127.0.0.1", port: int = 8000) -> A2AServer:
    """
    设置并返回DeepResearch的A2A服务器实例 (启用推送通知支持)

    Args:
        host: 服务器主机地址
        port: 服务器端口

    Returns:
        A2AServer: 配置好的A2A服务器实例
    """
    print("\n=== 配置 DeepResearch A2A 服务器 ===\n")

    # 创建Agent卡片 (确保 pushNotifications=True)
    agent_card = AgentCard(
        name="DeepResearch Agent",
        description="一个强大的研究助手，能够执行深度研究并生成详细报告",
        url=f"http://{host}:{port}/agent", # 使用传入的 host/port 构建 URL
        version="0.1.0",
        capabilities=AgentCapabilities(
            streaming=True,           # Agent 支持流式
            pushNotifications=True    # Agent *声明*支持推送通知
        ),
        skills=[
            AgentSkill(
                id="deep_research_skill",
                name="deep_research",
                description="执行深度研究并生成详细报告，包括搜索、分析和综合",
                inputModes=["text"],
                outputModes=["text"]
            )
        ]
        # 你可以在这里添加 provider 等可选字段
        # provider=AgentProvider(organization="YourOrg", url="http://yourorg.com")
    )

    # --- 实例化 Push Notification Sender ---
    # 使用上面定义的占位符实现。
    # TODO: 当你有真实的实现时，替换下面这行
    notification_sender = DummyPushNotificationSender()
    logger.info("Initialized with DummyPushNotificationSender.")
    # --- 实例化结束 ---

    # --- 创建任务管理器，并传入 notification_sender_auth ---
    task_manager = DeepResearchTaskManager(
        notification_sender_auth=notification_sender
    )
    # --- 创建结束 ---

    # 创建A2A服务器实例 (传入 host 和 port)
    server = A2AServer(
        host=host,
        port=port,
        agent_card=agent_card,
        task_manager=task_manager
    )
    
    # 添加CORS中间件支持
    server.app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 允许所有前端域名访问，生产环境中应该限制为特定域名
        allow_credentials=True,
        allow_methods=["*"],  # 允许所有HTTP方法
        allow_headers=["*"],  # 允许所有HTTP头
    )
    print("已添加CORS支持，允许来自所有域的请求")

    print(f"DeepResearch A2A服务器实例已创建，监听地址 http://{host}:{port}")
    return server

# 示例使用方法 (保持不变)
def run_server(host: str = "127.0.0.1", port: int = 8000):
    """
    运行DeepResearch A2A服务器

    Args:
        host: 服务器主机地址
        port: 服务器端口
    """
    try:
        # 设置服务器
        server = setup_a2a_server(host, port)

        # 启动服务器
        print(f"启动DeepResearch A2A服务器...") # 移除重复地址信息
        server.start()

    except KeyboardInterrupt:
        print("\n服务器已手动停止。")
    except Exception as e:
        logger.error(f"启动服务器时发生未处理的异常: {e}", exc_info=True)

if __name__ == "__main__":
    # 直接运行此文件时启动服务器
    # 你可以从命令行参数或环境变量获取 host 和 port
    run_host = os.getenv("A2A_HOST", "127.0.0.1")
    run_port = int(os.getenv("A2A_PORT", "8000"))
    run_server(host=run_host, port=run_port)