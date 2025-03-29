# reason_graph/llm_manager.py
import os
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Type, Union, Callable, Tuple
from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_openai import ChatOpenAI
# (移除 ChatGroq 导入)

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class ModelType(Enum):
    """模型提供商类型枚举"""
    OPENAI = auto()
    XAI = auto()
    DEEPSEEK = auto()
    CUSTOM = auto() # 保持用于其他 OpenAI 兼容 API

class ModelCapability(Enum):
    """模型能力枚举"""
    GENERAL = auto(); PLANNING = auto(); REASONING = auto()
    CREATIVE = auto(); RESEARCH = auto(); CODE = auto()
    LONG_CONTEXT = auto()

class LLMManager:
    """
    模型管理器 (融合版 V2)
    - 在初始化时根据配置自动注册模型。
    - 支持按能力获取模型。
    - 支持延迟实例化。
    - 从环境变量加载 API Keys/Base URLs。
    """

    def __init__(self):
        """初始化模型管理器，加载配置并自动注册模型"""
        self._models_config: Dict[str, Dict[str, Any]] = {}
        self._models_instance: Dict[str, BaseChatModel] = {}
        self._default_model_id: Optional[str] = None
        self._capability_models: Dict[ModelCapability, str] = {}

        # 加载 API Keys 和 Base URLs (保持不变)
        self._loaded_api_keys = {
            ModelType.OPENAI: os.getenv("OPENAI_API_KEY"),
            ModelType.XAI: os.getenv("XAI_API_KEY"),
            ModelType.DEEPSEEK: os.getenv("DEEPSEEK_API_KEY"),
            ModelType.CUSTOM: os.getenv("LLM_API_KEY"),
        }
        self._loaded_base_urls = {
            ModelType.OPENAI: os.getenv("OPENAI_BASE_URL"),
            ModelType.XAI: os.getenv("XAI_BASE_URL"),
            ModelType.DEEPSEEK: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            ModelType.CUSTOM: os.getenv("LLM_BASE_URL"),
        }
        print("LLMManager initialized.")
        print("Loaded API Keys for:", [k.name for k, v in self._loaded_api_keys.items() if v])
        print("Loaded Base URLs for:", {k.name: v for k, v in self._loaded_base_urls.items() if v})

        # --- 自动注册模型 ---
        try:
            from .model_config import SUPPORTED_MODELS_CONFIG # 从配置文件导入
            
            print("Registering models from config...")
            for model_id, config in SUPPORTED_MODELS_CONFIG.items():
                # 检查所需 Key/URL 是否存在，如果不存在则跳过注册并警告
                model_type = config.get("model_type")
                api_key = config.get("config_override", {}).get("api_key") or self._loaded_api_keys.get(model_type)
                base_url = config.get("config_override", {}).get("base_url") or self._loaded_base_urls.get(model_type)
                
                # OpenAI 可以只依赖 OPENAI_API_KEY 环境变量
                if model_type == ModelType.OPENAI and not api_key:
                    api_key = os.getenv("OPENAI_API_KEY") # 再次检查 OpenAI 专用 Key

                # 对于需要 Key 的类型进行检查
                key_required = model_type not in [ModelType.CUSTOM] # 假设 CUSTOM 可能匿名
                url_required = model_type in [ModelType.XAI, ModelType.CUSTOM] # DeepSeek 有默认值

                if key_required and not api_key:
                    print(f"  Skipping registration for '{model_id}': Required API key for type '{model_type.name}' not found.")
                    continue
                if url_required and not base_url:
                     print(f"  Skipping registration for '{model_id}': Required Base URL for type '{model_type.name}' not found.")
                     continue

                # 调用内部注册方法
                self._register_model(
                    model_id=model_id,
                    model_type=config["model_type"],
                    model_name=config["model_name"],
                    model_class=config.get("model_class"), # 可能为 None
                    capabilities=config.get("capabilities", [ModelCapability.GENERAL]),
                    set_as_default=config.get("is_default", False),
                    config_override=config.get("config_override"),
                    **config.get("kwargs", {})
                )
            print("Model registration complete.")
            # 可以在这里设置一个环境变量的默认模型 ID，如果配置中没有 is_default=True
            if not self._default_model_id and self._models_config:
                 fallback_default = list(self._models_config.keys())[0]
                 print(f"Warning: No default model marked in config. Falling back to first registered: '{fallback_default}'")
                 self._default_model_id = fallback_default


        except ImportError:
            print("Warning: Could not import model_config.py. No models registered automatically.")
        except Exception as e:
            print(f"Error during automatic model registration: {e}")

        print(f"Default model set to: {self._default_model_id}")
        print(f"Capability mapping: {self.list_capabilities()}")
        print("-" * 20)


    # register_model 现在是内部方法
    def _register_model(
        self, model_id: str, model_type: ModelType, model_name: str,
        model_class: Optional[Type[BaseChatModel]] = None,
        capabilities: List[ModelCapability] = [ModelCapability.GENERAL],
        set_as_default: bool = False,
        config_override: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """(Internal) Registers a model configuration."""
        if model_id in self._models_config:
            # Decide on behavior: overwrite or ignore? Let's overwrite with warning.
            print(f"  Overwriting registration for existing model_id: '{model_id}'")
            # pass # If ignore is preferred

        if model_class is None:
            model_class = ChatOpenAI

        self._models_config[model_id] = {
            "type": model_type, "name": model_name, "class": model_class,
            "capabilities": list(set(capabilities)),
            "config_override": config_override or {},
            "kwargs": kwargs,
        }
        print(f"  Registered model config: '{model_id}' (Type: {model_type.name}, Class: {model_class.__name__})")

        if set_as_default:
            self._default_model_id = model_id
            print(f"    Set '{model_id}' as default.")

        for capability in capabilities:
            if capability not in self._capability_models:
                self._capability_models[capability] = model_id
                print(f"    Mapped capability '{capability.name}' to '{model_id}'.")

    def set_default_model(self, model_id: str) -> None:
        """设置默认模型"""
        if model_id not in self._models_config: raise ValueError(...)
        self._default_model_id = model_id

    def set_capability_model(self, capability: ModelCapability, model_id: str) -> None:
        """设置特定能力的模型"""
        if model_id not in self._models_config: raise ValueError(...)
        model_info = self._models_config[model_id]
        if capability not in model_info.get("capabilities", []):
              print(f"Warning: Model '{model_id}' not registered with capability '{capability.name}'.")
        self._capability_models[capability] = model_id

    # _get_instance (核心实例化逻辑)
    def _get_instance(self, model_id: str) -> BaseChatModel:
        """(Internal) Gets or creates a model instance."""
        if model_id in self._models_instance:
            return self._models_instance[model_id]

        if model_id not in self._models_config:
            raise ValueError(f"Model ID '{model_id}' not registered or registration skipped due to missing config.")

        config = self._models_config[model_id]
        model_type = config["type"]
        model_name = config["name"]
        model_class = config["class"]
        config_override = config["config_override"]
        kwargs = config["kwargs"]

        # 确定 Key/URL (优先 override, 其次 env)
        api_key = config_override.get("api_key", self._loaded_api_keys.get(model_type))
        base_url = config_override.get("base_url", self._loaded_base_urls.get(model_type))

        # OpenAI 特殊 Key 处理
        if model_type == ModelType.OPENAI and not api_key:
            api_key = os.getenv("OPENAI_API_KEY")

        # 检查必要配置
        key_required = model_type not in [ModelType.CUSTOM]
        url_required = model_type in [ModelType.XAI, ModelType.DEEPSEEK, ModelType.CUSTOM]
        if key_required and not api_key:
            raise ValueError(f"API key required but not found for '{model_id}' (Type: {model_type.name}). Set in .env or config_override.")
        if url_required and not base_url:
            raise ValueError(f"Base URL required but not found for '{model_id}' (Type: {model_type.name}). Set in .env or config_override.")

        print(f"Instantiating model: ID='{model_id}', Type='{model_type.name}', Name='{model_name}'")

        # 准备构造函数参数
        init_kwargs = kwargs.copy()
        if model_class == ChatOpenAI:
             init_kwargs['model'] = model_name
             if api_key: init_kwargs['openai_api_key'] = api_key
             if base_url: init_kwargs['openai_api_base'] = base_url
        # elif model_class == ChatGroq: ... # Removed
        else: # 尝试通用参数
             init_kwargs['model'] = model_name # 很多兼容类可能也认 model
             init_kwargs['model_name'] = model_name
             if api_key: init_kwargs['api_key'] = api_key
             if base_url: init_kwargs['base_url'] = base_url

        # 移除内部配置键
        for k in ["config_override", "capabilities", "type", "class", "name", "instance"]:
            init_kwargs.pop(k, None)
            
        # 实例化
        try:
            instance = model_class(**init_kwargs)
            self._models_instance[model_id] = instance
            return instance
        except Exception as e:
            print(f"!!! Failed to instantiate model '{model_id}'")
            raise e

    # get_model 和 get_model_for_capability (保持不变, 调用 _get_instance)
    def get_model(self, model_id: Optional[str] = None) -> BaseChatModel:
        """获取模型实例 (通过 ID 或默认)"""
        target_id = model_id
        if target_id is None:
            if self._default_model_id is None: raise ValueError("No default model set.")
            target_id = self._default_model_id
        if target_id not in self._models_config: raise ValueError(f"Model ID '{target_id}' not registered.")
        return self._get_instance(target_id)

    def get_model_for_capability(self, capability: ModelCapability) -> BaseChatModel:
        """获取具有特定能力的模型实例"""
        if capability not in self._capability_models:
            print(f"No preferred model for '{capability.name}'. Falling back to default.")
            if self._default_model_id is None: raise ValueError(f"No model for '{capability.name}' and no default set.")
            model_id = self._default_model_id
        else: model_id = self._capability_models[capability]
        print(f"Using model '{model_id}' for capability '{capability.name}'.")
        return self.get_model(model_id)

    # list_models 和 list_capabilities (保持不变)
    def list_models(self) -> Dict[str, Dict[str, Any]]:
        """列出所有注册的模型及其配置"""
        result = {}; # ... (populate result) ...
        for model_id, model_info in self._models_config.items():
            result[model_id] = {
                "type": model_info["type"].name,
                "name": model_info["name"],
                "class": model_info["class"].__name__,
                "capabilities": [c.name for c in model_info.get("capabilities", [])],
                "is_default": model_id == self._default_model_id,
                "kwargs": model_info.get("kwargs"),
                "config_override": model_info.get("config_override"),
            }
        return result

    def list_capabilities(self) -> Dict[str, str]:
        return {capability.name: model_id for capability, model_id in self._capability_models.items()}