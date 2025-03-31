# core/tools/e2b_tool.py

import os
import json
import asyncio
import traceback
from typing import Dict, Any, Optional, Type, List # 确保导入 List
from pydantic import BaseModel, Field, PrivateAttr
from langchain_core.tools import BaseTool


# --- E2B Imports ---
try:
    from e2b import Sandbox, SandboxException, TimeoutException # <--- 修改导入，从 'e2b' 导入
    E2B_AVAILABLE = True
except ImportError:
    Sandbox = None # type: ignore
    SandboxException = Exception # type: ignore # Fallback to base Exception
    TimeoutException = TimeoutError # type: ignore # Fallback to base TimeoutError
    E2B_AVAILABLE = False
    print("Warning: 'e2b' package not installed (pip install e2b). E2BCodeInterpreterTool will not work.")

# --- Tool Category ---
try:
    from .registry import ToolCategory, register_tool
    if not hasattr(ToolCategory, 'CODE_INTERPRETER'):
         ToolCategory.CODE_INTERPRETER = ToolCategory.OTHER
    category = ToolCategory.CODE_INTERPRETER
except ImportError:
    category = None
    print("Tool registry not found.")

# --- Input Schema (保持不变) ---
class E2BCodeInterpreterToolInput(BaseModel):
    code: str = Field(description="要执行的Python代码")

# --- Tool Class (优化版) ---
class E2BCodeInterpreterTool(BaseTool):
    """
    使用 E2B SDK 在安全沙箱中执行 Python 代码的工具 (修正异常处理版)。
    返回执行结果的字符串摘要。
    """
    name: str = "e2b_code_interpreter"
    description: str = ( # 可以稍微调整描述，强调是 Python 执行环境
        "Executes Python code in a sandboxed environment. "
        "Input MUST be a JSON object with a 'code' key containing the Python code string. "
        "Libraries like matplotlib, pandas, numpy, sympy are available. Install others using pip (e.g., `import subprocess; subprocess.run(['pip', 'install', 'requests'])`). "
        "Use 'print()' to output results. For plots, save them to a file (e.g., '/home/user/plot.png') and state the path; do not return raw image data. "
        "Returns a string summarizing execution status, stdout, stderr, and any errors."
    )
    args_schema: Type[BaseModel] = E2BCodeInterpreterToolInput

    _sandbox: Optional[Any] = PrivateAttr(default=None)
    _is_available: bool = PrivateAttr(default=False)
    _init_error: Optional[str] = PrivateAttr(default=None)
    # 不再需要 self.ExceptionClass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._initialize_sandbox()

    def _initialize_sandbox(self):
        """初始化沙箱环境"""
        if not E2B_AVAILABLE:
            self._init_error = "Package 'e2b' not installed."
            print(f"ERROR: {self._init_error}")
            return

        if "E2B_API_KEY" not in os.environ:
            self._init_error = "Environment variable E2B_API_KEY not set."
            print(f"ERROR: {self._init_error}")
            return

        try:
            print("Initializing E2B Sandbox...")
            # 实例化 Sandbox
            self._sandbox = Sandbox() # 使用导入的 Sandbox 类
            print("E2B Sandbox initialized successfully!")
            self._is_available = True
            self._init_error = None
        except (SandboxException, TimeoutException) as e: # <--- 捕获特定的 E2B 异常
            self._init_error = f"Failed to initialize E2B Sandbox (E2B Error): {e}"
            print(f"ERROR: {self._init_error}")
            self._is_available = False
        except Exception as e: # 捕获其他意外错误
            self._init_error = f"An unexpected error occurred during E2B Sandbox initialization: {e}"
            print(f"ERROR: {self._init_error}")
            self._is_available = False

    def _run(self, code: str, **kwargs) -> str:
        """同步执行 Python 代码并返回结果摘要字符串"""
        if not self._is_available or self._sandbox is None:
            # ... (返回包含设置指南的错误信息，不变) ...
            error_message = "E2B Sandbox is not available"
            if self._init_error: error_message += f": {self._init_error}"
            setup_guide = "\n\nSetup: pip install e2b; export E2B_API_KEY='...'"
            return f"Execution Failed: {error_message}{setup_guide}"

        output_summary = ""
        try:
            print(f"--- E2B: Executing code synchronously ---\n{code}\n--------------------------------------")
            # 使用 run_python 方法
            execution = self._sandbox.run_python(code)

            # 构建结果字符串 (逻辑保持不变)
            if execution.error:
                output_summary += f"Execution Failed!\nError Name: {execution.error.name}\nError Value: {execution.error.value}\n"
                if execution.error.traceback:
                     traceback_lines = execution.error.traceback.splitlines()
                     output_summary += f"Traceback (last few lines):\n...\n" + "\n".join(traceback_lines[-5:])
            else:
                 output_summary += "Execution Successful.\n"
            if execution.logs.stdout: output_summary += f"\nSTDOUT:\n{execution.logs.stdout}"
            if execution.logs.stderr: output_summary += f"\nSTDERR:\n{execution.logs.stderr}"
            if execution.results: output_summary += "\n\nNote: Execution produced structured results (e.g., plots saved as files)."
            if not output_summary.strip() or output_summary.strip() == "Execution Successful.": output_summary = "Code executed successfully with no textual output."

            print(f"--- E2B: Execution finished ---\nResult Summary:\n{output_summary[:500]}...\n-----------------------------")
            return output_summary.strip()

        except (SandboxException, TimeoutException) as e: # <--- 捕获特定的 E2B 异常
             error_str = f"Execution Failed (E2B Error)!\nError Name: {getattr(e, 'name', type(e).__name__)}\nDetails: {e}"
             # TimeoutException 可能没有 traceback 属性，SandboxException 通常有
             tb = getattr(e, 'traceback', traceback.format_exc())
             if tb:
                 tb_lines = tb.splitlines()
                 error_str += f"\nTraceback (last few lines):\n...\n" + "\n".join(tb_lines[-5:])
             print(f"ERROR during E2B execution: {error_str}")
             return error_str
        except Exception as e: # 其他错误
            error_str = f"Execution Failed (Unexpected Error)!\nError Type: {type(e).__name__}\nError Details: {str(e)}\nTraceback:\n{traceback.format_exc()}"
            print(f"ERROR during E2B execution: {error_str}")
            return error_str

    async def _arun(self, code: str, **kwargs) -> str:
        """异步执行 Python 代码并返回结果摘要字符串"""
        if not self._is_available or self._sandbox is None:
             # ... (返回错误信息) ...
             error_message = f"E2B Sandbox is not available: {self._init_error}"
             return f"Execution Failed: {error_message}"

        try:
            loop = asyncio.get_running_loop()
            import functools
            # 注意：传递给 run_in_executor 的函数应该是可调用的
            # 这里 _run 是实例方法，所以直接传递 self._run 即可
            # 但为了确保 code 参数被正确传递，可以用 lambda 或 partial
            sync_run_with_args = functools.partial(self._run, code=code, **kwargs)

            print(f"--- E2B: Executing code asynchronously via executor ---\n{code}\n--------------------------------------")
            result_summary = await loop.run_in_executor(
                None, sync_run_with_args
            )
            print(f"--- E2B: Async execution finished ---")
            return result_summary
        except Exception as e: # run_in_executor 或 _run 的异常会在这里捕获
            error_str = f"Execution Failed (Async Wrapper Error)!\nError Type: {type(e).__name__}\nError Details: {str(e)}"
            # 尝试获取 Traceback
            tb = traceback.format_exc()
            error_str += f"\nTraceback:\n{tb}"
            print(f"ERROR during E2B async execution: {error_str}")
            return error_str


    def close(self):
        """关闭沙箱，释放资源。"""
        if hasattr(self, "sandbox") and self._is_available and self._sandbox is not None:
            try:
                print("Attempting to close E2B Sandbox...")
                self._sandbox.close() # <--- E2B SDK 通常使用 close()
                print("E2B Sandbox closed successfully.")
                self._is_available = False
                self._sandbox = None
            except (SandboxException, TimeoutException) as e: # 捕获特定异常
                print(f"Error closing E2B Sandbox (E2B Error): {e}")
            except Exception as e:
                print(f"An unexpected error occurred while closing E2B Sandbox: {e}")

    model_config = {
        "arbitrary_types_allowed": True
    }

    # __del__ 方法用于对象销毁，通常不保证执行，不建议依赖它来关闭资源
    # def __del__(self): self.close()