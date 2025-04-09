# core/mcp/config_loader.py (修改 load_config 返回类型)
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Literal, Union, Type # 导入 Type
try:
    from pydantic.v1 import BaseModel, Field, ValidationError, validator
    PYDANTIC_V = 1
except ImportError:
    try:
        from pydantic import BaseModel, Field, ValidationError, validator # type: ignore
        PYDANTIC_V = 2
    except ImportError: raise ImportError("Pydantic (v1 or v2) required.")
from typing_extensions import TypedDict

EncodingErrorHandler = Literal["strict", "ignore", "replace"]

class StdioConfig(BaseModel):
    transport: Literal["stdio"] = "stdio"; command: str = Field(...)
    args: List[str] = Field(default_factory=list); env: Optional[Dict[str, str]] = None
    cwd: Optional[Union[str, Path]] = None; encoding: str = Field(default="utf-8")
    encoding_error_handler: EncodingErrorHandler = Field(default="strict")
    timeout: int = Field(default=30, gt=0); session_kwargs: Optional[Dict[str, Any]] = None
    if PYDANTIC_V == 1: 
        class Config: extra = 'forbid'
    else: model_config = {'extra': 'forbid'}

class SSEConfig(BaseModel):
    transport: Literal["sse"] = "sse"; url: str = Field(...)
    headers: Optional[Dict[str, Any]] = None; timeout: float = Field(default=5.0, gt=0)
    sse_read_timeout: float = Field(default=300.0, gt=0); session_kwargs: Optional[Dict[str, Any]] = None
    if PYDANTIC_V == 1: 
        class Config: extra = 'forbid'
    else: model_config = {'extra': 'forbid'}

class MCPConfig(BaseModel):
    """Represents the structure for a single server configuration."""
    id: Optional[str] = Field(default=None)
    type: Literal["mcp-server"] = Field(default="mcp-server")
    description: Optional[str] = Field(default=None)
    connection: Union[StdioConfig, SSEConfig] = Field(..., discriminator='transport')
    if PYDANTIC_V == 1: 
        class Config: extra = 'forbid'
    else: model_config = {'extra': 'forbid'}


# --- 修改 load_config ---
def load_config(config_path: Union[str, Path]) -> Dict[str, MCPConfig]:
    """
    Loads the central MCP configuration JSON file and validates each server entry.

    Args:
        config_path: Path to the central config.json file.

    Returns:
        A dictionary where keys are server names and values are validated MCPConfig objects.
    """
    config_p = Path(config_path).resolve()
    if not config_p.is_file():
        raise FileNotFoundError(f"Configuration file not found at: {config_p}")

    print(f"DEBUG: Loading central MCP configuration from: {config_p}")
    validated_configs: Dict[str, MCPConfig] = {}
    try:
        with open(config_p, 'r', encoding='utf-8') as f:
            raw_config_dict = json.load(f)

        if not isinstance(raw_config_dict, dict):
            raise TypeError("Root configuration must be a JSON object (dictionary).")

        # 遍历字典中的每个服务器配置并验证
        for server_name, config_data in raw_config_dict.items():
            print(f"DEBUG: Validating config for server: '{server_name}'")
            if not isinstance(config_data, dict):
                 print(f"WARNING: Entry for '{server_name}' is not a dictionary. Skipping.")
                 continue
            try:
                 # 确保 connection 和 transport 存在
                 if 'connection' not in config_data: raise ValueError("Missing 'connection'")
                 if 'transport' not in config_data.get('connection', {}): raise ValueError("Missing 'transport' in connection")

                 if PYDANTIC_V == 2:
                      validated_config = MCPConfig.model_validate(config_data)
                 else: # Pydantic V1
                      validated_config = MCPConfig.parse_obj(config_data)
                 validated_configs[server_name] = validated_config
                 print(f"DEBUG: Config for '{server_name}' validated successfully.")
            except (ValidationError, ValueError) as e_val:
                 print(f"ERROR: Validation failed for server '{server_name}' config:\n{e_val}\nSkipping this server.")
                 #可以选择继续加载其他配置，或者在这里 raise 让整个加载失败

        if not validated_configs:
             print("WARNING: No valid server configurations were loaded.")

        print(f"DEBUG: Central configuration loaded. Found {len(validated_configs)} valid server configs.")
        return validated_configs
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to decode JSON from {config_p}: {e}"); raise
    except Exception as e:
        print(f"ERROR: An unexpected error occurred loading config {config_p}: {e}"); raise