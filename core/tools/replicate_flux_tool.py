# 文件路径: core/tools/replicate_flux_tool.py (或类似)

import os
import asyncio
import json
from typing import Dict, Any, Optional, Type, List, Literal
from pydantic import BaseModel, Field, PrivateAttr
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)

# --- Replicate Client ---
try:
    import replicate
    REPLICATE_AVAILABLE = True
except ImportError:
    replicate = None # type: ignore
    REPLICATE_AVAILABLE = False
    print("Warning: 'replicate' package not installed (pip install replicate). ReplicateFluxImageTool will not work.")

# --- Tool Category (可选, 用于 Registry) ---
try:
    from .registry import ToolCategory, register_tool
    if not hasattr(ToolCategory, 'IMAGE_GENERATION'):
         ToolCategory.IMAGE_GENERATION = ToolCategory.OTHER
    category = ToolCategory.IMAGE_GENERATION
except ImportError:
    category = None
    print("Tool registry not found. Cannot auto-register ReplicateFluxImageTool.")


# --- Input Schema based on flux-dev ---
class ReplicateFluxToolInput(BaseModel):
    """Input schema for the Replicate Flux Image Generator Tool."""
    prompt: str = Field(description="Required. Detailed text description of the image to be generated.")
    aspect_ratio: Literal["1:1", "16:9", "21:9", "3:2", "2:3", "4:5", "5:4", "3:4", "4:3", "9:16", "9:21"] = Field(
        default="1:1", description="Aspect ratio for the generated image."
    )
    num_outputs: int = Field(
        default=1, description="Number of images to generate (1-4).", ge=1, le=4
    )
    guidance: float = Field(
        default=3.0, description="Guidance scale (0-10).", ge=0, le=10
    )
    num_inference_steps: int = Field(
        default=28, description="Number of denoising steps (1-50). Lower is faster, lower quality.", ge=1, le=50
    )
    seed: Optional[int] = Field(default=None, description="Random seed for reproducible generation.")
    # Add other relevant fields from the schema if needed, e.g., megapixels, output_format
    # megapixels: Literal["1", "0.25"] = Field(default="1", description="Approximate megapixels for output.")
    # output_format: Literal["webp", "jpg", "png"] = Field(default="webp", description="Output image format.")


# --- Tool Class (修正返回值处理) ---
class ReplicateFluxImageTool(BaseTool):
    """Generates images using 'black-forest-labs/flux-dev' on Replicate."""
    name: str = "replicate_flux_image_generator"
    description: str = (
        "Generates high-quality images based on a detailed text prompt using the Flux model on Replicate. "
        "Specify 'prompt' and optionally other parameters like 'aspect_ratio'. "
        "Returns a string containing the URL(s) of the generated image(s)."
    )
    args_schema: Type[BaseModel] = ReplicateFluxToolInput
    _client: Any = PrivateAttr(default=None)
    _is_available: bool = PrivateAttr(default=False)
    _init_error: Optional[str] = PrivateAttr(default=None)
    model_identifier: str = "black-forest-labs/flux-dev"

    def __init__(self, api_token: Optional[str] = None, model_id: Optional[str] = None, **kwargs):
        """Initialize the Replicate client."""
        super().__init__(**kwargs)
        if not REPLICATE_AVAILABLE: self._init_error = "..."; print(f"ERROR: {self._init_error}"); return
        token = api_token or os.getenv("REPLICATE_API_TOKEN")
        if not token: self._init_error = "..."; print(f"ERROR: {self._init_error}"); return
        try:
            print("Initializing Replicate client...")
            self._client = replicate.Client(api_token=token)
            print("Replicate client initialized successfully.")
            self._is_available = True; self._init_error = None
            if model_id: self.model_identifier = model_id
        except Exception as e: self._init_error = f"...: {e}"; print(f"ERROR: {self._init_error}"); self._is_available = False

    def _run( self, run_manager: Optional[CallbackManagerForToolRun] = None, **kwargs: Any ) -> str:
        """Generates image(s) synchronously."""
        if not self._is_available or self._client is None:
             error_message = f"Replicate client unavailable: {self._init_error}"
             print(f"ERROR: {error_message}"); return f"Error: {error_message}"

        input_data = {k: v for k, v in kwargs.items() if v is not None and k in self.args_schema.__fields__}
        prompt_short = str(input_data.get('prompt', ''))[:100]
        print(f"--- TOOL CALL: {self.name} ---")
        print(f"   Input: Prompt='{prompt_short}...', Args={ {k:v for k,v in input_data.items() if k != 'prompt'} }")

        try:
            # output 现在预期是包含特殊对象 (如 FileOutput 或 URL 字符串) 的列表
            output: List[Any] = self._client.run(self.model_identifier, input=input_data)

            if not output or not isinstance(output, list):
                result_str = "Image generation failed: Replicate API returned no output or unexpected format."
                print(f"   Warning: {result_str}"); return f"Error: {result_str}"

            # --- 从返回的对象中提取 URL ---
            image_urls: List[str] = []
            for item in output:
                if isinstance(item, str): # 如果直接返回了 URL 字符串
                    image_urls.append(item)
                elif hasattr(item, 'url') and isinstance(getattr(item, 'url'), str): # 检查是否有 .url 属性且是字符串
                    image_urls.append(getattr(item, 'url'))
                elif hasattr(item, 'read'): # 如果是文件类对象，可能需要其他处理或报错
                     print(f"Warning: Received file-like object from Replicate, cannot directly get URL: {item}")
                     # 或者尝试其他属性？这个需要根据 replicate 库的具体 FileOutput 类型确定
                else:
                     print(f"Warning: Unknown item type in Replicate output list: {type(item)}")

            if not image_urls:
                 result_str = "Image generation succeeded but failed to extract image URLs from the response."
                 print(f"   Warning: {result_str}"); return f"Error: {result_str}"
            # --- 提取结束 ---

            # 格式化 URL 列表为字符串
            url_list_str = "\n".join(image_urls)
            result_str = f"Successfully generated {len(image_urls)} image(s):\n{url_list_str}"
            print(f"   Result: {result_str}")
            return result_str

        except Exception as e: # 捕获 Replicate API 错误等
            # 检查是否是 ReplicateError 并提取更具体的细节
            error_detail = str(e)
            if REPLICATE_AVAILABLE and isinstance(e, replicate.exceptions.ReplicateError):
                 error_detail = f"ReplicateError (Status: {e.status}): {e.title} - {e.detail}"

            error_msg = f"Error calling Replicate API ({self.model_identifier}): {error_detail}"
            print(f"   Error: {error_msg}")
            # traceback.print_exc() # 可以在调试时取消注释
            return f"Error: {error_msg}" # 返回错误信息给 LLM

    async def _arun( self, run_manager: Optional[AsyncCallbackManagerForToolRun] = None, **kwargs: Any ) -> str:
        """Generates image(s) asynchronously using run_in_executor."""
        if not self._is_available or self._client is None:
             error_message = f"Replicate client unavailable: {self._init_error}"
             print(f"ERROR: {error_message}"); return f"Error: {error_message}"

        input_data = {k: v for k, v in kwargs.items() if v is not None and k in self.args_schema.__fields__}
        prompt_short = str(input_data.get('prompt', ''))[:100]
        print(f"--- TOOL CALL (Async): {self.name} ---")
        print(f"   Input: Prompt='{prompt_short}...', Args={ {k:v for k,v in input_data.items() if k != 'prompt'} }")

        try:
            loop = asyncio.get_running_loop()
            import functools
            sync_call_with_args = functools.partial( self._client.run, self.model_identifier, input=input_data )
            output: List[Any] = await loop.run_in_executor( None, sync_call_with_args )

            if not output or not isinstance(output, list):
                result_str = "Async image generation failed: Replicate API returned no output or unexpected format."
                print(f"   Warning: {result_str}"); return f"Error: {result_str}"

            # --- 从返回的对象中提取 URL (逻辑同 _run) ---
            image_urls: List[str] = []
            for item in output:
                if isinstance(item, str): image_urls.append(item)
                elif hasattr(item, 'url') and isinstance(getattr(item, 'url'), str): image_urls.append(getattr(item, 'url'))
                else: print(f"Warning: Unknown item type in async Replicate output list: {type(item)}")
            if not image_urls:
                 result_str = "Async image generation succeeded but failed to extract image URLs."
                 print(f"   Warning: {result_str}"); return f"Error: {result_str}"
            # --- 提取结束 ---

            url_list_str = "\n".join(image_urls)
            result_str = f"Successfully generated {len(image_urls)} image(s) asynchronously:\n{url_list_str}"
            print(f"   Result: {result_str}")
            return result_str

        except Exception as e: # 捕获 Replicate API 错误等
            error_detail = str(e)
            if REPLICATE_AVAILABLE and isinstance(e, replicate.exceptions.ReplicateError):
                 error_detail = f"ReplicateError (Status: {e.status}): {e.title} - {e.detail}"
            error_msg = f"Error calling Replicate API asynchronously ({self.model_identifier}): {error_detail}"
            print(f"   Error: {error_msg}")
            # traceback.print_exc()
            return f"Error: {error_msg}"


    def close(self):
        """关闭沙箱（如果需要的话）。Replicate Client 通常不需要关闭。"""
        print(f"Info: Replicate client for '{self.name}' does not require explicit closing.")
        pass # Replicate client 通常不需要显式关闭

    model_config = {"arbitrary_types_allowed": True}
