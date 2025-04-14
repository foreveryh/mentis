# super_agents/deep_research/a2a_adapter/run_server.py

import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
current_script_path = Path(__file__).resolve()
project_root = current_script_path.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入A2A适配器
from super_agents.deep_research.a2a_adapter.setup import run_server

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """
    启动DeepResearch A2A服务器的主函数
    """
    # 定义服务器配置
    HOST = os.getenv("A2A_HOST", "127.0.0.1")
    PORT = int(os.getenv("A2A_PORT", "8000"))
    
    print(f"\n=== 启动 DeepResearch A2A 服务器 ===\n")
    print(f"主机: {HOST}")
    print(f"端口: {PORT}")
    print("-" * 40)
    
    # 运行服务器
    run_server(HOST, PORT)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n服务器已手动停止。")
    except Exception as e:
        logger.error(f"启动服务器时发生未处理的异常: {e}", exc_info=True)