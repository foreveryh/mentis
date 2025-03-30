# 文件路径: core/tools/firecrawl_tool.py (或您存放工具的文件)

import os
import json # 虽然不直接返回 JSON，但可能用于处理 metadata
from typing import Dict, List, Literal, Optional, Tuple, Type, Union, Any # 确保导入
from pydantic import BaseModel, Field, PrivateAttr # 导入 PrivateAttr
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from dotenv import load_dotenv
load_dotenv()  # 自动加载 .env 文件


# 尝试导入 FireCrawlLoader，如果失败则标记
try:
    from langchain_community.document_loaders import FireCrawlLoader
    FIRECRAWL_LOADER_AVAILABLE = True
except ImportError:
    FireCrawlLoader = None # type: ignore
    FIRECRAWL_LOADER_AVAILABLE = False
    print("Warning: langchain_community or firecrawl-py not installed? FireCrawlLoader unavailable.")
    print("Run: pip install -U langchain-community firecrawl-py")

# 定义输入 Schema (保持不变)
class FireCrawlInput(BaseModel):
    """Input for the FireCrawl tool."""
    url: str = Field(description="URL to crawl or scrape")
    mode: str = Field(
        default="scrape", # <-- 将默认模式改为 'scrape' 可能更常用
        description="Mode: 'scrape' (single page), 'crawl' (multiple pages). Default: 'scrape'",
    )
    # 可以添加 params 字段如果希望 LLM 控制更多参数
    # params: Optional[Dict[str, Any]] = Field(default=None, description="Optional dictionary of additional FireCrawl parameters (e.g., {'pageOptions': {'onlyMainContent': True}})")


class FireCrawlTool(BaseTool):
    """
    Tool that uses FireCrawl API to crawl or scrape web content and return a summary.

    Setup:
        pip install -U langchain-community firecrawl-py
        export FIRECRAWL_API_KEY="your-api-key"

    Instantiate:
        tool = FireCrawlTool() # Reads API key from env
        # Or explicitly: tool = FireCrawlTool(api_key="...")

    Invoke:
        tool.invoke({"url": "https://example.com", "mode": "scrape"})
    """

    name: str = "firecrawl_web_content" # 建议用更描述性的名字
    description: str = (
        "Fetches and extracts the main textual content from a given URL. "
        "Use 'scrape' mode (default) for a single page, or 'crawl' mode to follow links (use sparingly). "
        "Input should be a URL. Returns a textual summary of the content."
    )
    args_schema: Type[BaseModel] = FireCrawlInput

    # --- 配置属性 ---
    # API Key 可以通过 __init__ 传入，或者留空让 loader 从环境变量读取
    _api_key: Optional[str] = PrivateAttr(default=None) # 使用 PrivateAttr 避免 Pydantic 验证
    _api_url: Optional[str] = PrivateAttr(default=None)
    # 可以在 __init__ 中设置默认 mode 和 params，或者在 _run/_arun 中处理
    default_mode: str = "scrape" # 工具级别的默认模式
    default_params: Dict[str, Any] = Field(default_factory=dict) # 工具级别的默认参数

    # 添加 __init__ 以便可以传入 api_key (可选)
    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None,
                 mode: str = "scrape", params: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        # Pydantic V2 中，非 model 字段需要用 PrivateAttr 或在 model_config 中设置
        self._api_key = api_key
        self._api_url = api_url
        self.default_mode = mode
        self.default_params = params or {}
        # 检查 Loader 是否可用
        if not FIRECRAWL_LOADER_AVAILABLE:
            print("ERROR: FireCrawlLoader is unavailable. Please install required packages.")

    def _run(
        self,
        url: str,
        mode: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str: # <--- 返回值必须是字符串
        """使用工具同步获取网页内容。"""
        if not FIRECRAWL_LOADER_AVAILABLE:
            return "Error: FireCrawlLoader is not available. Required packages might be missing."
            
        # 确定使用的 API Key (优先实例属性，其次环境变量)
        key = self._api_key or os.getenv('FIRECRAWL_API_KEY')
        if not key:
             return "Error: FIRECRAWL_API_KEY not found in environment variables or instantiation."
        
        # 打印 Debug 信息 (可选)
        print(f"DEBUG [FireCrawlTool]: Running for URL='{url}', Mode='{mode or self.default_mode}'")
        # print(f"DEBUG [FireCrawlTool]: Effective API Key = {'*' * (len(key) - 4) + key[-4:] if key else 'None'}")

        try:
            current_mode = mode or self.default_mode
            loader = FireCrawlLoader(
                url=url,
                api_key=key, # 传递最终确定的 key
                api_url=self._api_url, # 传递实例属性或 None
                mode=current_mode,
                params=self.default_params, # 传递实例默认参数
            )

            print(f"--- Calling FireCrawl API (Sync) for: '{url}' ---")
            docs = loader.load()
            print(f"--- FireCrawl API call successful for: '{url}', received {len(docs)} document(s) ---")

            # --- 格式化结果为字符串 ---
            if not docs:
                return f"FireCrawl successful but returned no content from {url} (Mode: {current_mode}). The page might be empty or restricted."

            summary_parts = [f"Content summary from {url} (Mode: {current_mode}):"]
            content_limit = 4000 # 限制返回给 LLM 的总字符数 (可调整)
            current_length = len(summary_parts[0])
            doc_count = 0

            for doc in docs:
                 # 可以考虑只返回第一个文档的内容，如果文档很多
                 # if doc_count >= 1 and current_mode == 'scrape': break 
                 
                 source_info = f"\n\n--- Source: {doc.metadata.get('sourceURL', url)} ---"
                 page_content = doc.page_content or ""
                 
                 available_length = content_limit - current_length - len(source_info) - 20 # 预留空间
                 if available_length <= 0 and doc_count > 0: # 如果已经有内容且空间不足
                      summary_parts.append("\n\n... (further content truncated)")
                      break

                 content = source_info + "\n" + page_content
                 
                 if len(content) > available_length:
                      content = content[:available_length] + "... (truncated)"
                 
                 summary_parts.append(content)
                 current_length += len(content)
                 doc_count += 1
                 if current_length >= content_limit: break # 达到总长度限制

            return "\n".join(summary_parts).strip()
            # --- 格式化结束 ---

        except Exception as e:
            error_msg = f"Error during FireCrawl for {url} (Mode: {mode or self.default_mode}): {repr(e)}"
            print(f"ERROR: {error_msg}")
            return error_msg # 返回错误信息字符串

    async def _arun(
        self,
        url: str,
        mode: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str: # <--- 返回值必须是字符串
        """使用工具异步获取网页内容。"""
        if not FIRECRAWL_LOADER_AVAILABLE:
            return "Error: FireCrawlLoader is not available."
            
        key = self.api_key or os.getenv('FIRECRAWL_API_KEY')
        if not key:
             return "Error: FIRECRAWL_API_KEY not found."
        
        print(f"DEBUG [FireCrawlTool]: Running async for URL='{url}', Mode='{mode or self.default_mode}'")

        try:
            current_mode = mode or self.default_mode
            loader = FireCrawlLoader(
                url=url, api_key=key, api_url=self.api_url,
                mode=current_mode, params=self.default_params,
            )

            print(f"--- Calling FireCrawl API (Async) for: '{url}' ---")
            # 使用 aload 进行异步加载
            docs = await loader.aload()
            print(f"--- FireCrawl API call successful for: '{url}', received {len(docs)} document(s) ---")

            # --- 格式化结果为字符串 (与 _run 逻辑相同) ---
            if not docs: return f"FireCrawl successful but returned no content from {url} (Mode: {current_mode})."
            summary_parts = [f"Content summary from {url} (Mode: {current_mode}):"]
            content_limit = 4000; current_length = len(summary_parts[0]); doc_count = 0
            for doc in docs:
                 # if doc_count >= 1 and current_mode == 'scrape': break
                 source_info = f"\n\n--- Source: {doc.metadata.get('sourceURL', url)} ---"
                 page_content = doc.page_content or ""
                 available_length = content_limit - current_length - len(source_info) - 20
                 if available_length <= 0 and doc_count > 0:
                      summary_parts.append("\n\n... (further content truncated)"); break
                 content = source_info + "\n" + page_content
                 if len(content) > available_length: content = content[:available_length] + "... (truncated)"
                 summary_parts.append(content); current_length += len(content); doc_count += 1
                 if current_length >= content_limit: break
            return "\n".join(summary_parts).strip()
            # --- 格式化结束 ---

        except Exception as e:
            error_msg = f"Error during Async FireCrawl for {url} (Mode: {mode or self.default_mode}): {repr(e)}"
            print(f"ERROR: {error_msg}")
            return error_msg

    # Pydantic V2: 允许额外的私有属性
    model_config = {
        "arbitrary_types_allowed": True
    }