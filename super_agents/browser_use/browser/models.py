# super_agents/browser_use/browser/models.py
from typing import List, Dict, Optional, Any

# --- Force Pydantic V2 Import ---
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel
# --- End Pydantic V2 Import ---

# --- BrowserError Exception ---
class BrowserError(Exception): pass
class URLNotAllowedError(BrowserError): pass

# --- Data Models ---
class TabInfo(BaseModel):
    page_id: int
    url: str
    title: str

class Coordinates(BaseModel):
    x: int
    y: int
    width: Optional[int] = Field(default=None)
    height: Optional[int] = Field(default=None)

class Viewport(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra='ignore')
    width: int = Field(default=1200)
    height: int = Field(default=900)
    scroll_x: int = Field(default=0)
    scroll_y: int = Field(default=0)
    device_pixel_ratio: float = Field(default=1.0)
    scroll_distance_above_viewport: Optional[int] = Field(default=0)
    scroll_distance_below_viewport: Optional[int] = Field(default=0)

class InteractiveElement(BaseModel):
    """Represents an interactive element, combining DOM/AX/VLM info."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra='ignore'
    )

    # Common fields
    index: int
    browser_agent_id: str # Unique ID (pw-X or vlm-Y)
    tag_name: str
    text: Optional[str] = Field(default=None)
    attributes: Dict[str, str] = Field(default_factory=dict) # Keep basic DOM attributes as string dict?
    weight: float = Field(default=1.0)
    viewport: Optional[Coordinates] = Field(default=None) # Make optional as VLM might not provide perfectly
    page: Optional[Coordinates] = Field(default=None)     # Make optional
    center: Optional[Coordinates] = Field(default=None)   # Make optional
    input_type: Optional[str] = Field(default=None)
    rect: Optional[Dict[str, int]] = Field(default=None) # Make optional
    z_index: int = Field(default=0)

    # --- Fields specifically from VLM (added as top-level optional) ---
    vlm_description: Optional[str] = Field(default=None, description="Description provided by VLM")
    vlm_type: Optional[str] = Field(default=None, description="Element type suggested by VLM")
    box_percent: Optional[List[float]] = Field(default=None, description="Bounding box [xmin, ymin, xmax, ymax] as percentages from VLM")
    # --- End VLM specific fields ---

class InteractiveElementsData(BaseModel):
    model_config = ConfigDict(extra='ignore')
    viewport: Viewport
    elements: List[InteractiveElement] = Field(default_factory=list)

class BrowserState(BaseModel):
    model_config = ConfigDict(extra='ignore')
    url: str
    tabs: List[TabInfo] = Field(default_factory=list)
    viewport: Optional[Viewport] = Field(default=None)
    screenshot_with_highlights: Optional[str] = Field(default=None)
    screenshot: Optional[str] = Field(default=None)
    # Use str key (browser_agent_id)
    interactive_elements: Dict[str, InteractiveElement] = Field(default_factory=dict)