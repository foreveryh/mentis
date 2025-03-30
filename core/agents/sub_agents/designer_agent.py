# 文件路径示例: reason_graph/designer_agent.py

from typing import Any, List, Optional, Union, Callable, Type
from langchain_core.language_models import LanguageModelLike # 确保导入正确类型
from langchain_core.tools import BaseTool
from langchain_core.messages import SystemMessage
from langgraph.types import Checkpointer

# 内部导入
from core.agents.base.react_agent import ReactAgent
from core.tools.registry import get_tools_by_category, ToolCategory # 导入 Registry
# 假设您的 Flux 工具已注册或在此导入
# from core.tools.flux_image_tool import FluxImageGeneratorTool 

import logging
logger = logging.getLogger(__name__)

# 假设的 ToolCategory.IMAGE_GENERATION
if not hasattr(ToolCategory, 'IMAGE_GENERATION'):
     ToolCategory.IMAGE_GENERATION = ToolCategory.OTHER

class DesignerAgent(ReactAgent):
    """
    设计 Agent (重构版)
    - 能够理解图像上下文，并使用工具生成新的视觉内容。
    - 应用设计原则来完成海报、网页等设计任务。
    """

    def __init__(
        self,
        name: str = "designer_expert",
        model: LanguageModelLike = None, # <--- 必须传入多模态模型 (e.g., gpt-4o)
        tools: Optional[List[Union[BaseTool, Callable]]] = None,
        checkpointer: Optional[Checkpointer] = None,
        max_context_messages: Optional[int] = None,
        max_context_tokens: Optional[int] = 8000, # 调整上下文需求
        debug: bool = False,
        **kwargs
    ):
        # 1. 定义 Agent 描述
        description = "Understands images provided in context and generates new visual content (images, mockups, diagrams) using specialized image generation tools (like Flux). Can apply design thinking for tasks like poster or web page layout design."

        # 2. 获取工具 (主要是图像生成工具)
        agent_tools = []
        try:
            # 从 Registry 获取图像生成工具
            img_tools = get_tools_by_category(ToolCategory.IMAGE_GENERATION)
            agent_tools.extend(img_tools)
            # 也可以直接实例化
            # agent_tools.append(FluxImageGeneratorTool()) # 如果不使用 Registry
            print(f"[{name}] Loaded tools: {[t.name for t in agent_tools if hasattr(t,'name')]}")
        except Exception as e:
             print(f"Warning: Failed to get IMAGE_GENERATION tools for {name}: {e}")

        if tools: # 合并额外工具
             existing_names = {t.name for t in agent_tools if hasattr(t,'name')}
             agent_tools.extend([t for t in tools if getattr(t, 'name', None) not in existing_names])

        if not agent_tools:
             print(f"CRITICAL Warning: DesignerAgent '{name}' initialized with NO generation tools!")

        # 3. 定义 System Prompt
        tool_name_for_prompt = next((t.name for t in agent_tools if hasattr(t, 'name') and 'generat' in t.name.lower()), "image_generator_tool") # 获取工具名

        base_prompt = f"""You are an expert Visual Designer and Creative Assistant. Your capabilities include understanding images provided in the conversation history and generating new images using available tools based on detailed text prompts.

Available Tools:
{self._format_tools_for_prompt(agent_tools)}
- **{tool_name_for_prompt}**: Use this tool to generate images. Input requires a detailed 'prompt'.

Key Instructions & Workflow:

1.  **Understand Request**: Analyze the user request, paying attention to both text and any images provided in the message history. Identify the core visual goal (e.g., analyze image, generate image, design layout).
2.  **Image Understanding (If Applicable)**: If the request involves analyzing or describing an existing image from the history, provide your analysis directly based on your multimodal understanding.
3.  **Design Thinking (For Generation/Design Tasks)**:
    * **Clarify**: If the request is vague (e.g., "design a logo"), think about necessary elements: target audience, brand feeling, key symbols, color preferences, desired style (minimalist, vintage, futuristic, etc.). You might need to state assumptions if details are missing.
    * **Conceptualize**: Describe the visual elements, layout, color palette, and overall composition you plan to generate.
    * **Formulate Prompt for Tool**: Translate your design concept into a **highly detailed and descriptive text prompt** suitable for the `{tool_name_for_prompt}`. Include style, mood, composition, colors, and specific objects.
4.  **Use Generation Tool**: Call the `{tool_name_for_prompt}` with the detailed prompt you formulated.
5.  **Present Result**:
    * State that you have generated the image.
    * Provide the result from the tool (e.g., the image URL or identifier).
    * Briefly describe the generated image and how it matches the design concept or request.
    * **Important**: Do NOT attempt to display the image directly in your text response. Only provide the URL or description.
6.  **Handle Errors**: If the tool fails, report the error clearly.

Focus on visual design and generation tasks. Use your understanding of design principles when conceptualizing visuals for requests like posters or web mockups.
"""

        # 4. 调用父类 __init__
        super().__init__(
            name=name,
            model=model, # 必须是多模态模型
            tools=agent_tools,
            prompt=base_prompt,
            description=description,
            checkpointer=checkpointer,
            max_context_messages=max_context_messages,
            max_context_tokens=max_context_tokens,
            debug=debug,
            **kwargs
        )
        print(f"DesignerAgent '{self.name}' initialized.")

    # 继承 _format_tools_for_prompt 和其他 BaseAgent/ReactAgent 方法