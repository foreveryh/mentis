# MCP 测试框架说明

## 概述

MCP（Machine Conversation Protocol）是一个用于机器对话的协议框架，它允许不同的系统通过标准化的接口进行通信。本测试框架提供了一种方式来测试MCP服务器的功能和性能。

## 测试文件结构

测试框架包含以下主要文件：

### 1. minimal_fastmcp_test.py

这是一个最小化的FastMCP服务器实现，用于测试基本功能：

- 创建FastMCP实例
- 注册简单的工具函数（ping工具）
- 通过STDIO传输方式运行服务器

该文件可以独立运行，也可以被其他测试脚本作为子进程启动。

### 2. test_minimal_client.py

这个脚本使用MCP客户端库来测试minimal_fastmcp_test.py：

- 导入必要的MCP客户端库（ClientSession, stdio_client等）
- 连接到minimal_fastmcp_test.py并测试ping工具
- 展示如何使用客户端API进行工具调用

## 测试方法

### 客户端库测试（test_minimal_client.py）

这种测试方法使用MCP客户端库与MCP服务器通信，展示了如何在实际应用中使用MCP客户端。测试流程如下：

1. 创建ClientSession对象
2. 连接到MCP服务器
3. 调用工具并处理结果

## 运行测试

### 运行客户端库测试

```bash
python core/mcp/test/test_minimal_client.py
```

## 扩展测试

### 添加新工具

要在minimal_fastmcp_test.py中添加新工具，可以按照以下步骤操作：

1. 定义新的异步工具函数
2. 使用FastMCP实例的装饰器注册工具

示例：
```python
async def new_tool(param1: str, param2: int = 0) -> str:
    """A new tool description."""
    # 工具实现
    return f"Result: {param1}, {param2}"

mcp_server.tool(name="new_tool", description="New tool description.")(new_tool)
```

### 创建新的测试脚本

可以参考现有的测试脚本创建新的测试脚本，测试不同的功能或场景。

## 常见问题

### 服务器无响应

- 确保服务器进程正在运行
- 检查传输方式是否正确（stdio或sse）
- 检查客户端连接参数是否正确

### 工具调用失败

- 确保工具名称正确
- 检查参数是否符合工具的要求
- 查看服务器日志以获取更多信息

## 总结

MCP测试框架提供了使用MCP客户端库测试MCP服务器功能的方法。通过这些测试，可以验证MCP服务器的基本功能和性能，为开发和调试提供支持。