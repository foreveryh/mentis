# reason_graph/model_config.py
from langchain_openai import ChatOpenAI
# from langchain_groq import ChatGroq # 不再需要
# (如果未来支持其他非 OpenAI 兼容的，在这里 import)

from .llm_manager import ModelType, ModelCapability # 从同级 llm_manager 导入枚举

# 定义支持的模型及其配置
# key 是我们内部使用的 model_id
SUPPORTED_MODELS_CONFIG = {
    "openai_gpt4o": {
        "model_type": ModelType.OPENAI,
        "model_name": "gpt-4o", # API 调用名
        "model_class": ChatOpenAI,
        "capabilities": [
            ModelCapability.GENERAL, ModelCapability.PLANNING, ModelCapability.REASONING,
            ModelCapability.CREATIVE, ModelCapability.LONG_CONTEXT, ModelCapability.CODE,
            ModelCapability.RESEARCH # GPT-4o 也能做一定研究
        ],
        "is_default": False, # 不设为默认
        "config_override": {}, # 允许覆盖 env vars, e.g., {'api_key': '...'}
        "kwargs": {"temperature": 0.1} # 传递给构造函数的额外参数
    },
    "openai_gpt4o_mini": {
        "model_type": ModelType.OPENAI,
        "model_name": "gpt-4o-mini",
        "model_class": ChatOpenAI,
        "capabilities": [ModelCapability.GENERAL, ModelCapability.REASONING, ModelCapability.CREATIVE],
        "is_default": True, # <--- 将其设为默认模型
        "config_override": {},
        "kwargs": {"temperature": 0.0}
    },
    "xai_grok": { # 假设 ID 命名为 xai_grok
        "model_type": ModelType.XAI,
        "model_name": "grok-2-latest", # 或者是 xAI API 实际接受的模型名
        "model_class": ChatOpenAI, # 假设使用兼容 OpenAI 的方式连接
        "capabilities": [ModelCapability.GENERAL, ModelCapability.REASONING, ModelCapability.LONG_CONTEXT, ModelCapability.CREATIVE],
        "is_default": False,
        "config_override": {}, # Key/URL 将从 env (XAI_API_KEY, XAI_BASE_URL) 加载
        "kwargs": {"temperature": 0.2}
    },
    "deepseek_v3": { # 假设 ID 命名为 deepseek_chat
        "model_type": ModelType.DEEPSEEK,
        "model_name": "deepseek/deepseek-v3-0324", # DeepSeek Chat 模型 API 名
        "model_class": ChatOpenAI, # 使用兼容 OpenAI 的方式连接
        "capabilities": [ModelCapability.GENERAL, ModelCapability.REASONING, ModelCapability.CODE, ModelCapability.LONG_CONTEXT],
        "is_default": False,
        "config_override": {}, # Key/URL 将从 env (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL) 加载
        "kwargs": {"temperature": 0.0}
    },
    # --- 可以继续添加其他模型配置 ---
    # "groq_llama3_70b": {
    #     "model_type": ModelType.GROQ,
    #     "model_name": "llama3-70b-8192",
    #     "model_class": ChatGroq, # 需要导入 ChatGroq
    #     "capabilities": [...],
    #     "is_default": False,
    #     "config_override": {},
    #     "kwargs": {"temperature": 0.1}
    # },
}