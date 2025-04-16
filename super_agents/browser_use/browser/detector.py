# super_agents/browser_use/browser/detector.py
import os
import json
import logging
import base64
from typing import List, Optional, Dict, Any

# LangChain Core Imports
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.base import RunnableSerializable
# Pydantic for schema
try:
    from pydantic.v1 import BaseModel
except ImportError:
    from pydantic import BaseModel

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Local imports (ensure they exist)
try:
    from .observe_helper import observe
except ImportError:
    def observe(name, ignore_input=False, ignore_output=False):
        def decorator(func): return func
        return decorator
    # Setup basic logger if not configured by main app yet
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.warning("observe_helper not found, using dummy decorator.")
try:
    from .models import InteractiveElement
    # Define the expected VLM output schema here or import from agent.schemas
    # Let's define it here for clarity in this step
    class VLMJsonOutput(BaseModel):
        detected_elements: List[Dict[str, Any]] = []
except ImportError:
    class InteractiveElement: pass
    class VLMJsonOutput(BaseModel): detected_elements: List = []
    # Setup basic logger if not configured by main app yet
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import InteractiveElement or define VLMJsonOutput! Detector parsing will fail.")

# Import the specific ChatOpenRouter class from the updated llm.py
# Adjust path if llm.py is elsewhere relative to detector.py
try:
    from ..llm import ChatOpenRouter # Assumes llm.py is one level up
except ImportError:
     logger.error("Failed to import ChatOpenRouter from ..llm. Ensure llm.py is in the parent directory.")
     # Define a dummy class to allow loading, but it won't work
     class ChatOpenRouter: pass

logger = logging.getLogger(__name__)

# --- VLM Configuration (Read by Detector's __init__ via ChatOpenRouter) ---
VLM_API_MODEL = os.getenv("VLM_API_MODEL", "openai/gpt-4o") # Read desired VLM model from .env

# --- VLM Prompt Template ---
VLM_PROMPT_TEMPLATE = """
Analyze the provided screenshot of a webpage. Your task is to identify all significant interactive elements visible on the screen. Interactive elements include: buttons, links (<a> tags), text input fields (<input type='text'>, <input type='search'>, etc.), password fields (<input type='password'>), text areas (<textarea>), select dropdowns (<select>), checkboxes (<input type='checkbox'>), radio buttons (<input type='radio'>), and any other clearly clickable areas (e.g., some <div>s or <span>s styled as buttons).

For EACH identified interactive element, provide the following information:
1.  `type`: A string indicating the type of the element (e.g., "button", "link", "input-text", "input-password", "textarea", "select", "checkbox", "radio", "clickable-area").
2.  `description`: A brief string describing the element, preferably using its visible text label or aria-label. If no text is available, describe its appearance or function (e.g., "Search icon button", "Dropdown menu arrow").
3.  `box_percent`: A list of four floating-point numbers `[xmin, ymin, xmax, ymax]`, representing the bounding box coordinates as percentages of the image's total width and height. Each value must be between 0.0 and 1.0. `xmin` is the left edge, `ymin` is the top edge, `xmax` is the right edge, and `ymax` is the bottom edge, all relative to the image dimensions.

Your response MUST be a single, valid JSON object. This object must contain exactly one key: `"detected_elements"`. The value associated with this key must be a list (`[]`) where each item in the list is an object containing the `type`, `description`, and `box_percent` for one detected element.

Example of the required EXACT output format:
```json
{{
  "detected_elements": [
    {{
      "type": "link",
      "description": "new",
      "box_percent": [0.152, 0.015, 0.180, 0.035]
    }},
    {{
      "type": "input-text",
      "description": "Search query input",
      "box_percent": [0.3, 0.1, 0.7, 0.15]
    }},
    {{
       "type": "button",
       "description": "Login",
       "box_percent": [0.85, 0.1, 0.95, 0.15]
    }}
  ]
}}
```

Output ONLY the JSON object within a ```json ... ``` block. Do not include any other explanatory text before or after the JSON block. Be precise with the bounding box percentages.
"""

class Detector:
    """
    Uses ChatOpenRouter (LangChain) to call a VLM for visual element detection.
    Initializes its own VLM client based on environment variables.
    """
    def __init__(self):
        """
        Initialize the detector by creating a ChatOpenRouter instance.
        Reads OPENROUTER_API_KEY and VLM_API_MODEL from environment variables.
        """
        self.vlm_client: Optional[ChatOpenRouter] = None
        self.enabled = False
        openrouter_key = os.getenv("OPENROUTER_API_KEY")

        if not openrouter_key:
            logger.error("OPENROUTER_API_KEY environment variable not set. Vision detector disabled.")
        elif not VLM_API_MODEL:
            logger.error("VLM_API_MODEL environment variable not set (e.g., 'alibaba/qwen-vl-max'). Vision detector disabled.")
        else:
            try:
                # Instantiate ChatOpenRouter using the VLM model from env var
                # It reads OPENROUTER_API_KEY internally via its Field definition
                self.vlm_client = ChatOpenRouter(
                    model_name=VLM_API_MODEL,
                    temperature=0.05,
                    max_tokens=2048,
                    # Note: API key is handled by ChatOpenRouter's default_factory
                )
                self.enabled = True
                logger.info(f"ChatOpenRouter VLM Detector initialized. Enabled: {self.enabled}. Model: {VLM_API_MODEL}")
            except Exception as e:
                 logger.error(f"Failed to initialize ChatOpenRouter in Detector: {e}", exc_info=True)
                 self.enabled = False # Ensure disabled if init fails


    @observe(name="detector.detect_from_image", ignore_input=True)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception), # Retry on LangChain exceptions too
        reraise=True,
    )
    async def detect_from_image(self, image_b64: str, detect_sheets: bool = False) -> List[InteractiveElement]:
        """
        Sends a base64 encoded image to the configured VLM via ChatOpenRouter.

        Args:
            image_b64: Base64 encoded image.
            detect_sheets: Currently ignored.

        Returns:
            List of InteractiveElement objects parsed from the VLM response.
        """
        if not self.enabled or not self.vlm_client or not image_b64:
            logger.warning("Detector disabled, VLM client not initialized, or image missing. Skipping detection.")
            return []

        logger.info(f"Calling VLM {VLM_API_MODEL} via ChatOpenRouter...")
        image_url_data = f"data:image/png;base64,{image_b64}"

        prompt_text = VLM_PROMPT_TEMPLATE
        # Optional: Modify prompt if detect_sheets is True

        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": image_url_data}}
                ]
            )
        ]

        try:
            # Use with_structured_output targeting the VLMJsonOutput schema
            # Ensure VLMJsonOutput is correctly defined/imported
            structured_llm_vlm = self.vlm_client.with_structured_output(VLMJsonOutput)
            vlm_output: Optional[VLMJsonOutput] = await structured_llm_vlm.ainvoke(messages)

            if vlm_output and isinstance(vlm_output, VLMJsonOutput):
                detection_result = vlm_output.detected_elements
                if not isinstance(detection_result, list): # Add validation
                    logger.error(f"Parsed VLM output 'detected_elements' is not a list: {detection_result}")
                    return []
                logger.info(f"Successfully received and parsed VLM JSON with {len(detection_result)} potential elements.")
                elements = self._parse_vlm_detections(detection_result)
                logger.info(f"Created {len(elements)} InteractiveElement objects from VLM detections.")
                return elements
            else:
                logger.error("VLM response failed validation against VLMJsonOutput schema or returned None.")
                return []

        except Exception as e:
            logger.error(f"Error calling VLM or processing structured output: {e}", exc_info=True)
            raise # Re-raise to trigger tenacity retry or fail the node

    # Inside class Detector in detector.py

    def _parse_vlm_detections(self, detections: List[Dict[str, Any]]) -> List[InteractiveElement]:
        """
        Parses VLM JSON output into InteractiveElement objects, populating
        top-level VLM fields instead of nested attributes.
        NOTE: Still needs image dimensions for pixel coordinates.
        """
        elements = []
        if not isinstance(detections, list):
            logger.warning(f"VLM detections expected to be a list, but got {type(detections)}")
            return []

        # Placeholder dimensions
        img_w, img_h = 100, 100

        for i, pred in enumerate(detections):
            if not isinstance(pred, dict):
                logger.warning(f"Skipping detection item as it's not a dict: {pred}")
                continue

            try:
                box_percent = pred.get('box_percent')
                vlm_description = pred.get('description', '') # Get VLM description
                vlm_type = pred.get('type', 'unknown') # Get VLM suggested type

                if not isinstance(box_percent, list) or len(box_percent) != 4 or not all(isinstance(n, (int, float)) for n in box_percent):
                     logger.warning(f"Skipping detection due to invalid box_percent format: {box_percent}")
                     continue
                box_percent_clamped = [max(0.0, min(1.0, p)) for p in box_percent]

                # Calculate placeholder pixel values
                xmin = round(box_percent_clamped[0] * img_w); ymin = round(box_percent_clamped[1] * img_h)
                xmax = round(box_percent_clamped[2] * img_w); ymax = round(box_percent_clamped[3] * img_h)
                if xmax < xmin: xmax = xmin;
                if ymax < ymin: ymax = ymin
                width = xmax - xmin; height = ymax - ymin

                index_id = f"vlm-{i}"
                # Use VLM type as tag_name, or maybe default to 'div'?
                tag_name = vlm_type # Or 'div'

                if 'InteractiveElement' not in globals() and 'InteractiveElement' not in locals(): continue

                element = InteractiveElement(
                    index=i,
                    browser_agent_id=index_id,
                    tag_name=tag_name,
                    # Basic attributes remain empty for pure VLM detections for now
                    attributes={},
                    weight=0.8, # VLM weight
                    # Use calculated placeholder pixel values
                    viewport={"x": xmin, "y": ymin, "width": width, "height": height},
                    page={"x": xmin, "y": ymin, "width": width, "height": height},
                    center={"x": xmin + width//2, "y": ymin + height//2},
                    rect={"left": xmin, "top": ymin, "right": xmax, "bottom": ymax, "width": width, "height": height},
                    z_index=0,
                    # --- Populate NEW VLM specific fields ---
                    vlm_description=vlm_description,
                    vlm_type=vlm_type,
                    box_percent=box_percent_clamped
                    # --- End VLM specific fields ---
                )
                elements.append(element)

            except Exception as e:
                logger.warning(f"Error parsing individual VLM detection: {e} - Data: {pred}", exc_info=False)

        return elements
    # def _parse_vlm_detections(self, detections: List[Dict[str, Any]]) -> List[InteractiveElement]:
    #     """
    #     Parses the list of detections from the VLM JSON output into
    #     InteractiveElement objects.
    #     NOTE: Needs image dimensions passed in to calculate meaningful pixel coordinates.
    #           Currently uses placeholder coordinates.
    #     """
    #     elements = []
    #     if not isinstance(detections, list):
    #         logger.warning(f"VLM detections expected to be a list, but got {type(detections)}")
    #         return []

    #     # Placeholder dimensions - THIS IS STILL A PROBLEM TO SOLVE LATER
    #     img_w, img_h = 100, 100

    #     for i, pred in enumerate(detections):
    #         if not isinstance(pred, dict):
    #             logger.warning(f"Skipping detection item as it's not a dict: {pred}")
    #             continue

    #         try:
    #             box_percent = pred.get('box_percent')
    #             description = pred.get('description', '')
    #             element_type = pred.get('type', 'unknown')

    #             if not isinstance(box_percent, list) or len(box_percent) != 4 or not all(isinstance(n, (int, float)) for n in box_percent):
    #                  logger.warning(f"Skipping detection due to invalid box_percent format: {box_percent}")
    #                  continue
    #             box_percent_clamped = [max(0.0, min(1.0, p)) for p in box_percent]

    #             # Calculate placeholder pixel values
    #             xmin = round(box_percent_clamped[0] * img_w); ymin = round(box_percent_clamped[1] * img_h)
    #             xmax = round(box_percent_clamped[2] * img_w); ymax = round(box_percent_clamped[3] * img_h)
    #             if xmax < xmin: xmax = xmin;
    #             if ymax < ymin: ymax = ymin
    #             width = xmax - xmin; height = ymax - ymin

    #             index_id = f"vlm-{i}"; tag_name = element_type

    #             if 'InteractiveElement' not in globals() and 'InteractiveElement' not in locals():
    #                  logger.error("InteractiveElement class definition is missing. Cannot create elements.")
    #                  continue

    #             element = InteractiveElement(
    #                 index=i, browser_agent_id=index_id, tag_name=tag_name, text=description,
    #                 attributes={'description': description, 'vlm_type': element_type, 'box_percent': box_percent_clamped}, weight=0.8,
    #                 viewport={"x": xmin, "y": ymin, "width": width, "height": height}, page={"x": xmin, "y": ymin, "width": width, "height": height},
    #                 center={"x": xmin + width//2, "y": ymin + height//2}, input_type=element_type if 'input' in element_type else None,
    #                 rect={"left": xmin, "top": ymin, "right": xmax, "bottom": ymax, "width": width, "height": height}, z_index=0)
    #             elements.append(element)

    #         except Exception as e:
    #             logger.warning(f"Error parsing individual VLM detection: {e} - Data: {pred}", exc_info=False)

    #     return elements