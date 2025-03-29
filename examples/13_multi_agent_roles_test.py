from langgraph.prebuilt import create_react_agent
from core.agents.react_supervisor_agent import SupervisorAgent
from core.agents.sub_agents.research_agent import ResearchAgent
from core.agents.sub_agents.coder_agent import CoderAgent
from core.agents.sub_agents.reporter_agent import ReporterAgent
from core.agents.sub_agents.designer_agent import DesignerAgent
from core.agents.sub_agents.data_analyst_agent import DataAnalystAgent
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages
from dotenv import load_dotenv
from langchain_community.tools import TavilySearchResults
import os
import logging
import sys
import io
import json
from contextlib import redirect_stdout, redirect_stderr

load_dotenv()  # 自动加载 .env 文件

# 1. 初始化大模型
model = ChatOpenAI(model="gpt-4o-mini")
# 设置日志捕获
class LogCapture:
    def __init__(self):
        self.log_buffer = io.StringIO()
        self.log_content = []
    
    def start_capture(self):
        self.log_buffer = io.StringIO()
        return self.log_buffer
    
    def stop_capture(self):
        output = self.log_buffer.getvalue()
        self.log_content.append(output)
        return output
    
    def get_content(self):
        return "\n".join(self.log_content)

log_capture = LogCapture()

##############################################################################
# 从沙箱下载文件到本地的函数
##############################################################################

def download_file_from_sandbox(sandbox, sandbox_path, local_path):
    """从 e2b 沙箱中下载文件并保存到本地，自动区分文本和二进制文件"""
    try:
        print(f"读取文件: {sandbox_path}")

        # 判断是否为常见二进制文件类型（可自行扩展）
        binary_extensions = (
            '.png', '.jpg', '.jpeg', '.gif', '.pdf', '.svg',
            '.xlsx', '.xls', '.zip', '.bin', '.pyc', '.pyd',
            '.pptx', '.docx', '.mp3', '.mp4', '.avi', '.mov',
        )
        is_binary = sandbox_path.lower().endswith(binary_extensions)

        # 创建目录
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        if is_binary:
            print("📦 识别为二进制文件，使用 sandbox.download_file()")
            content = sandbox.files.read(sandbox_path)  # 返回 bytes
            with open(local_path, 'wb') as f:
                f.write(content)
        else:
            print("📄 识别为文本文件，使用 sandbox.files.read()")
            content = sandbox.files.read(sandbox_path)  # 返回 str
            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(content)

        print(f"✅ 文件已保存到本地: {local_path}")
        return True

    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return False

def download_directory_from_sandbox(sandbox, sandbox_dir_path, local_dir_path):
    """从沙箱下载整个目录内容到本地
    
    Args:
        sandbox: 沙箱实例
        sandbox_dir_path: 沙箱中的目录路径
        local_dir_path: 本地保存目录路径
    
    Returns:
        bool: 是否成功下载所有文件
    """
    try:
        print(f"尝试下载目录: {sandbox_dir_path} -> {local_dir_path}")
        
        # 确保本地目录存在
        os.makedirs(local_dir_path, exist_ok=True)
        
        # 列出沙箱中指定目录下的所有文件
        try:
            files = sandbox.files.list(sandbox_dir_path)
        except Exception as e:
            print(f"列出文件时出错: {sandbox_dir_path}, 错误: {str(e)}")
            return False
        
        if not files:
            print(f"沙箱中目录 {sandbox_dir_path} 为空或不存在")
            return False
            
        downloaded_count = 0
        # 定义需要跳过的系统文件
        skip_files = {'.bashrc', '.bash_logout', '.profile'}
        
        # 遍历并下载每个文件
        for file_info in files:
            try:
                # 尝试安全获取name和type属性
                file_name = getattr(file_info, "name", None)
                if file_name is None:
                    print(f"警告: 无法获取文件名, 跳过此文件")
                    continue
                    
                file_type = getattr(file_info, "type", "file")  # 默认为文件类型
                # 如果 file_type 是枚举, 使用其 value 进行判断
                type_value = file_type.value if hasattr(file_type, "value") else file_type
                
                # 跳过不需要的系统文件或系统目录（隐藏文件/目录）
                if file_name in skip_files or (file_name.startswith('.') and type_value == 'dir'):
                    print(f"跳过系统文件或目录: {file_name}")
                    continue
                
                print(f"处理文件: {file_name}, 类型: {type_value}")
                
                sandbox_file_path = f"{sandbox_dir_path}/{file_name}"
                local_file_path = os.path.join(local_dir_path, file_name)
                
                if type_value == 'dir':
                    # 递归下载子目录
                    print(f"发现子目录: {sandbox_file_path}")
                    if download_directory_from_sandbox(sandbox, sandbox_file_path, local_file_path):
                        downloaded_count += 1
                else:
                    # 下载文件
                    print(f"下载文件: {sandbox_file_path} -> {local_file_path}")
                    if download_file_from_sandbox(sandbox, sandbox_file_path, local_file_path):
                        downloaded_count += 1
            except Exception as e:
                print(f"处理文件时出错: {str(e)}")
                import traceback
                print(f"详细错误跟踪: {traceback.format_exc()}")
                continue
        
        if downloaded_count > 0:
            print(f"从 {sandbox_dir_path} 下载了 {downloaded_count} 个文件/目录到 {local_dir_path}")
            return True
        return False
        
    except Exception as e:
        print(f"下载整个目录时出错: {str(e)}")
        import traceback
        print(f"详细错误跟踪: {traceback.format_exc()}")


##############################################################################
# Agent 2: Research Expert - 使用自定义的ResearchAgent
##############################################################################

research_agent = ResearchAgent(
    name="research_expert",
    model=model,
    max_iterations=5,
    cache_enabled=True,
    debug=True
)

##############################################################################
# Agent 3: Coder - 使用自定义的CoderAgent
##############################################################################
from core.tools.e2b_tool import E2BCodeInterpreterTool
e2b_tool = E2BCodeInterpreterTool()

coder_agent = CoderAgent(
    name="coder_expert",
    model=model,
    tools=[e2b_tool],
    max_iterations=5,
    cache_enabled=True,
    debug=True
)

##############################################################################
# Agent 4: Reporter - 使用自定义的ReporterAgent
##############################################################################

reporter_agent = ReporterAgent(
    name="reporter_expert",
    model=model,
    max_iterations=5,
    cache_enabled=True,
)

##############################################################################
# Agent 5: Designer - 使用自定义的DesignerAgent
##############################################################################

designer_agent = DesignerAgent(
    name="designer_expert",
    model=model,
    max_iterations=5,
    cache_enabled=True,
)

##############################################################################
# Agent 6: Data Analyst - 使用自定义的DataAnalystAgent
##############################################################################

data_analyst_agent = DataAnalystAgent(
    name="data_analyst_expert",
    model=model,
    max_iterations=5,
    cache_enabled=True,
)

##############################################################################
# 使用带有Planning功能的SupervisorAgent协调所有角色
##############################################################################

# 创建 SupervisorAgent 实例，启用Planning功能
supervisor = SupervisorAgent(
    agents=[
        research_agent,
        coder_agent,
        reporter_agent,
        designer_agent,
        data_analyst_agent,
    ],
    model=model,
    enable_planning=True,
    output_mode="last_message"
)

# 获取当前文件名（不含路径和扩展名）
current_file = os.path.basename(__file__)
file_name_without_ext = os.path.splitext(current_file)[0]
logs_dir = os.path.join(os.path.dirname(__file__), "logs")
# 创建图表输出文件路径
os.makedirs(logs_dir, exist_ok=True)
# 创建Markdown输出文件路径
markdown_path = os.path.join(logs_dir, f"{file_name_without_ext}.md")

##############################################################################
# 测试：复杂请求需要规划和多个步骤
##############################################################################

def save_markdown_log():
    """将执行结果保存为Markdown文件"""
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(f"# 执行结果: {file_name_without_ext}\n\n")
        f.write("## 图表\n\n")
        f.write("## 执行日志\n\n")
        f.write("```\n")
        f.write(log_capture.get_content())
        f.write("\n```\n")
    print(f"执行日志已保存到 {markdown_path}")

if __name__ == "__main__":
    try:
        # 开始捕获输出
        log_buffer = log_capture.start_capture()
        
        with redirect_stdout(log_buffer), redirect_stderr(log_buffer):
            print(f"开始执行 {current_file} 测试...")
            
            # 测试1：需要研究和编码的任务
            print("\n## 测试1：需要研究和编码的任务")
            final_state = supervisor.run({
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "我需要一个Python爬虫来获取 https://www.paulgraham.com/articles.html 所有articles列表，并将结果保存为CSV文件,放在/home/user下面。"
                            "并将你测试通过的爬虫代码返回给我。"
                            "请确保你的代码能够正常运行。"
                            "如果遇到问题，请重试。"
                        )
                    }
                ]
            })
            
            print("\n测试1结果:")
            for m in final_state["messages"]:
                m.pretty_print()
            
            # 遍历 react_agent.tools 以查找 E2B 相关工具
            try:
            # 遍历 react_agent.tools 以查找 E2B 相关工具
                sandbox = None
                for tool in coder_agent.tools:
                    if hasattr(tool, "sandbox"):
                        sandbox = tool.sandbox
                        break  # 找到后就退出循环

                if sandbox:
                    # 设定输出目录
                    output_dir = os.path.join(os.getcwd(), "examples/output/sandbox_files")
                    os.makedirs(output_dir, exist_ok=True)

                    # 直接下载主要工作目录
                    print("\n从沙箱下载文件到本地...")
                    download_directory_from_sandbox(sandbox, "/home/user", output_dir)

                    # 下载临时目录中可能的图表和数据文件
                    # download_directory_from_sandbox(sandbox, "/tmp", output_dir)

                    print(f"\n文件已保存到目录: {output_dir}")
                    sandbox.close()
            except Exception as e:
                print(f"从沙箱下载文件时出错: {str(e)}")

           
    finally:
        # 停止捕获并保存结果
        log_capture.stop_capture()
        save_markdown_log()