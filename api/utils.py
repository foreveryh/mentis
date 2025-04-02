import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, ToolMessage
from langgraph.types import StateSnapshot


def checkpoint_event(value):
    """Create a checkpoint event for the client."""

    def format_values(values: dict):
        formatted_values = values.copy()
        if "messages" in formatted_values:
            formatted_values["messages"] = [
                {
                    "type": msg.get("type") if isinstance(msg, dict) else msg.type,
                    "content": msg.get("content") if isinstance(msg, dict) else msg.content,
                    "id": msg.get("id") if isinstance(msg, dict) else msg.id,
                    "tool_calls": msg.get("tool_calls") if isinstance(msg, dict) else (msg.tool_calls if hasattr(msg, 'tool_calls') else None)
                }
                for msg in formatted_values["messages"]
            ]
        return formatted_values

    def format_writes(writes: dict):
        if writes is None:
            return None
        formatted_writes = {}
        for key, value in writes.items():
            if isinstance(value, dict):
                formatted_writes[key] = format_values(value)
            elif isinstance(value, list):
                formatted_writes[key] = [format_values(item) if isinstance(
                    item, dict) else item for item in value]
            else:
                formatted_writes[key] = value
        return formatted_writes

    configurable = value["payload"]["config"]["configurable"]
    data = {
        "next": value["payload"]["next"],
        "values": format_values(value["payload"]["values"]),
        "config": {
            "configurable": {
                "checkpoint_id": configurable["checkpoint_id"],
                "checkpoint_ns": configurable["checkpoint_ns"],
                "thread_id": configurable["thread_id"]
            }
        },
        "metadata": {
            "source": value["payload"]["metadata"]["source"],
            "step": value["payload"]["metadata"]["step"],
            "writes": format_writes(value["payload"]["metadata"]["writes"]),
            "parents": value["payload"]["metadata"]["parents"]
        }
    }
    return {
        "event": "checkpoint",
        "data": json.dumps(data)
    }


def message_chunk_event(node_name, message_chunk):
    """Create a message chunk event for the client."""

    def format_messages(value):
        """Format message chunk into a serializable dictionary. 
        This is needed because the message class is not serializable.
        """
        return {
            "content": value.content,
            "id": value.id,
            "tool_calls": value.tool_calls if hasattr(value, 'tool_calls') else None,
            "tool_call_chunks": value.tool_call_chunks if hasattr(value, 'tool_call_chunks') else None
        }

    return {
        "event": "message_chunk",
        "data": json.dumps({
            "node_name": node_name,
            "message_chunk": format_messages(message_chunk)
        })
    }


def interrupt_event(interrupts):
    """Create an interrupt event for the client."""
    formatted_interrupts = [{"value": interrupt["value"]}
                            for interrupt in interrupts]
    return {
        "event": "interrupt",
        "data": json.dumps(formatted_interrupts)
    }


def custom_event(value):
    """Create a custom event for the client."""
    return {
        "event": "custom",
        "data": json.dumps(value)
    }


def format_state_snapshot(snapshot: StateSnapshot):
    interrupts = []
    for task in snapshot.tasks:
        for interrupt in task.interrupts:
            interrupts.append({"value": interrupt.value})
    return {
        "values": snapshot.values,
        "next": snapshot.next,
        "config": snapshot.config,
        "interrupts": interrupts,
        "parent_config": snapshot.parent_config,
        "metadata": snapshot.metadata
    }


def stream_update_event(data: dict):
    """为 DeepResearch Agent 的 StreamUpdateData 创建一个 stream_update 事件。

    Args:
        data: 从 add_stream_update 产生的、符合 StreamUpdateData 结构的字典。

    Returns:
        符合 SSE EventSourceResponse 格式的字典。
    """
    if not isinstance(data, dict):
        # 如果传入的不是字典，记录错误或返回一个错误事件
        print(f"Error: stream_update_event received non-dict data: {type(data)}")
        return {
            "event": "error",
            "data": json.dumps({"message": "Internal server error: Invalid stream update data type."})
        }
    
    # 确保关键字段存在（可选，主要依赖生产者正确生成）
    # expected_keys = ['id', 'type', 'status', 'title', 'message']
    # if not all(k in data for k in expected_keys):
    #     print(f"Warning: stream_update_event received data missing expected keys: {data}")
        
    print(f"DEBUG: Formatting stream_update event for ID: {data.get('id')}") # 添加 Debug 日志
    return {
        "event": "stream_update", # 使用明确的事件名称
        "data": json.dumps(data, default=str) # 直接序列化数据字典为 JSON 字符串
    }
