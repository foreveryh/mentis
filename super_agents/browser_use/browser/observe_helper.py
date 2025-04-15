"""
自定义 observe 装饰器，替代缺失的 lmnr.observe
"""
import functools
import asyncio
import logging
from typing import Any, Callable, Optional, TypeVar, cast

logger = logging.getLogger(__name__)

T = TypeVar('T')

def observe(name: Optional[str] = None, ignore_input: bool = False, ignore_output: bool = False):
    """
    简化版观察者装饰器，用于替代缺失的 lmnr.observe
    
    Args:
        name: 观察名称，默认为函数名
        ignore_input: 是否忽略输入参数的日志记录
        ignore_output: 是否忽略输出结果的日志记录
        
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = name or func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.debug(f"调用异步函数 {func_name}")
            if not ignore_input and len(args) > 1:
                logger.debug(f"{func_name} 参数: {args[1:] if len(args) > 1 else ''}")
            try:
                result = await func(*args, **kwargs)
                if not ignore_output:
                    logger.debug(f"{func_name} 返回结果类型: {type(result)}")
                return result
            except Exception as e:
                logger.error(f"{func_name} 执行出错: {e}")
                raise
                
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.debug(f"调用同步函数 {func_name}")
            if not ignore_input and len(args) > 1:
                logger.debug(f"{func_name} 参数: {args[1:] if len(args) > 1 else ''}")
            try:
                result = func(*args, **kwargs)
                if not ignore_output:
                    logger.debug(f"{func_name} 返回结果类型: {type(result)}")
                return result
            except Exception as e:
                logger.error(f"{func_name} 执行出错: {e}")
                raise
            
        return cast(Callable[..., T], async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper)
    return decorator
