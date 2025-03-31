# Tools package initialization
from langchain_community.agent_toolkits.load_tools import load_tools
from core.tools.registry import register_tool, ToolCategory, get_registered_tools
from core.tools.firecrawl_tool import FireCrawlTool
from core.tools.e2b_tool import E2BCodeInterpreterTool
import os
import importlib
import inspect
from typing import Any, Dict, List, Type, Optional
from langchain_core.tools import BaseTool

# 导入预注册所需的工具
from langchain_community.tools import (
    TavilySearchResults,
    ArxivQueryRun,
)
from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_community.agent_toolkits.openapi.toolkit import RequestsToolkit,TextRequestsWrapper
from langchain_community.tools.riza.command import ExecPython, ExecJavaScript

from dotenv import load_dotenv
load_dotenv()  # 自动加载 .env 文件

# 预注册核心工具列表 - 定义需要预注册的核心工具
def preregister_core_tools():
    """预注册核心工具，确保系统启动时这些工具已经可用"""
    print("开始预注册核心工具...")
    
    # 注册搜索类工具
    try:
        # Tavily搜索工具
        tavily_search = TavilySearchResults()
        register_tool(tavily_search, ToolCategory.SEARCH)
        print(f"已预注册工具: {tavily_search.name} (类别: {ToolCategory.SEARCH.value})")
    except Exception as e:
        print(f"预注册Tavily搜索工具失败: {e}")
    
    # 注册网页浏览类工具
    try:
        # Arxiv查询工具
        arxiv_tool = ArxivQueryRun()
        register_tool(arxiv_tool, ToolCategory.WEB_BROWSING)
        print(f"已预注册工具: {arxiv_tool.name} (类别: {ToolCategory.WEB_BROWSING.value})")
    except Exception as e:
        print(f"预注册Arxiv查询工具失败: {e}")
    
    try:
        # RequestoolKit请求工具
        # 创建TextRequestsWrapper实例作为请求包装器
        requests_wrapper = TextRequestsWrapper(headers={})
        # 初始化RequestsToolkit，提供必要的参数
        requests_toolkit = RequestsToolkit(
            requests_wrapper=requests_wrapper,
            allow_dangerous_requests=True  # 允许危险请求，使工具可用
        )
        for req_tool in requests_toolkit.get_tools():
            register_tool(req_tool, ToolCategory.WEB_BROWSING)
            print(f"已预注册工具: {req_tool.name} (类别: {ToolCategory.WEB_BROWSING.value})")
    except Exception as e:
        print(f"预注册 RequestoolKit请求工具失败: {e}")
    
    # 注册文件系统工具
    try:
        # 获取当前目录作为文件系统工具的根目录
        current_dir = os.getcwd()
        # 创建文件系统工具集
        filesystem_toolkit = FileManagementToolkit(
            root_dir=current_dir,
            selected_tools=["write_file", "read_file", "list_directory"]
        )
        # 获取文件系统工具并注册
        for fs_tool in filesystem_toolkit.get_tools():
            register_tool(fs_tool, ToolCategory.FILE_SYSTEM)
            print(f"已预注册工具: {fs_tool.name} (类别: {ToolCategory.FILE_SYSTEM.value})")
    except Exception as e:
        print(f"预注册文件系统工具失败: {e}")
    
    # 注册代码解释器工具
    # try:
    #     # Python REPL工具
    #     python_repl = ExecPython()
    #     register_tool(python_repl, ToolCategory.CODE_INTERPRETER)
    #     print(f"已预注册工具: {python_repl.name} (类别: {ToolCategory.CODE_INTERPRETER.value})")
    # except Exception as e:
    #     print(f"预注册Python REPL工具失败: {e}")

    # # 注册代码解释器工具
    # try:
    #     # Python REPL工具
    #     javascript_repl = ExecJavaScript()
    #     register_tool(javascript_repl, ToolCategory.CODE_INTERPRETER)
    #     print(f"已预注册工具: {javascript_repl.name} (类别: {ToolCategory.CODE_INTERPRETER.value})")
    # except Exception as e:
    #     print(f"预注册Python REPL工具失败: {e}")
    
    # 注册自定义工具 - FireCrawl工具
    try:
        firecrawl_tool = FireCrawlTool()
        register_tool(firecrawl_tool, ToolCategory.WEB_BROWSING)
        print(f"已预注册工具: {firecrawl_tool.name} (类别: {ToolCategory.WEB_BROWSING.value})")
    except Exception as e:
        print(f"预注册FireCrawl工具失败: {e}")
    
    # 注册E2B代码解释器工具
    try:
        e2b_tool = E2BCodeInterpreterTool()
        register_tool(e2b_tool, ToolCategory.CODE_INTERPRETER)
        print(f"已预注册工具: {e2b_tool.name} (类别: {ToolCategory.CODE_INTERPRETER.value})")
    except Exception as e:
        print(f"预注册E2B代码解释器工具失败: {e}")


    from .replicate_flux_tool import ReplicateFluxImageTool, category 
    try:
        flux_tool = ReplicateFluxImageTool()
        if flux_tool._is_available:
            register_tool(flux_tool, category)
    except Exception as e:
        print(f"Failed to register ReplicateFluxImageTool: {e}")

print("核心工具预注册完成")

# 执行预注册
preregister_core_tools()

# 注册 LangChain 工具 - 使用load_tools加载的工具列表
try:
    langchain_tools = load_tools(["serpapi"])
    for tool in langchain_tools:
        register_tool(tool, ToolCategory.SEARCH)
        print(f"已注册LangChain工具: {tool.name} (类别: {ToolCategory.SEARCH.value})")
except Exception as e:
    print(f"加载LangChain工具失败: {e}")

# 工具类别映射 - 用于自动分类直接导入的工具
tool_category_mapping = {
    # 搜索类工具
    "TavilySearchResults": ToolCategory.SEARCH,
    "GoogleSearchResults": ToolCategory.SEARCH,
    "GoogleSerperResults": ToolCategory.SEARCH,
    "WikipediaQueryRun": ToolCategory.SEARCH,
    "FireCrawl": ToolCategory.SEARCH,
    
    # 网页浏览类工具
    "WebBrowser": ToolCategory.WEB_BROWSING,
    "ArxivQueryRun": ToolCategory.WEB_BROWSING,
    "RequestsGet": ToolCategory.WEB_BROWSING,
    "RequestsPost": ToolCategory.WEB_BROWSING,
    
    # 文件系统类工具
    "WriteFile": ToolCategory.FILE_SYSTEM,
    "ReadFile": ToolCategory.FILE_SYSTEM,
    "ListDirectory": ToolCategory.FILE_SYSTEM,
    
    # 代码解释器类工具
    "PythonREPL": ToolCategory.CODE_INTERPRETER,
    "ShellTool": ToolCategory.CODE_INTERPRETER,
    "E2BCodeInterpreterTool": ToolCategory.CODE_INTERPRETER,
    
    # 数据库类工具
    "SQLDatabaseTool": ToolCategory.DATABASE,
    
    # 默认为其他类别
    "default": ToolCategory.OTHER
}

def register_direct_tool(tool_instance: BaseTool, category: ToolCategory = None) -> None:
    """注册直接从langchain_community.tools导入的工具
    
    Args:
        tool_instance: 工具实例
        category: 工具类别，如果为None则自动根据工具名称判断类别
    """
    if not category:
        # 获取工具类名
        tool_class_name = tool_instance.__class__.__name__
        # 根据工具类名自动判断类别
        category = tool_category_mapping.get(tool_class_name, tool_category_mapping["default"])
    
    # 注册工具
    register_tool(tool_instance, category)
    print(f"已注册工具: {tool_instance.name} (类别: {category.value})")

# 获取 tools 目录路径
tools_dir = os.path.dirname(__file__)

# 遍历目录中的所有文件，注册自定义工具
for filename in os.listdir(tools_dir):
    # 只处理 .py 文件，且排除 __init__.py 和 registry.py
    if filename.endswith('.py') and filename not in ['__init__.py', 'registry.py']:
        # 提取模块名（去掉 .py 后缀）
        module_name = filename[:-3]
        try:
            # 动态导入模块
            module = importlib.import_module(f'.{module_name}', package='core.tools')
            
            # 查找模块中的工具类（继承自BaseTool的类）
            for name, obj in inspect.getmembers(module):
                # 检查是否是类且是BaseTool的子类
                if inspect.isclass(obj) and issubclass(obj, BaseTool) and obj != BaseTool:
                    # 检查该类是否已经被实例化并注册
                    tool_name = getattr(obj, 'name', None)
                    if tool_name and tool_name not in [info['tool'].name for info in get_registered_tools().values()]:
                        # 确定工具类别
                        category = getattr(module, 'category', ToolCategory.OTHER)
                        # 实例化并注册工具
                        try:
                            tool_instance = obj()
                            register_tool(tool_instance, category)
                            print(f"已注册工具类: {name} (工具名: {tool_instance.name}, 类别: {category.value})")
                        except Exception as e:
                            print(f"实例化工具类 {name} 时出错: {e}")
        except Exception as e:
            print(f"导入 {module_name} 时出错: {e}")