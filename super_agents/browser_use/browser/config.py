# super_agents/browser_use/browser/config.py
"""
Configuration for the browser tool.
"""
from typing import Dict, Optional, Union

class BrowserConfig:
    """
    Configuration for browser tool initialization.
    """
    def __init__(
        self,
        viewport_size: Dict[str, int] = None,
        headless: bool = True,
        cdp_url: Optional[str] = None,
        default_timeout: int = 30000  # 30 seconds default timeout
    ):
        """
        Initialize browser configuration.
        
        Args:
            viewport_size: Dictionary with 'width' and 'height' for browser viewport
            headless: Whether to run in headless mode
            cdp_url: Chrome DevTools Protocol URL for connecting to existing browser
            default_timeout: Default timeout for browser operations in milliseconds
        """
        self.viewport_size = viewport_size or {"width": 1280, "height": 720}
        self.headless = headless
        self.cdp_url = cdp_url
        self.default_timeout = default_timeout
