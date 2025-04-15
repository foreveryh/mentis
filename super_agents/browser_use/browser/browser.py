"""
Streamlined Playwright browser implementation.
"""

import asyncio
import json
import logging
import functools
import os
from dataclasses import dataclass, field
from importlib import resources
from typing import Any, Optional, TypedDict, List

# 导入自定义的 observe 装饰器
from .observe_helper import observe

from playwright.async_api import (
	Browser as PlaywrightBrowser,
)
from playwright.async_api import (
	BrowserContext as PlaywrightBrowserContext,
)
from playwright.async_api import (
	Page,
	Playwright,
	StorageState,
	async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from tenacity import (
	retry,
	retry_if_exception_type,
	stop_after_attempt,
	wait_exponential,
)

# 修正为本地导入路径
from .detector import Detector
from .models import (
	BrowserError,
	BrowserState,
	InteractiveElementsData,
	TabInfo,
)
from .utils import (
	combine_and_filter_elements,
	put_highlight_elements_on_screenshot,
)

logger = logging.getLogger(__name__)

# 修正 JavaScript 文件读取路径，使用相对路径和 os 模块
# resources.read_text() 要求模块路径格式，对于本地文件，使用文件IO更合适
current_dir = os.path.dirname(os.path.abspath(__file__))
js_file_path = os.path.join(current_dir, 'findVisibleInteractiveElements.js')

with open(js_file_path, 'r', encoding='utf-8') as js_file:
    INTERACTIVE_ELEMENTS_JS_CODE = js_file.read()

# --- JS 脚本：用于简化页面结构并添加唯一 x-pw-id ---
SIMPLIFY_PAGE_SCRIPT = """
(() => {
    const MAX_ELEMENTS = 250;
    const MAX_TEXT_LENGTH = 200;
    const INTERACTIVE_TAGS = ['a', 'button', 'input', 'textarea', 'select', 'option', 'details', 'summary'];
    const EXCLUDED_TAGS = ['script', 'style', 'noscript', 'svg', 'link', 'meta', 'head', 'embed', 'object', 'path', 'canvas'];
    let elementCount = 0;
    let uniqueIdCounter = 0;
    function truncateText(text) {
        return text.length > MAX_TEXT_LENGTH ? text.substring(0, MAX_TEXT_LENGTH) + '...' : text;
    }
    function getElementData(el) {
        const data = {
            tag: el.tagName.toLowerCase(),
            attributes: {},
            text: '',
            children: [],
            pw_id: `pw-${uniqueIdCounter++}`
        };
        el.setAttribute('x-pw-id', data.pw_id);
        const attrsToKeep = ['id', 'class', 'role', 'aria-label', 'aria-labelledby', 'aria-describedby', 'aria-hidden', 'aria-invalid', 'aria-required', 'placeholder', 'title', 'alt', 'for', 'name', 'type', 'href', 'value', 'selected', 'checked', 'disabled', 'readonly', 'open'];
        for (const attr of attrsToKeep) {
            if (el.hasAttribute(attr)) {
                let value = el.getAttribute(attr);
                if (attr === 'class' && value) {
                    value = value.split(' ').filter(c => c.length > 0 && c.length < 20).slice(0, 5).join(' ');
                }
                if (value !== null && value !== '') {
                    data.attributes[attr] = truncateText(String(value));
                }
            }
        }
        if (el.tagName.toLowerCase() === 'input' && !data.attributes.value && el.value) {
            data.attributes.value = truncateText(el.value);
        } else if (el.tagName.toLowerCase() === 'textarea' && !data.attributes.value && el.value) {
            data.attributes.value = truncateText(el.value);
        }
        const directText = Array.from(el.childNodes)
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent.trim())
            .join(' ');
        if (directText) {
            data.text = truncateText(directText);
        }
        return data;
    }
    function simplifyNode(node) {
        if (elementCount >= MAX_ELEMENTS) return null;
        if (node.nodeType !== Node.ELEMENT_NODE || EXCLUDED_TAGS.includes(node.tagName.toLowerCase())) {
            return null;
        }
        elementCount++;
        const elementData = getElementData(node);
        if (node.hasChildNodes()) {
            Array.from(node.childNodes).forEach(child => {
                const simplifiedChild = simplifyNode(child);
                if (simplifiedChild) {
                    elementData.children.push(simplifiedChild);
                }
            });
        }
        if (elementData.children.length === 0 && !elementData.text && !INTERACTIVE_TAGS.includes(elementData.tag) && Object.keys(elementData.attributes).length <= 1 ) {
            return null;
        }
        return elementData;
    }
    const simplifiedBody = simplifyNode(document.body);
    function convertToPseudoHTML(node) {
        if (!node) return '';
        let attrs = `x-pw-id="${node.pw_id}"`;
        for (const [key, value] of Object.entries(node.attributes)) {
            attrs += ` ${key}="${String(value).replace(/"/g, '&quot;')}"`;
        }
        let childrenHTML = node.children.map(convertToPseudoHTML).join('');
        let textContent = node.text ? node.text.replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
        if (['input', 'img', 'br', 'hr'].includes(node.tag)) {
            return `<${node.tag} ${attrs}/>`;
        } else {
            return `<${node.tag} ${attrs}>${textContent}${childrenHTML}</${node.tag}>`;
        }
    }
    return convertToPseudoHTML(simplifiedBody);
})()
"""

class ViewportSize(TypedDict):
	width: int
	height: int

@dataclass
class BrowserConfig:
	"""
	Simplified configuration for the Browser.
	
	Parameters:
		cdp_url: Optional[str] = None
			Connect to a browser instance via CDP
		
		viewport_size: ViewportSize = {"width": 1024, "height": 768}
			Default browser window size
			
		storage_state: Optional[StorageState] = None
			Storage state to set
			
		cv_model_endpoint: Optional[str] = None
			SageMaker endpoint for CV model, set to None to disable CV detection

		sheets_model_endpoint: Optional[str] = None
			SageMaker endpoint for sheets model, set to None to disable sheets detection

	"""
	cdp_url: Optional[str] = None
	viewport_size: ViewportSize = field(default_factory=lambda: {"width": 1200, "height": 900})
	storage_state: Optional[StorageState] = None
	cv_model_endpoint: Optional[str] = None
	sheets_model_endpoint: Optional[str] = None

class Browser:
	"""
	Unified Browser responsible for interacting with the browser via Playwright.
	"""

	def __init__(self, config: BrowserConfig = BrowserConfig(), close_context: bool = True):
		logger.debug('Initializing browser')
		self.config = config
		self.close_context = close_context
		# Playwright-related attributes
		self.playwright: Optional[Playwright] = None
		self.playwright_browser: Optional[PlaywrightBrowser] = None
		self.context: Optional[PlaywrightBrowserContext] = None
		
		# Page and state management
		self.current_page: Optional[Page] = None
		self._state: Optional[BrowserState] = None
		self._cdp_session = None
		
		# CV detection-related attributes
		self.detector: Optional[Detector] = None
		
		# Initialize state
		self._init_state()
		
		# Set up CV detection if endpoints are provided - 添加属性检查以防止 AttributeError
		if hasattr(self.config, 'cv_model_endpoint') and self.config.cv_model_endpoint:
			# 安全地获取 sheets_model_endpoint 属性，如果不存在则默认为 None
			sheets_endpoint = getattr(self.config, 'sheets_model_endpoint', None)
			self.setup_cv_detector(self.config.cv_model_endpoint, sheets_endpoint)

	async def __aenter__(self):
		"""Async context manager entry"""
		await self._init_browser()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Async context manager exit"""
		if self.close_context:
			await self.close()
			
	async def initialize(self):
		"""
		Initialize the browser instance.
		Public interface that calls the internal _init_browser method.
		"""
		logger.debug("Initializing browser instance")
		await self._init_browser()
		return self

	def _init_state(self, url: str = '') -> None:
		"""Initialize browser state"""
		self._state = BrowserState(
			url=url,
			screenshot_with_highlights=None,
			tabs=[],
			interactive_elements={},
		)

	async def _init_browser(self):
		"""Initialize the browser and context"""
		logger.debug('Initializing browser context')
		# Start playwright if needed
		if self.playwright is None:
			self.playwright = await async_playwright().start()
		
		# Initialize browser if needed
		if self.playwright_browser is None:
			if self.config.cdp_url:
				logger.info(f'Connecting to remote browser via CDP {self.config.cdp_url}')
				attempts = 0
				while True:
					try:
						self.playwright_browser = await self.playwright.chromium.connect_over_cdp(
							self.config.cdp_url,
							timeout=2500,
						)
						break
					except Exception as e:
						logger.error(f'Failed to connect to remote browser via CDP {self.config.cdp_url}: {e}. Retrying...')
						await asyncio.sleep(1)
						attempts += 1
						if attempts > 3:
							raise e
				logger.info(f'Connected to remote browser via CDP {self.config.cdp_url}')
			else:
				logger.info('Launching new browser instance')
				self.playwright_browser = await self.playwright.chromium.launch(
					headless=False,
					args=[
						'--no-sandbox',
						'--disable-blink-features=AutomationControlled',
						'--disable-web-security',
						'--disable-site-isolation-trials',
						'--disable-features=IsolateOrigins,site-per-process',
						f'--window-size={self.config.viewport_size["width"]},{self.config.viewport_size["height"]}',
					]
				)
		
		# Create context if needed
		if self.context is None:

			if len(self.playwright_browser.contexts) > 0:
				self.context = self.playwright_browser.contexts[0]
			else:
				self.context = await self.playwright_browser.new_context(
				viewport=self.config.viewport_size,
				user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
				java_script_enabled=True,
				bypass_csp=True,
				ignore_https_errors=True,
			)
			
			# Apply anti-detection scripts
			await self._apply_anti_detection_scripts()
			
		self.context.on('page', self._on_page_change)	

		# 添加安全检查，确保 storage_state 属性存在
		if hasattr(self.config, 'storage_state') and self.config.storage_state and 'cookies' in self.config.storage_state:
			await self.context.add_cookies(self.config.storage_state['cookies'])
		
		# Create page if needed
		if self.current_page is None:
			if len(self.context.pages) > 0:
				self.current_page = self.context.pages[-1]
			else:
				self.current_page = await self.context.new_page()
		
		return self
	
	async def _on_page_change(self, page: Page):
		"""Handle page change events"""
		logger.info(f'Current page changed to {page.url}')

		self._cdp_session = await self.context.new_cdp_session(page)
		self.current_page = page

	def setup_cv_detector(self, cv_endpoint_name: Optional[str] = None, sheets_endpoint_name: Optional[str] = None) -> None:
		"""
		Set up the CV detector with the browser
		
		Args:
			cv_endpoint_name: Optional SageMaker endpoint name for CV model. If None, uses default.
			sheets_endpoint_name: Optional SageMaker endpoint name for sheets model. If None, uses default.
		"""
		if cv_endpoint_name is None and self.config.cv_model_endpoint is None:
			logger.debug("No CV model endpoint provided, skipping CV detector setup")
			return
			
		# Use provided endpoint or fall back to config
		cv_endpoint = cv_endpoint_name or self.config.cv_model_endpoint
		sheets_endpoint = sheets_endpoint_name or self.config.sheets_model_endpoint

		self.detector = Detector(cv_endpoint_name=cv_endpoint, sheets_endpoint_name=sheets_endpoint)
		
		return self.detector

	async def _apply_anti_detection_scripts(self):
		"""Apply scripts to avoid detection as automation"""
		await self.context.add_init_script(
			"""
			// Webdriver property
			Object.defineProperty(navigator, 'webdriver', {
				get: () => undefined
			});

			// Languages
			Object.defineProperty(navigator, 'languages', {
				get: () => ['en-US']
			});

			// Plugins
			Object.defineProperty(navigator, 'plugins', {
				get: () => [1, 2, 3, 4, 5]
			});

			// Chrome runtime
			window.chrome = { runtime: {} };

			// Permissions
			const originalQuery = window.navigator.permissions.query;
			window.navigator.permissions.query = (parameters) => (
				parameters.name === 'notifications' ?
					Promise.resolve({ state: Notification.permission }) :
					originalQuery(parameters)
			);
			(function () {
				const originalAttachShadow = Element.prototype.attachShadow;
				Element.prototype.attachShadow = function attachShadow(options) {
					return originalAttachShadow.call(this, { ...options, mode: "open" });
				};
			})();
			"""
		)
	
	async def close(self):
		"""Close the browser instance and cleanup resources"""
		logger.debug('Closing browser')
		
		try:
			
			# Close CDP session if exists
			self._cdp_session = None
			
			# Close context
			if self.context:
				try:
					await self.context.close()
				except Exception as e:
					logger.debug(f'Failed to close context: {e}')
				self.context = None
			
			# Close browser
			if self.playwright_browser:
				try:
					await self.playwright_browser.close()
				except Exception as e:
					logger.debug(f'Failed to close browser: {e}')
				self.playwright_browser = None
			
			# Stop playwright
			if self.playwright:
				await self.playwright.stop()
				self.playwright = None
		except Exception as e:
			logger.error(f'Error during browser cleanup: {e}')
		finally:
			self.context = None
			self.current_page = None
			self._state = None
			self.playwright_browser = None
			self.playwright = None
	
	async def navigate_to(self, url: str):
		"""Navigate to a URL"""
		page = await self.get_current_page()
		await page.goto(url, wait_until='domcontentloaded')

	async def refresh_page(self):
		"""Refresh the current page"""
		page = await self.get_current_page()
		await page.reload()
		await page.wait_for_load_state()

	async def go_forward(self):
		"""Navigate forward in history"""
		page = await self.get_current_page()
			
		try:
			await page.go_forward(timeout=10, wait_until='domcontentloaded')
		except Exception as e:
			logger.debug(f'During go_forward: {e}')


	
	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all tabs"""

		tabs_info = []
		for page_id, page in enumerate(self.context.pages):
			tab_info = TabInfo(page_id=page_id, url=page.url, title=await page.title())
			tabs_info.append(tab_info)

		return tabs_info

	async def switch_to_tab(self, page_id: int) -> None:
		"""Switch to a specific tab by its page_id"""
		if self.context is None:
			await self._init_browser()

		pages = self.context.pages
		if page_id >= len(pages):
			raise BrowserError(f'No tab found with page_id: {page_id}')

		page = pages[page_id]
		self.current_page = page

		await page.bring_to_front()
		await page.wait_for_load_state()

	async def create_new_tab(self, url: str | None = None) -> None:
		"""Create a new tab and optionally navigate to a URL"""
		if self.context is None:
			await self._init_browser()

		new_page = await self.context.new_page()
		self.current_page = new_page

		await new_page.wait_for_load_state()

		if url:
			await new_page.goto(url, wait_until='domcontentloaded')

	async def close_current_tab(self):
		"""Close the current tab"""
		if self.current_page is None:
			return
			
		await self.current_page.close()

		# Switch to the first available tab if any exist
		if self.context and self.context.pages:
			await self.switch_to_tab(0)
	
	async def get_current_page(self) -> Page:
		"""Get the current page"""
		if self.current_page is None:
			await self._init_browser()
		return self.current_page
	
	def get_state(self) -> BrowserState:
		"""Get the current browser state"""
		return self._state

	@observe(name='browser.update_state', ignore_output=True)
	async def update_state(self) -> BrowserState:
		"""Update the browser state with current page information and return it"""
		self._state = await self._update_state()
		return self._state

	@observe(name='browser._update_state', ignore_output=True)
	async def _update_state(self) -> BrowserState:
		"""Update and return state."""
		@retry(
			stop=stop_after_attempt(3),
			wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
			retry=retry_if_exception_type((Exception)),
			reraise=True
		)
		async def get_stable_state():
			if self.current_page is None:
				await self._init_browser()
			url = self.current_page.url

			detect_sheets = 'docs.google.com/spreadsheets/d' in url

			screenshot_b64 = await self.fast_screenshot()
			
			# Use CV detection if available, otherwise use standard browser detection
			if self.detector is not None:
				interactive_elements_data = await self.get_interactive_elements_with_cv(screenshot_b64, detect_sheets)
			else:
				interactive_elements_data = await self.get_interactive_elements_data()
			
			interactive_elements = {element.index: element for element in interactive_elements_data.elements}
			
			# Create highlighted version of the screenshot
			screenshot_with_highlights = put_highlight_elements_on_screenshot(
				interactive_elements, 
				screenshot_b64
			)
			
			tabs = await self.get_tabs_info()

			return BrowserState(
				url=url,
				tabs=tabs,
				screenshot_with_highlights=screenshot_with_highlights,
				screenshot=screenshot_b64,
				viewport=interactive_elements_data.viewport,
				interactive_elements=interactive_elements,
			)

		try:
			self._state = await get_stable_state()
			return self._state
		except Exception as e:
			logger.error(f'Failed to update state after multiple attempts: {str(e)}')
			# Return last known good state if available
			if hasattr(self, '_state'):
				return self._state
			raise
	
	@observe(name='browser.get_interactive_elements')
	async def get_interactive_elements_data(self) -> InteractiveElementsData:
		"""Get all interactive elements on the page"""
		page = await self.get_current_page()	
		result = await page.evaluate(INTERACTIVE_ELEMENTS_JS_CODE)
		interactive_elements_data = InteractiveElementsData(**result)

		return interactive_elements_data
	
	@observe(name='browser.get_interactive_elements_with_cv')
	async def get_interactive_elements_with_cv(self, screenshot_b64: Optional[str] = None, detect_sheets: bool = False) -> InteractiveElementsData:
		"""
		Get interactive elements using combined browser and CV detection.
		
		Args:
			screenshot_b64: Optional base64 encoded screenshot. If None, a new screenshot will be taken.
			detect_sheets: Whether to detect sheets elements
		Returns:
			Combined detection results
		"""
		if self.detector is None:
			logger.warning("CV detector not set up. Falling back to browser-only detection.")
			return await self.get_interactive_elements_data()
		
		# Take screenshot if not provided
		if screenshot_b64 is None:
			screenshot_b64 = await self.fast_screenshot()
		
		# Get browser-based detections
		browser_elements_data, cv_elements = await asyncio.gather(
			self.get_interactive_elements_data(),
			self.detector.detect_from_image(screenshot_b64, detect_sheets)
		)
		
		# Combine and filter detections
		combined_elements = combine_and_filter_elements(
			browser_elements_data.elements, 
			cv_elements,
		)
		
		# Create new InteractiveElementsData with combined elements
		return InteractiveElementsData(
			viewport=browser_elements_data.viewport,
			elements=combined_elements
		)

	async def get_cdp_session(self):
		"""Get or create a CDP session for the current page"""
		
		# Create a new session if we don't have one or the page has changed
		if (self._cdp_session is None or 
			not hasattr(self._cdp_session, '_page') or 
			self._cdp_session._page != self.current_page):
			self._cdp_session = await self.context.new_cdp_session(self.current_page)
			# Store reference to the page this session belongs to
			self._cdp_session._page = self.current_page
			
		return self._cdp_session

	@observe(name='browser.take_screenshot', ignore_output=True)
	async def fast_screenshot(self) -> str:
		"""
		Returns a base64 encoded screenshot of the current page.
			
		Returns:
			Base64 encoded screenshot
		"""
		# Use cached CDP session instead of creating a new one each time
		cdp_session = await self.get_cdp_session()
		screenshot_params = {
			"format": "png",
			"fromSurface": False,
			"captureBeyondViewport": False
		}
		
		# Capture screenshot using CDP Session
		screenshot_data = await cdp_session.send("Page.captureScreenshot", screenshot_params)
		screenshot_b64 = screenshot_data["data"]
		
		return screenshot_b64

	async def get_cookies(self) -> list[dict[str, Any]]:
		"""Get cookies from the browser"""
		if self.context:
			cookies = await self.context.cookies()
			return cookies
		return []
	
	async def get_storage_state(self) -> dict[str, Any]:
		"""Get local storage from the browser"""

		if self.context:
			cookies = await self.context.cookies()

			return {
				'cookies': cookies,
			}
		return {}

	async def get_content(self, max_length: int = 8000) -> str: # Increased max_length slightly
		"""
		Gets a comprehensive representation of the current page state, including
		simplified DOM, accessibility tree, and visual element detections (if CV is enabled).

		Args:
			max_length: Approximate maximum character length for the combined output.

		Returns:
			A string containing the page URL, simplified DOM, accessibility tree,
			and visual elements, truncated if necessary.
		"""
		# Ensure browser is initialized (using internal method if __aenter__ wasn't used)
		# Using get_current_page which calls _init_browser if needed
		page = await self.get_current_page()
		logger.info("Getting comprehensive page content with vision...")
		combined_content = ""
		error_messages = []
		current_url = "Unknown"
		screenshot_b64 = None # Initialize screenshot variable

		try:
			# 1. Get Current URL
			current_url = page.url
			combined_content += f"# Page URL:\n{current_url}\n\n"

			# --- Screenshot needed for Vision ---
			try:
				screenshot_b64 = await self.fast_screenshot()
				logger.debug(f"Screenshot captured (size: {len(screenshot_b64) if screenshot_b64 else 0})")
			except Exception as ss_err:
				logger.error(f"Error taking screenshot: {ss_err}", exc_info=False)
				error_messages.append(f"Screenshot Error: {ss_err}")
				combined_content += "# Screenshot:\n (Error taking screenshot)\n\n"
			# --- End Screenshot ---


			# 2. Get Simplified DOM via JavaScript
			try:
				simplified_dom_pseudo_html = await page.evaluate(SIMPLIFY_PAGE_SCRIPT)
				if simplified_dom_pseudo_html:
					combined_content += f"# Simplified DOM (Pseudo-HTML with x-pw-id attributes):\n```html\n{simplified_dom_pseudo_html}\n```\n\n"
					logger.debug(f"Retrieved simplified DOM (length: {len(simplified_dom_pseudo_html)})")
				else:
					logger.warning("JavaScript simplification returned empty content.")
					combined_content += "# Simplified DOM:\n (Script returned empty or null)\n\n"
			except PlaywrightError as js_err:
				logger.error(f"Playwright Error executing JS for DOM simplification: {js_err}", exc_info=False)
				error_messages.append(f"JS Simplification Error: {js_err}")
				combined_content += f"# Simplified DOM:\n (Error: {js_err})\n\n"
			except Exception as js_err_other:
					logger.error(f"Unexpected Error executing JS: {js_err_other}", exc_info=True)
					error_messages.append(f"JS Simplification Error: {js_err_other}")
					combined_content += f"# Simplified DOM:\n (Unexpected Error: {js_err_other})\n\n"


			# 3. Get Accessibility Tree
			try:
				# --- CHANGE HERE: Remove the root argument ---
				ax_tree = await page.accessibility.snapshot(interesting_only=False) # <--- REMOVED root=...
				# --- END CHANGE ---

				if ax_tree:
					try:
						# Compact JSON might be too dense, maybe pretty print but limit depth?
						# For now, compact:
						ax_tree_str = json.dumps(ax_tree, indent=None, separators=(',', ':')) # Compact JSON
						# Limit AX tree length separately if needed
						ax_max_len = 2000
						if len(ax_tree_str) > ax_max_len:
								ax_tree_str = ax_tree_str[:ax_max_len] + "...(AX Tree truncated)"
						combined_content += f"# Accessibility Tree (JSON, Partial):\n```json\n{ax_tree_str}\n```\n\n"
						logger.debug(f"Retrieved accessibility tree (JSON length: {len(ax_tree_str)})")
					except TypeError as json_err:
							logger.error(f"Error serializing accessibility tree to JSON: {json_err}")
							error_messages.append(f"AX Tree JSON Error: {json_err}")
							combined_content += "# Accessibility Tree:\n (Error serializing to JSON)\n\n"
				else:
						logger.warning("Accessibility tree snapshot returned None or empty.")
						combined_content += "# Accessibility Tree:\n (Snapshot was empty)\n\n"
			# Keep the existing error handling blocks
			except PlaywrightError as ax_err:
				logger.error(f"Playwright Error getting accessibility tree: {ax_err}", exc_info=False)
				error_messages.append(f"Accessibility Tree Error: {ax_err}")
				combined_content += f"# Accessibility Tree:\n (Error: {ax_err})\n\n"
			except Exception as ax_err_other:
					logger.error(f"Unexpected Error getting AX tree: {ax_err_other}", exc_info=True)
					error_messages.append(f"AX Tree Error: {ax_err_other}")
					combined_content += f"# Accessibility Tree:\n (Unexpected Error: {ax_err_other})\n\n"


			# --- 4. Get Visual Elements via CV Detector (If enabled) ---
			visual_elements_str = ""
			if self.detector and screenshot_b64:
				logger.info("CV Detector is enabled, attempting visual detection...")
				try:
					# Decide if sheets detection is needed based on URL (example)
					detect_sheets = 'docs.google.com/spreadsheets/d' in current_url
					# Call the appropriate detection method
					visual_elements: List[InteractiveElement] = await self.detector.detect_from_image(
						image_b64=screenshot_b64,
						detect_sheets=detect_sheets
					)
					if visual_elements:
						# Format visual elements for the LLM prompt
						formatted_elements = []
						for el in visual_elements[:20]: # Limit number of CV elements shown
							# Use the browser_agent_id assigned by detector (cv-X or class_name)
							el_id = el.browser_agent_id
							el_box = el.rect # Use the 'rect' field which has left,top,right,bottom
							# Construct a summary string for each element
							formatted_elements.append(
								f"- ID: {el_id}, Box: [L:{el_box['left']}, T:{el_box['top']}, R:{el_box['right']}, B:{el_box['bottom']}] (Tag: {el.tag_name})"
							)
						visual_elements_str = "\n".join(formatted_elements)
						combined_content += f"# Visual Elements (Detected via CV, Max 20):\n{visual_elements_str}\n\n"
						logger.info(f"Added {len(formatted_elements)} visual elements to content.")
					else:
						combined_content += "# Visual Elements:\n (None detected or error)\n\n"
						logger.info("No visual elements detected by CV.")
				except Exception as cv_err:
					logger.error(f"Error during CV detection: {cv_err}", exc_info=True)
					error_messages.append(f"CV Detection Error: {cv_err}")
					combined_content += f"# Visual Elements:\n (Error: {cv_err})\n\n"
			else:
				logger.info("CV Detector not configured or screenshot missing, skipping visual detection.")
				combined_content += "# Visual Elements:\n (CV detection not enabled/run)\n\n"
			# --- End Visual Elements ---


			# 5. Final Truncation (Applied at the very end)
			if len(combined_content) > max_length:
				logger.warning(f"Combined content length ({len(combined_content)}) exceeds limit ({max_length}). Truncating.")
				truncated_len = max_length - 300 # Reserve more space for truncation msg and errors
				if truncated_len < 0: truncated_len = max_length // 2
				combined_content = combined_content[:truncated_len] + \
									"\n\n... (Content truncated due to length limit)"


			# Append errors at the end
			if error_messages:
				# 使用简单的字符串拼接来构建错误信息部分，避免 f-string 语法问题
				error_prefix = "\n\n# Content Retrieval Errors:\n- "
				error_joiner = "\n- "
					# 使用 map(str, ...) 确保列表中的所有项都是字符串
				error_section = error_prefix + error_joiner.join(map(str, error_messages))

				# 附加错误信息，同时考虑截断
				if len(combined_content) + len(error_section) > max_length:
				# 计算剩余可用空间，确保不为负
					available_space = max_length - len(error_section) - 10 # 为 "..." 和错误信息本身留出空间
					if available_space < 0: available_space = 0
					combined_content = combined_content[:available_space] + "\n...(truncated)..." + error_section # 在截断处加提示
				else:
					combined_content += error_section


			logger.info(f"Finished getting comprehensive content (final length: {len(combined_content)})")
			return combined_content

		except Exception as e:
			logger.error(f"General error in get_content: {e}", exc_info=True)
			return f"# Page URL:\n{current_url}\n\n# Error:\nFailed to retrieve page content: {e}"

	@observe(name='browser.click') # Optional: Add observation if desired
	async def click(self, selector: str):
		"""Finds an element by selector and clicks it."""
		page = await self.get_current_page() # Ensure we have the current page
		logger.info(f"Attempting to click element: '{selector}'")
		try:
			element = page.locator(selector).first
			# Wait for element to be visible and enabled before interacting
			await element.wait_for(state="visible", timeout=15000)
			await element.wait_for(state="enabled", timeout=10000)
			await element.scroll_into_view_if_needed(timeout=10000)
			# Use force=False (default) to ensure playwright checks hit target etc.
			await element.click(timeout=15000, delay=50) # Small delay can sometimes help
			logger.info(f"Successfully clicked element: '{selector}'")
			# Optional: Trigger state update after interaction? Or rely on graph loop?
			# await self._update_state() # Decide if immediate state update is needed
		except PlaywrightError as e:
			logger.error(f"Playwright Error clicking '{selector}': {e}")
			raise BrowserError(f"Click action failed: {e}") from e # Use BrowserError if defined
		except Exception as e:
			logger.error(f"Unexpected Error clicking '{selector}': {e}")
			raise BrowserError(f"Click action failed unexpectedly: {e}") from e

	@observe(name='browser.type') # Optional: Add observation
	async def type(self, selector: str, text: str):
		"""Finds an element by selector and types text into it."""
		page = await self.get_current_page()
		log_text = '***' if 'password' in selector.lower() or 'pass' in selector.lower() else text
		logger.info(f"Attempting to type into element: '{selector}', Text: '{log_text}'")
		try:
			element = page.locator(selector).first
			await element.wait_for(state="visible", timeout=15000)
			await element.wait_for(state="enabled", timeout=10000)
			await element.scroll_into_view_if_needed(timeout=10000)
			# Use fill for efficiency
			await element.fill(text, timeout=15000)
			logger.info(f"Successfully typed into element: '{selector}'")
			# Optional: Trigger state update?
			# await self._update_state()
		except PlaywrightError as e:
			logger.error(f"Playwright Error typing into '{selector}': {e}")
			raise BrowserError(f"Type action failed: {e}") from e
		except Exception as e:
			logger.error(f"Unexpected Error typing into '{selector}': {e}")
			raise BrowserError(f"Type action failed unexpectedly: {e}") from e

	@observe(name='browser.scroll') # Optional: Add observation
	async def scroll(self, direction: str):
		"""Scrolls the page window in the specified direction."""
		page = await self.get_current_page()
		logger.info(f"Scrolling page {direction}")
		try:
			scroll_amount = "window.innerHeight" if direction in ["down", "up"] else "window.innerWidth"
			scroll_sign = "-" if direction in ["up", "left"] else ""
			scroll_axis = "0" if direction in ["down", "up"] else scroll_amount
			scroll_ordinate = scroll_amount if direction in ["down", "up"] else "0"

			js_command = f"window.scrollBy({scroll_sign}{scroll_axis}, {scroll_sign}{scroll_ordinate})"
			await page.evaluate(js_command)
			await asyncio.sleep(0.3) # Short delay for potential content loading
			logger.info(f"Scrolled page {direction}")
			# Optional: Trigger state update?
			# await self._update_state()
		except PlaywrightError as e:
			logger.error(f"Playwright Error scrolling {direction}: {e}")
			raise BrowserError(f"Scroll action failed: {e}") from e
		except Exception as e:
				logger.error(f"Unexpected Error scrolling {direction}: {e}")
				raise BrowserError(f"Scroll action failed unexpectedly: {e}") from e

	# Simple wait function if needed
	async def wait(self, milliseconds: int):
		"""Pauses execution for a specified duration."""
		logger.info(f"Waiting for {milliseconds} ms")
		if milliseconds <= 0:
				return
		await asyncio.sleep(milliseconds / 1000.0)
		logger.info("Wait finished")