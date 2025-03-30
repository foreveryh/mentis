from enum import Enum
from typing import List, Dict, Union, Optional
from langchain.tools import Tool

# 定义工具分类枚举
class ToolCategory(Enum):
    SEARCH = "Search"
    CODE_INTERPRETER = "Code Interpreter"
    WEB_BROWSING = "Web Browsing"
    DATABASE = "Database"
    FILE_SYSTEM = "FileSystem"
    IMAGE_GENERATION = "Image Generation"
    OTHER = "Other"

# 全局工具注册表
_registered_tools = {}

def register_tool(tool: Tool, category: ToolCategory) -> None:
    """注册一个工具到全局字典中，带有分类信息
    
    如果工具名已存在，将覆盖现有的工具注册信息
    """
    if tool.name in _registered_tools:
        print(f"警告: 工具名 {tool.name} 已存在，将覆盖现有注册信息")
    _registered_tools[tool.name] = {
        "tool": tool,
        "category": category
    }

def get_registered_tools(as_dict: bool = False) -> Union[List[Tool], Dict[str, Dict]]:
    """返回所有已注册的工具
    
    Args:
        as_dict: 如果为True，返回原始字典格式；如果为False，返回工具列表
        
    Returns:
        如果as_dict为True，返回原始字典格式；否则返回工具列表
    """
    if as_dict:
        return _registered_tools
    return [info["tool"] for info in _registered_tools.values()]

def get_tools_list() -> List[Tool]:
    """返回所有已注册的工具列表，直接可用于Agent初始化
    
    Returns:
        所有已注册工具的列表
    """
    return [info["tool"] for info in _registered_tools.values()]

def get_tools_dict() -> Dict[str, Tool]:
    """返回工具名称到工具实例的映射字典
    
    Returns:
        工具名称到工具实例的映射字典
    """
    return {name: info["tool"] for name, info in _registered_tools.items()}

def get_tool(name: str) -> Optional[Dict]:
    """根据名称获取工具及其分类
    
    Args:
        name: 工具名称
        
    Returns:
        包含工具和分类的字典，如果工具不存在则返回None
    """
    tool_info = _registered_tools.get(name)
    if tool_info:
        return {
            "tool": tool_info["tool"],
            "category": tool_info["category"].value
        }
    return None

def get_tool_instance(name: str) -> Optional[Tool]:
    """根据名称直接获取工具实例
    
    Args:
        name: 工具名称
        
    Returns:
        工具实例，如果工具不存在则返回None
    """
    tool_info = _registered_tools.get(name)
    return tool_info["tool"] if tool_info else None

def get_tools_by_category(category: ToolCategory, return_instances: bool = True) -> List[Union[str, Tool]]:
    """返回指定分类的工具列表
    
    Args:
        category: 工具分类
        return_instances: 如果为True，返回工具实例列表；如果为False，返回工具名称列表
        
    Returns:
        工具实例列表或工具名称列表
    """
    if return_instances:
        return [info["tool"] for name, info in _registered_tools.items() if info["category"] == category]
    return [name for name, info in _registered_tools.items() if info["category"] == category]