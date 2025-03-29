import os
from typing import Dict, Any, Optional, Literal
from langchain_core.messages import AIMessage, ToolMessage
import inspect

def log_agent_actions(state: Dict[str, Any]) -> None:
    """记录Agent的思考过程和行动
    
    这个函数用于在控制台打印Agent的思考过程、工具调用和工具返回结果，
    便于观察和调试Agent的行为。
    
    Args:
        state: 包含消息历史的状态字典
    """
    print("\n" + "=" * 50)
    print("当前状态:")
    
    # 打印最新消息
    if state.get("messages") and len(state["messages"]) > 0:
        latest_message = state["messages"][-1]
        
        if isinstance(latest_message, AIMessage):
            print(f"\nAI思考过程:")
            print(latest_message.content)
            
            # 如果有工具调用，打印工具调用信息
            if latest_message.tool_calls:
                print(f"\n工具调用:")
                for tool_call in latest_message.tool_calls:
                    print(f"- 工具: {tool_call['name']}")
                    print(f"- 参数: {tool_call['args']}")
        
        elif isinstance(latest_message, ToolMessage):
            print(f"\n工具返回结果:")
            print(f"- 工具: {latest_message.name}")
            # 只打印结果的前500个字符，避免输出过长
            content = latest_message.content
            if len(content) > 500:
                content = content[:500] + "... (更多内容省略)"
            print(f"- 结果: {content}")
    
    print("=" * 50)

def save_agent_graph(
    agent, 
    caller_file_path: Optional[str] = None,
    output_format: Literal["png", "svg", "mermaid"] = "png",
    custom_filename: Optional[str] = None,
    output_dir: Optional[str] = None
) -> str:
    """保存Agent的图表到指定目录
    
    这个函数用于生成Agent的图表并保存到指定目录，
    默认情况下文件名与调用者的文件名保持一致（不含扩展名）。
    
    Args:
        agent: Agent对象，必须有get_graph方法
        caller_file_path: 调用者的文件路径，如果为None则使用调用栈获取
        output_format: 输出格式，可选"png"、"svg"或"mermaid"
        custom_filename: 自定义文件名（不含扩展名），如果提供则使用此名称
        output_dir: 自定义输出目录，如果提供则使用此目录
        
    Returns:
        str: 保存的图表路径
    """
    # 如果没有提供调用者文件路径，则从调用栈获取
    if caller_file_path is None:
        # 获取调用者的栈帧
        frame = inspect.currentframe().f_back
        caller_file_path = frame.f_code.co_filename
    
    try:
        # 获取图对象
        graph = agent.get_graph()
    except AttributeError:
        raise ValueError("提供的agent对象没有get_graph方法") 
    except Exception as e:
        raise RuntimeError(f"获取图表时出错: {str(e)}")
    
    # 确定文件名
    if custom_filename:
        file_name_without_ext = custom_filename
    else:
        # 获取当前文件名（不含路径和扩展名）
        current_file = os.path.basename(caller_file_path)
        file_name_without_ext = os.path.splitext(current_file)[0]
    
    # 确定输出目录
    if output_dir:
        graph_dir = output_dir
    else:
        # 如果调用者在examples目录下，则使用examples/graphs
        # 否则在调用者所在目录创建graphs子目录
        if 'examples' in caller_file_path:
            base_dir = os.path.dirname(os.path.dirname(caller_file_path))
            graph_dir = os.path.join(base_dir, "examples", "graphs")
        else:
            graph_dir = os.path.join(os.path.dirname(caller_file_path), "graphs")
    
    # 确保graphs目录存在
    os.makedirs(graph_dir, exist_ok=True)
    
    # 根据输出格式生成相应文件
    try:
        if output_format == "png":
            image_data = graph.draw_mermaid_png()
            graph_path = os.path.join(graph_dir, f"{file_name_without_ext}.png")
            with open(graph_path, "wb") as f:
                f.write(image_data)
                
        elif output_format == "svg":
            image_data = graph.draw_mermaid_svg()
            graph_path = os.path.join(graph_dir, f"{file_name_without_ext}.svg")
            with open(graph_path, "wb") as f:
                f.write(image_data)
                
        elif output_format == "mermaid":
            mermaid_code = graph.get_mermaid()
            graph_path = os.path.join(graph_dir, f"{file_name_without_ext}.mmd")
            with open(graph_path, "w") as f:
                f.write(mermaid_code)
        else:
            raise ValueError(f"不支持的输出格式: {output_format}")
            
    except Exception as e:
        raise RuntimeError(f"保存图表时出错: {str(e)}")
        
    print(f"图表已保存为 {graph_path}")
    return graph_path

def visualize_agent(agent, **kwargs):
    """可视化Agent的快捷方法
    
    这是save_agent_graph的简便包装，用于快速可视化Agent
    
    Args:
        agent: Agent对象
        **kwargs: 传递给save_agent_graph的其他参数
        
    Returns:
        str: 保存的图表路径
    """
    # 获取调用者的栈帧
    frame = inspect.currentframe().f_back
    caller_file_path = frame.f_code.co_filename
    
    return save_agent_graph(agent, caller_file_path=caller_file_path, **kwargs)