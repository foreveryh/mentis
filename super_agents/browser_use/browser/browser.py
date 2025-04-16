# super_agents/browser_use/browser/browser.py
"""
Streamlined Playwright browser implementation with integrated perception capabilities.
Includes DOM/AX Tree/Visual analysis and basic interaction methods.
"""

import asyncio
import json
import logging
import functools 
import base64
import os
from dataclasses import dataclass, field
# from importlib import resources # Not used
from typing import Any, Optional, TypedDict, List, Dict # Added List, Dict

# --- Local Imports (Ensure these files exist in the same directory) ---
try:
    from .observe_helper import observe
except ImportError:
    def observe(name, ignore_input=False, ignore_output=False):
        def decorator(func): return func
        return decorator
    logging.basicConfig(level=logging.WARNING) # Setup basic logging if needed
    logger_observe = logging.getLogger(__name__)
    logger_observe.warning("observe_helper not found, using dummy decorator.")

try:
    from .detector import Detector
    from .models import (
        BrowserError,
        BrowserState,
        InteractiveElementsData,
        TabInfo,
        InteractiveElement,
    )
    from .utils import (
        combine_and_filter_elements,
        put_highlight_elements_on_screenshot,
    )
except ImportError as e:
     logging.basicConfig(level=logging.ERROR)
     logger_import = logging.getLogger(__name__)
     logger_import.error(f"Failed to import local browser dependencies (detector, models, utils): {e}. Browser class may not function correctly.", exc_info=True)
     # Define dummy classes to allow file loading, but functionality will be broken
     class Detector: enabled=False
     class BrowserError(Exception): pass
     class BrowserState: pass
     class InteractiveElementsData: elements=[]; viewport={}
     class TabInfo: pass
     class InteractiveElement: pass
     def combine_and_filter_elements(a, b): return []
     def put_highlight_elements_on_screenshot(a, b): return None
# --- End Local Imports ---

# --- Playwright Imports ---
from playwright.async_api import (
    Browser as PlaywrightBrowser,
    BrowserContext as PlaywrightBrowserContext,
    Page,
    Playwright,
    StorageState,
    async_playwright,
    Error as PlaywrightError
)
# --- Tenacity Import ---
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)
# Ensure basic logging is configured if not done elsewhere
if not logger.hasHandlers():
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# --- Load JavaScript Files ---
INTERACTIVE_ELEMENTS_JS_CODE = ""
SIMPLIFY_PAGE_SCRIPT = ""
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # JS for DOM-based interactive elements used in get_interactive_elements_data
    js_file_path_interactive = os.path.join(current_dir, 'findVisibleInteractiveElements.js')
    with open(js_file_path_interactive, 'r', encoding='utf-8') as js_file:
        INTERACTIVE_ELEMENTS_JS_CODE = js_file.read()

    # JS for DOM simplification used in get_content
    # (Re-paste the script here for completeness)
    SIMPLIFY_PAGE_SCRIPT = """
    (() => {
        const MAX_ELEMENTS = 250; const MAX_TEXT_LENGTH = 200;
        const INTERACTIVE_TAGS = ['a', 'button', 'input', 'textarea', 'select', 'option', 'details', 'summary', 'label'];
        const EXCLUDED_TAGS = ['script', 'style', 'noscript', 'svg', 'link', 'meta', 'head', 'embed', 'object', 'path', 'canvas', 'iframe', 'video', 'audio'];
        let elementCount = 0; let uniqueIdCounter = 0;
        function isVisible(el) { if (!el || !el.checkVisibility) return false; return el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}); }
        function truncateText(text, maxLength = MAX_TEXT_LENGTH) { if (typeof text !== 'string') return text; return text.length > maxLength ? text.substring(0, maxLength) + '...' : text; }
        function getElementData(el) {
            const data = { tag: el.tagName.toLowerCase(), attributes: {}, text: '', children: [], pw_id: `pw-${uniqueIdCounter++}` };
            try { if (document.body.contains(el)) el.setAttribute('x-pw-id', data.pw_id); } catch(e){}
            const attrsToKeep = ['id', 'class', 'role', 'aria-label', 'aria-labelledby', 'aria-describedby', 'aria-hidden', 'aria-invalid', 'aria-required', 'placeholder', 'title', 'alt', 'for', 'name', 'type', 'href', 'value', 'selected', 'checked', 'disabled', 'readonly', 'open'];
            for (const attr of attrsToKeep) {
                if (el.hasAttribute(attr)) {
                    let value = el.getAttribute(attr);
                    if (attr === 'class' && value) value = value.split(' ').filter(c => c && c.length > 1 && c.length < 30 && !/^[0-9]+$/.test(c)).slice(0, 5).join(' ');
                    if (value !== null && value !== '') data.attributes[attr] = truncateText(String(value), 80);
                }
            }
            if (['button', 'a', 'label', 'summary'].includes(data.tag) && !data.attributes['aria-label'] && el.textContent) data.attributes['aria-label'] = truncateText(el.textContent.trim(), 80);
            try {
                if (el.tagName.toLowerCase() === 'input' && !data.attributes.value && el.value) data.attributes.value = truncateText(el.value);
                else if (el.tagName.toLowerCase() === 'textarea' && !data.attributes.value && el.value) data.attributes.value = truncateText(el.value);
                else if (el.tagName.toLowerCase() === 'select' && el.options && el.selectedIndex !== -1 && !data.attributes.value) data.attributes.value = truncateText(el.options[el.selectedIndex].text);
            } catch (e) {}
            try {
                const directText = Array.from(el.childNodes).filter(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0).map(node => node.textContent.trim()).join(' ').replace(/\s+/g, ' ');
                if (directText) data.text = truncateText(directText);
            } catch (e) {}
            return data;
        }
        function simplifyNode(node) {
            if (elementCount >= MAX_ELEMENTS) return null;
            if (node.nodeType !== Node.ELEMENT_NODE || EXCLUDED_TAGS.includes(node.tagName.toLowerCase())) { if(node.nodeType === Node.TEXT_NODE && node.textContent.trim().length === 0) return null; return null; }
            elementCount++; const elementData = getElementData(node);
            if (node.hasChildNodes()) {
                Array.from(node.childNodes).forEach(child => {
                    if (INTERACTIVE_TAGS.includes(node.tagName.toLowerCase()) && child.nodeType === Node.ELEMENT_NODE) return;
                    const simplifiedChild = simplifyNode(child); if (simplifiedChild) elementData.children.push(simplifiedChild);
                });
            }
            const isInteractive = INTERACTIVE_TAGS.includes(elementData.tag); const hasMeaningfulAttrs = Object.keys(elementData.attributes).some(k => k !== 'x-pw-id');
            if (!isInteractive && !hasMeaningfulAttrs && elementData.children.length === 0 && !elementData.text) { try { if (document.body.contains(node)) node.removeAttribute('x-pw-id'); } catch(e){} return null; }
            return elementData;
        }
        if (!document.body) return "<body> element not found."; const simplifiedBody = simplifyNode(document.body);
        function convertToPseudoHTML(node) {
            if (!node) return ''; let attrs = `x-pw-id="${node.pw_id}"`;
            for (const [key, value] of Object.entries(node.attributes)) attrs += ` ${key}="${String(value).replace(/"/g, '&quot;')}"`;
            let childrenHTML = node.children.map(convertToPseudoHTML).join('');
            let textContent = node.text ? String(node.text).replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
            if (['input', 'img', 'br', 'hr'].includes(node.tag)) return `<${node.tag} ${attrs} />`;
            else return `<${node.tag} ${attrs}>${textContent}${childrenHTML}</${node.tag}>`;
        }
        return convertToPseudoHTML(simplifiedBody);
    })()
    """
except FileNotFoundError:
    logger.error(f"JavaScript file 'findVisibleInteractiveElements.js' not found in {current_dir}. Interactive element detection (JS based) will fail.")
    INTERACTIVE_ELEMENTS_JS_CODE = "() => ({ viewport: { width: window.innerWidth, height: window.innerHeight }, elements: [] });" # Provide fallback
except Exception as e:
     logger.error(f"Error loading JavaScript file(s): {e}", exc_info=True)
     INTERACTIVE_ELEMENTS_JS_CODE = "() => ({ viewport: { width: window.innerWidth, height: window.innerHeight }, elements: [] });"
     SIMPLIFY_PAGE_SCRIPT = "() => 'Error loading simplification script.';"


# --- TypedDict for Viewport Size ---
class ViewportSize(TypedDict):
    width: int
    height: int

# --- BrowserConfig Dataclass (Corrected: No CV Endpoints) ---
@dataclass
class BrowserConfig:
    """
    Configuration for the Browser.
    """
    cdp_url: Optional[str] = None
    viewport_size: ViewportSize = field(default_factory=lambda: {"width": 1200, "height": 900})
    storage_state: Optional[StorageState] = None
    # CV/Sheets Endpoints Removed

# --- Main Browser Class ---
class Browser:
    """
    Unified Browser responsible for interacting with the browser via Playwright.
    Includes methods for navigation, simple actions, perception (DOM, AX Tree, optional VLM),
    and state management. Initializes its own VLM detector based on environment variables.
    """
    def __init__(self, config: BrowserConfig = BrowserConfig(), close_context: bool = True):
        """
        Initializes the Browser instance.
        """
        logger.debug('Initializing browser')
        self.config = config
        self.close_context = close_context
        # Playwright attributes
        self.playwright: Optional[Playwright] = None
        self.playwright_browser: Optional[PlaywrightBrowser] = None
        self.context: Optional[PlaywrightBrowserContext] = None
        # Page and state management
        self.current_page: Optional[Page] = None
        self._state: Optional[BrowserState] = None # This holds the rich state from update_state
        self._cdp_session = None
        # Initialize Detector internally
        try:
            self.detector: Optional[Detector] = Detector()
            if not self.detector.enabled:
                self.detector = None
                logger.warning("Detector initialized but disabled due to missing config/errors.")
            else:
                logger.info("Detector initialized successfully.")
        except NameError:
             logger.error("Detector class not found (likely due to import errors). Vision disabled.")
             self.detector = None
        except Exception as e:
             logger.error(f"Unexpected error initializing Detector: {e}", exc_info=True)
             self.detector = None
        # REMOVED self._init_state() call as method doesn't exist / state init is implicit

    # --- Context Management Methods ---
    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.close_context:
            await self.close()

    # --- Public Initialization and Closing ---
    async def initialize(self):
        """Initializes browser, context, page if not already done."""
        if self.current_page and self.context and self.playwright_browser and self.playwright:
             logger.debug("Browser already initialized.")
             return self
        logger.info("Initializing browser instance via initialize()") # Changed level
        await self._init_browser()
        return self

    async def close(self):
        """Closes the browser and cleans up Playwright resources."""
        if not self.playwright: return
        logger.info('Closing browser...')
        try:
            self._cdp_session = None
            if self.context:
                try: await self.context.close()
                except Exception as e: logger.warning(f'Failed to close context: {e}')
            if self.playwright_browser and not self.config.cdp_url:
                try: await self.playwright_browser.close()
                except Exception as e: logger.warning(f'Failed to close browser: {e}')
            if self.playwright:
                try: await self.playwright.stop()
                except Exception as e: logger.warning(f'Failed to stop Playwright: {e}')
        except Exception as e:
            logger.error(f'Error during browser cleanup: {e}', exc_info=True)
        finally: # Ensure attributes are cleared
            self.context = None; self.current_page = None; self._state = None
            self.playwright_browser = None; self.playwright = None; self._cdp_session = None
            logger.info("Browser closed.")

    # --- Internal Initialization Helper ---
    async def _init_browser(self):
        """Internal method to initialize Playwright components."""
        if self.current_page and self.context: return # Avoid re-init if basics exist
        logger.debug('Running internal browser context initialization _init_browser()')
        try:
            if self.playwright is None: self.playwright = await async_playwright().start()
            if self.playwright_browser is None:
                if self.config.cdp_url:
                    logger.info(f'Connecting to remote browser via CDP {self.config.cdp_url}')
                    self.playwright_browser = await self.playwright.chromium.connect_over_cdp(self.config.cdp_url, timeout=5000)
                else:
                    logger.info(f'Launching new browser instance (headless=False assumed)')
                    # Note: Headless mode might need to be configurable via BrowserConfig again if needed
                    self.playwright_browser = await self.playwright.chromium.launch(
                        headless=False,
                        args=[ # Common args for stability/anti-detection
                            '--no-sandbox', '--disable-setuid-sandbox', '--disable-infobars',
                            '--disable-blink-features=AutomationControlled',
                            '--disable-dev-shm-usage', '--disable-gpu', '--window-size=1200,900', # Use configured size later
                            # '--disable-web-security', # Use with caution
                            # '--disable-site-isolation-trials',
                            # '--disable-features=IsolateOrigins,site-per-process',
                        ]
                    )
            if self.context is None:
                existing_contexts = self.playwright_browser.contexts
                if existing_contexts and not self.config.cdp_url: # Reuse only if we launched it? Be careful.
                    self.context = existing_contexts[0]
                    logger.info("Reusing existing browser context.")
                else:
                    logger.info("Creating new browser context.")
                    self.context = await self.playwright_browser.new_context(
                        viewport=self.config.viewport_size,
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
                        java_script_enabled=True, bypass_csp=True, ignore_https_errors=True,
                        storage_state=self.config.storage_state if self.config.storage_state else None
                    )
                    await self._apply_anti_detection_scripts() # Apply only to new contexts
                self.context.on('page', self._on_page_change) # Attach listener

            if self.current_page is None:
                if len(self.context.pages) > 0:
                    self.current_page = self.context.pages[-1] # Default to last open page
                    logger.info(f"Using existing page: {self.current_page.url}")
                else:
                    self.current_page = await self.context.new_page()
                    logger.info("Created new page.")
                # Ensure viewport is applied regardless
                try: await self.current_page.set_viewport_size(self.config.viewport_size)
                except Exception as vp_err: logger.warning(f"Failed to set viewport: {vp_err}")

            if not self.current_page: raise BrowserError("Failed to get or create a page.")
            await self.get_cdp_session() # Initialize CDP session for current page

        except PlaywrightError as pe:
            logger.error(f"Playwright Error during browser init: {pe}", exc_info=True)
            await self.close(); raise BrowserError(f"Playwright initialization failed: {pe}") from pe
        except Exception as e:
            logger.error(f"Unexpected error during browser init: {e}", exc_info=True)
            await self.close(); raise BrowserError(f"Unexpected browser initialization failed: {e}") from e

    # --- Method Implementations (Ensure ALL referenced methods are defined) ---

    async def _apply_anti_detection_scripts(self):
        """Apply scripts to avoid detection as automation"""
        if self.context is None: return # Should not happen if called from _init_browser correctly
        try:
            await self.context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [] }); // Empty is safer
                // ... other scripts from previous version ...
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
                """
            )
            logger.debug("Applied anti-detection init script.")
        except Exception as e:
             logger.error(f"Failed to add anti-detection init script: {e}", exc_info=True)

    async def _on_page_change(self, page: Page):
        """Handle page creation/popup events."""
        # Don't automatically switch current page, just log
        logger.info(f'Page event detected. New/Popup URL: {page.url}')
        self._cdp_session = None # Invalidate CDP session as context changed

    async def get_current_page(self) -> Page:
        """Get the current page, ensuring browser is initialized."""
        if self.current_page is None or self.current_page.is_closed():
            logger.warning("Current page is None or closed, re-initializing.")
            await self._init_browser()
            if self.current_page is None: raise BrowserError("Unable to get a valid page.")
        return self.current_page

    # Inside Browser class in browser.py
    async def get_cdp_session(self):
        """Get or create a CDP session for the *current* page."""
        page = await self.get_current_page()
        session_invalid = True # Assume invalid
        if self._cdp_session:
            # More robust check: try a simple CDP command to see if session is active
            try:
                # Example: Get cookies via CDP (relatively harmless check)
                await self._cdp_session.send("Network.getAllCookies")
                # Check if session page matches current page (using internal attr is risky)
                if hasattr(self._cdp_session, '_client') and hasattr(self._cdp_session._client, '_page') and self._cdp_session._client._page == page:
                   session_invalid = False # Session seems alive and for the correct page
                else:
                   logger.debug("CDP session page mismatch or internals unclear, recreating.")
            except Exception as session_check_err:
                 logger.debug(f"Existing CDP session check failed ({session_check_err}), recreating.")
                 session_invalid = True

        if session_invalid:
            try:
                if self.context is None: await self._init_browser()
                logger.debug(f"Attempting to create new CDP session for page: {page.url}")
                self._cdp_session = await self.context.new_cdp_session(page)
                logger.debug(f"Created new CDP session successfully.")
            except Exception as e:
                logger.error(f"Failed to create CDP session: {e}", exc_info=True)
                self._cdp_session = None
                raise BrowserError(f"Failed to create CDP session: {e}") from e
        return self._cdp_session

    @observe(name='browser.fast_screenshot', ignore_output=True)
    async def fast_screenshot(self) -> str:
        """Returns a base64 encoded screenshot using CDP."""
        cdp_session = await self.get_cdp_session()
        try:
            screenshot_data = await cdp_session.send("Page.captureScreenshot", {"format": "png", "fromSurface": False, "captureBeyondViewport": False})
            return screenshot_data["data"]
        except Exception as e:
             logger.error(f"Failed to capture screenshot via CDP: {e}")
             # Fallback to playwright's screenshot? Or raise error?
             page = await self.get_current_page()
             try:
                 logger.warning("CDP screenshot failed, falling back to Playwright screenshot.")
                 buffer = await page.screenshot()
                 return base64.b64encode(buffer).decode()
             except Exception as pw_e:
                  logger.error(f"Fallback Playwright screenshot also failed: {pw_e}")
                  raise BrowserError(f"Failed to take screenshot: {e}") from e

    # --- Simple Action Methods ---
    @observe(name='browser.navigate_to')
    async def navigate_to(self, url: str):
        page = await self.get_current_page()
        logger.info(f"Navigating to: {url}")
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            logger.info(f"Navigation successful. Current URL: {page.url}")
        except PlaywrightError as e: raise BrowserError(f"Navigation failed: {e}") from e
        except Exception as e: raise BrowserError(f"Navigation failed unexpectedly: {e}") from e

    @observe(name='browser.click')
    async def click(self, selector: str):
        page = await self.get_current_page()
        logger.info(f"Attempting to click element: '{selector}'")
        try:
            element = page.locator(selector).first
            await element.wait_for(state="visible", timeout=15000)
            await element.scroll_into_view_if_needed(timeout=10000)
            await element.click(timeout=15000, delay=50)
            logger.info(f"Successfully clicked element: '{selector}'")
        except PlaywrightError as e: raise BrowserError(f"Click action failed: {e}") from e
        except Exception as e: raise BrowserError(f"Click action failed unexpectedly: {e}") from e

    @observe(name='browser.type')
    async def type(self, selector: str, text: str):
        page = await self.get_current_page()
        log_text = '***' if 'password' in selector.lower() else text
        logger.info(f"Attempting to type into element: '{selector}', Text: '{log_text}'")
        try:
            element = page.locator(selector).first
            await element.wait_for(state="visible", timeout=15000)
            await element.scroll_into_view_if_needed(timeout=10000)
            await element.fill(text, timeout=15000)
            logger.info(f"Successfully typed into element: '{selector}'")
        except PlaywrightError as e: raise BrowserError(f"Type action failed: {e}") from e
        except Exception as e: raise BrowserError(f"Type action failed unexpectedly: {e}") from e

    @observe(name='browser.scroll')
    async def scroll(self, direction: str):
        page = await self.get_current_page()
        logger.info(f"Scrolling page {direction}")
        try:
            if direction == "down": await page.evaluate("window.scrollBy(0, window.innerHeight)")
            elif direction == "up": await page.evaluate("window.scrollBy(0, -window.innerHeight)")
            elif direction == "left": await page.evaluate("window.scrollBy(-window.innerWidth, 0)")
            elif direction == "right": await page.evaluate("window.scrollBy(window.innerWidth, 0)")
            else: logger.warning(f"Unknown scroll direction: {direction}"); return
            await asyncio.sleep(0.3)
            logger.info(f"Scrolled page {direction}")
        except PlaywrightError as e: raise BrowserError(f"Scroll action failed: {e}") from e
        except Exception as e: raise BrowserError(f"Scroll action failed unexpectedly: {e}") from e

    async def wait(self, milliseconds: int):
        logger.info(f"Waiting for {milliseconds} ms")
        if milliseconds <= 0: return
        await asyncio.sleep(milliseconds / 1000.0)
        logger.info("Wait finished")

    # --- Perception & State Methods ---
    async def get_content(self, max_length: int = 120000) -> str:
        """Gets comprehensive text representation: URL, DOM, AX Tree, VLM Elements."""
        page = await self.get_current_page()
        logger.info("Getting comprehensive page content with vision...")
        combined_content = ""
        error_messages = []
        current_url = "Unknown"
        screenshot_b64 = None
        try:
            current_url = page.url
            combined_content += f"# Page URL:\n{current_url}\n\n"
            try:
                screenshot_b64 = await self.fast_screenshot()
                logger.debug(f"Screenshot captured (size: {len(screenshot_b64) if screenshot_b64 else 0})")
            except Exception as ss_err: error_messages.append(f"Screenshot Error: {ss_err}"); logger.error("Screenshot error", exc_info=False); combined_content += "# Screenshot Error\n"
            try:
                if SIMPLIFY_PAGE_SCRIPT:
                     simplified_dom = await page.evaluate(SIMPLIFY_PAGE_SCRIPT)
                     if simplified_dom: combined_content += f"# Simplified DOM:\n```html\n{simplified_dom}\n```\n\n"; logger.debug(f"DOM length: {len(simplified_dom)}")
                     else: combined_content += "# Simplified DOM:\n(Empty)\n\n"; logger.warning("JS simplification empty.")
                else: combined_content += "# Simplified DOM:\n(JS Script Error)\n\n"; logger.error("SIMPLIFY_PAGE_SCRIPT empty.")
            except Exception as js_err: error_messages.append(f"JS Error: {js_err}"); logger.error("JS Simp. Error", exc_info=False); combined_content += f"# Simplified DOM Error: {js_err}\n"
            try:
                ax_tree = await page.accessibility.snapshot(interesting_only=False) # No root arg
                if ax_tree:
                    try:
                        ax_tree_str = json.dumps(ax_tree, separators=(',', ':')) # Compact
                        ax_max_len = 2000
                        if len(ax_tree_str) > ax_max_len: ax_tree_str = ax_tree_str[:ax_max_len] + "...(AX Tree truncated)"
                        combined_content += f"# Accessibility Tree (JSON, Partial):\n```json\n{ax_tree_str}\n```\n\n"; logger.debug(f"AX Tree length: {len(ax_tree_str)}")
                    except Exception as json_err: error_messages.append(f"AX JSON Error: {json_err}"); logger.error("AX JSON Error", exc_info=False); combined_content += "# AX Tree Error (JSON)\n"
                else: combined_content += "# Accessibility Tree:\n(Empty)\n\n"; logger.warning("AX snapshot empty.")
            except Exception as ax_err: error_messages.append(f"AX Tree Error: {ax_err}"); logger.error("AX Tree Error", exc_info=False); combined_content += f"# Accessibility Tree Error: {ax_err}\n"

            if self.detector and screenshot_b64:
                logger.info("Attempting visual detection via Detector...")
                try:
                    detect_sheets = 'docs.google.com/spreadsheets/d' in current_url
                    visual_elements = await self.detector.detect_from_image(screenshot_b64, detect_sheets)
                    if visual_elements:
                        formatted = [f"- ID: {el.browser_agent_id}, Box: [L:{el.rect.get('left',0)}, T:{el.rect.get('top',0)}, R:{el.rect.get('right',0)}, B:{el.rect.get('bottom',0)}] (Tag: {el.tag_name})" for el in visual_elements[:20]]
                        combined_content += f"# Visual Elements (Detected via CV, Max 20):\n{chr(10).join(formatted)}\n\n"; logger.info(f"Added {len(formatted)} visual elements.") # Use chr(10) for newline
                    else: combined_content += "# Visual Elements:\n(None detected or VLM error)\n\n"; logger.info("No visual elements detected.")
                except Exception as cv_err: error_messages.append(f"CV Error: {cv_err}"); logger.error("CV Detector Error", exc_info=True); combined_content += f"# Visual Elements Error: {cv_err}\n"
            else:
                 if not self.detector: logger.info("CV Detector not available.")
                 if not screenshot_b64: logger.info("Screenshot missing.")
                 combined_content += "# Visual Elements:\n(Not Run)\n\n"

            if len(combined_content) > max_length:
                logger.warning(f"Combined content ({len(combined_content)}) exceeds limit ({max_length}). Truncating.")
                reserve = len("\n\n# Content Retrieval Errors:\n- ") + sum(len(str(e)) + 4 for e in error_messages) + 50
                trunc_len = max(0, max_length - reserve); combined_content = combined_content[:trunc_len].rstrip() + "\n\n... (Content truncated)"
            if error_messages: combined_content += "\n\n# Content Retrieval Errors:\n- " + "\n- ".join(map(str, error_messages))
            logger.info(f"Finished getting content (final length: {len(combined_content)})")
            return combined_content
        except Exception as e: logger.error(f"General error in get_content: {e}", exc_info=True); return f"# Page URL:\n{current_url}\n# Error:\nFailed to get content: {e}"

    # --- Other Methods from Original Code ---

    async def get_cookies(self) -> list[dict[str, Any]]:
        """Get cookies from the current browser context."""
        if self.context:
            try: return await self.context.cookies()
            except Exception as e: logger.error(f"Failed to get cookies: {e}"); return []
        return []

    async def get_storage_state(self) -> dict[str, Any]:
        """Get storage state (currently only cookies) from the browser."""
        # Playwright's get_storage_state includes local/session storage too,
        # but might require more careful handling or filtering if large.
        # Sticking to cookies for simplicity based on original user code structure.
        if self.context:
            try:
                 # cookies = await self.context.cookies() # Redundant if get_cookies exists
                 # return {'cookies': cookies}
                 # Or use the full state function if available and needed
                 state = await self.context.storage_state()
                 return state
            except Exception as e:
                 logger.error(f"Failed to get storage state: {e}")
                 return {}
        return {}

    async def get_tabs_info(self) -> list[TabInfo]:
        """Get information about all open tabs in the current context."""
        tabs_info = []
        if not self.context: return []
        try:
            # Ensure pages list is accessed correctly
            pages = self.context.pages
            for i, page in enumerate(pages):
                 if not page.is_closed(): # Check if page is open
                     try:
                         url = page.url
                         title = await page.title()
                         # Ensure TabInfo model is available
                         tabs_info.append(TabInfo(page_id=i, url=url, title=title))
                     except Exception as page_err:
                          logger.warning(f"Failed to get info for tab {i}: {page_err}")
                          # Add placeholder if needed?
                          tabs_info.append(TabInfo(page_id=i, url="Error", title="Error retrieving info"))

        except Exception as e:
             logger.error(f"Failed to get tabs info: {e}")
        return tabs_info

    async def switch_to_tab(self, page_id: int) -> None:
        """Switch focus to a specific tab by its index."""
        if self.context is None: await self._init_browser()
        pages = self.context.pages
        if not 0 <= page_id < len(pages):
            raise BrowserError(f'Invalid page_id: {page_id}. Available pages: {len(pages)}')
        if pages[page_id].is_closed():
            raise BrowserError(f'Page with page_id {page_id} is closed.')

        logger.info(f"Switching to tab (page_id): {page_id}")
        self.current_page = pages[page_id]
        try:
            await self.current_page.bring_to_front()
            # Wait briefly for potential state changes after switch
            await self.current_page.wait_for_load_state('domcontentloaded', timeout=5000)
        except Exception as e:
             logger.warning(f"Error during tab switch finalization for page {page_id}: {e}")
             # Continue anyway, page is switched internally

    async def create_new_tab(self, url: str | None = None) -> None:
        """Create a new tab, optionally navigating to a URL, and switch to it."""
        if self.context is None: await self._init_browser()
        logger.info(f"Creating new tab. Navigate to: {url if url else 'about:blank'}")
        try:
            new_page = await self.context.new_page()
            self.current_page = new_page # Switch focus to the new page
            if url:
                await self.navigate_to(url) # Reuse navigate method
            else:
                 await new_page.wait_for_load_state('domcontentloaded') # Wait for about:blank load
            logger.info(f"Switched to new tab. URL: {self.current_page.url}")
        except Exception as e:
             logger.error(f"Failed to create new tab: {e}")
             raise BrowserError(f"Failed to create new tab: {e}") from e


    async def close_current_tab(self):
        """Close the currently focused tab."""
        if self.current_page is None: logger.warning("No current page to close."); return
        if len(self.context.pages) <= 1: logger.warning("Cannot close the last remaining tab."); return # Prevent closing last tab? Or allow context close?

        logger.info(f"Closing current tab: {self.current_page.url}")
        page_to_close = self.current_page
        # Find index to switch to after closing (e.g., previous or first)
        pages = self.context.pages
        current_index = pages.index(page_to_close) if page_to_close in pages else -1
        switch_to_index = 0 if current_index != 0 else 1 # Switch to first unless closing first
        if switch_to_index >= len(pages): switch_to_index = 0 # Fallback

        try:
            await page_to_close.close()
            logger.info("Tab closed.")
            # Need to wait briefly for context.pages to update sometimes
            await asyncio.sleep(0.1)
            # Switch to another tab if possible
            if self.context and self.context.pages:
                 new_current_page = self.context.pages[min(switch_to_index, len(self.context.pages)-1)]
                 self.current_page = new_current_page
                 await self.current_page.bring_to_front()
                 logger.info(f"Switched to tab index {min(switch_to_index, len(self.context.pages)-1)} after closing.")
            else:
                 self.current_page = None # No pages left
                 logger.info("Closed the last tab.")

        except Exception as e:
             logger.error(f"Error closing tab or switching: {e}")
             # Attempt to recover current page if possible
             if self.context and self.context.pages: self.current_page = self.context.pages[0]
             else: self.current_page = None

    async def refresh_page(self):
        """Refresh the current page."""
        page = await self.get_current_page()
        logger.info(f"Refreshing page: {page.url}")
        try:
             await page.reload(wait_until='domcontentloaded')
             logger.info("Page refreshed.")
        except Exception as e:
             logger.error(f"Failed to refresh page: {e}")
             raise BrowserError(f"Failed to refresh page: {e}") from e

    async def go_forward(self):
        """Navigate forward in the current page's history."""
        page = await self.get_current_page()
        logger.info(f"Going forward in history for: {page.url}")
        try:
            await page.go_forward(wait_until='domcontentloaded', timeout=10000) # Added timeout
            logger.info(f"Navigated forward. New URL: {page.url}")
        except Exception as e:
            # Often fails if no forward history exists, log as warning
            logger.warning(f'Failed to go forward (might be end of history): {e}')
            # raise BrowserError(f"Failed to go forward: {e}") from e # Option: re-raise if needed

    # --- State Update Methods (using CV potentially) ---
    def get_state(self) -> Optional[BrowserState]:
        """Get the last updated internal browser state."""
        # Returns the state cached from the last update_state call
        logger.debug(f"Returning cached browser state (URL: {self._state.url if self._state else 'None'})")
        return self._state

    @observe(name='browser.update_state', ignore_output=True)
    async def update_state(self) -> BrowserState:
        """Update the internal browser state by re-evaluating the page (incl. CV if enabled)."""
        logger.info("Updating browser state...")
        try:
            self._state = await self._update_state()
            logger.info("Browser state updated successfully.")
            if not self._state: raise BrowserError("State update returned None unexpectedly.") # Should not happen if _update_state raises
            return self._state
        except Exception as e:
             logger.error(f"Failed to update browser state: {e}", exc_info=True)
             # Decide whether to return old state or raise error
             # Raising error seems more appropriate if update fails
             raise BrowserError(f"Failed to update state: {e}") from e


    @observe(name='browser._update_state', ignore_output=True)
    async def _update_state(self) -> BrowserState:
        """Internal method to get comprehensive state with retry logic."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
            retry=retry_if_exception_type((Exception)), # Retry on any exception during state fetch
            reraise=True # Re-raise the exception after retries fail
        )
        async def get_stable_state():
            page = await self.get_current_page() # Ensures page exists
            url = page.url
            detect_sheets = 'docs.google.com/spreadsheets/d' in url
            screenshot_b64 = await self.fast_screenshot() # Get screenshot

            interactive_elements_data: Optional[InteractiveElementsData] = None
            # Get combined elements using CV if detector is enabled
            if self.detector and screenshot_b64:
                logger.debug("Getting interactive elements with CV...")
                interactive_elements_data = await self.get_interactive_elements_with_cv(screenshot_b64, detect_sheets)
            # Fallback to browser-only if detector disabled or screenshot failed
            elif INTERACTIVE_ELEMENTS_JS_CODE: # Ensure JS code loaded
                 logger.debug("Getting interactive elements with browser JS only...")
                 interactive_elements_data = await self.get_interactive_elements_data()
            else:
                 logger.error("Cannot get interactive elements: Detector disabled/failed and JS code missing.")
                 interactive_elements_data = InteractiveElementsData(viewport={"width":0,"height":0}, elements=[]) # Return empty state


            # Check if interactive_elements_data is valid before proceeding
            if interactive_elements_data is None or not hasattr(interactive_elements_data, 'elements'):
                 raise BrowserError("Failed to retrieve valid interactive elements data.")

            # Process elements into dictionary for state
            interactive_elements = {element.browser_agent_id: element for element in interactive_elements_data.elements}

            # Generate highlighted screenshot
            screenshot_with_highlights = None
            if screenshot_b64 and 'put_highlight_elements_on_screenshot' in globals():
                try:
                     screenshot_with_highlights = put_highlight_elements_on_screenshot(
                         list(interactive_elements.values()), # Pass list of elements
                         screenshot_b64
                     )
                except Exception as high_err:
                     logger.warning(f"Failed to generate highlighted screenshot: {high_err}")

            # Get tab info
            tabs = await self.get_tabs_info()

            # Ensure BrowserState model is available
            if 'BrowserState' not in globals() or 'BrowserState' not in locals():
                 raise ImportError("BrowserState model is not defined or imported.")

            # Create and return the state object
            return BrowserState(
                url=url,
                tabs=tabs,
                screenshot_with_highlights=screenshot_with_highlights,
                screenshot=screenshot_b64,
                viewport=interactive_elements_data.viewport, # Use viewport from data
                interactive_elements=interactive_elements,
            )

        # Execute the retry logic
        try:
            new_state = await get_stable_state()
            self._state = new_state # Cache the new state
            return new_state
        except Exception as e:
            logger.error(f'Failed to update state after multiple attempts: {e}', exc_info=True)
            # Don't return potentially stale state, let error propagate
            raise BrowserError(f"Failed to update state definitively: {e}") from e

    @observe(name='browser.get_interactive_elements')
    async def get_interactive_elements_data(self) -> InteractiveElementsData:
        """Gets interactive elements using only in-browser JavaScript."""
        page = await self.get_current_page()
        if not INTERACTIVE_ELEMENTS_JS_CODE:
             logger.error("INTERACTIVE_ELEMENTS_JS_CODE is empty. Cannot get elements.")
             # Return default empty structure
             vp = await page.viewport_size() or {"width":0, "height":0}
             return InteractiveElementsData(viewport=vp, elements=[])
        try:
            result = await page.evaluate(INTERACTIVE_ELEMENTS_JS_CODE)
            # Validate result basic structure
            if not isinstance(result, dict) or 'viewport' not in result or 'elements' not in result:
                 logger.error(f"JS evaluation returned unexpected structure: {type(result)}")
                 vp = await page.viewport_size() or {"width":0, "height":0}
                 return InteractiveElementsData(viewport=vp, elements=[])
            # Parse using Pydantic model if available
            if 'InteractiveElementsData' in globals() and 'InteractiveElementsData' in locals():
                 return InteractiveElementsData(**result)
            else:
                 # Fallback if model missing (though this indicates setup error)
                 logger.error("InteractiveElementsData model missing, returning raw dict.")
                 return result # type: ignore
        except Exception as e:
             logger.error(f"Error evaluating INTERACTIVE_ELEMENTS_JS_CODE: {e}", exc_info=True)
             vp = await page.viewport_size() or {"width":0, "height":0}
             return InteractiveElementsData(viewport=vp, elements=[])


    @observe(name='browser.get_interactive_elements_with_cv')
    async def get_interactive_elements_with_cv(self, screenshot_b64: Optional[str] = None, detect_sheets: bool = False) -> InteractiveElementsData:
        """Combines browser JS element detection with VLM detection."""
        if self.detector is None:
            logger.warning("CV detector not available. Falling back to browser-only detection.")
            return await self.get_interactive_elements_data()

        # Ensure screenshot exists
        current_screenshot_b64 = screenshot_b64 or await self.fast_screenshot()
        if not current_screenshot_b64:
             logger.error("Screenshot unavailable for CV detection.")
             return await self.get_interactive_elements_data() # Fallback

        logger.debug("Getting combined browser + CV elements...")
        try:
            # Run browser JS detection and VLM detection concurrently
            browser_elements_data_task = asyncio.create_task(self.get_interactive_elements_data())
            cv_elements_task = asyncio.create_task(self.detector.detect_from_image(current_screenshot_b64, detect_sheets))

            browser_elements_data = await browser_elements_data_task
            cv_elements = await cv_elements_task

            # Ensure results are valid before combining
            if not browser_elements_data or not hasattr(browser_elements_data, 'elements'):
                 logger.warning("Browser element data invalid or missing for combine step.")
                 browser_elements = []
                 viewport = await self.get_current_page().viewport_size() or {"width":0,"height":0}
            else:
                 browser_elements = browser_elements_data.elements
                 viewport = browser_elements_data.viewport # Use viewport from browser data

            if not isinstance(cv_elements, list):
                 logger.warning("CV elements result is not a list.")
                 cv_elements = []

            # Combine results using utility function
            if 'combine_and_filter_elements' in globals():
                 combined_elements = combine_and_filter_elements(browser_elements, cv_elements)
                 logger.info(f"Combined browser ({len(browser_elements)}) and CV ({len(cv_elements)}) elements into {len(combined_elements)}.")
            else:
                 logger.error("combine_and_filter_elements utility function not found. Returning only browser elements.")
                 combined_elements = browser_elements # Fallback

             # Return combined data in the expected structure
            if 'InteractiveElementsData' in globals() and 'InteractiveElementsData' in locals():
                 return InteractiveElementsData(viewport=viewport, elements=combined_elements)
            else:
                 logger.error("InteractiveElementsData model missing, returning raw combined list.")
                 # This fallback is problematic, structure is needed downstream
                 return {"viewport": viewport, "elements": combined_elements} # type: ignore

        except Exception as e:
            logger.error(f"Error during combined CV+Browser element detection: {e}", exc_info=True)
            # Fallback gracefully to browser-only if possible
            try: return await self.get_interactive_elements_data()
            except Exception: return InteractiveElementsData(viewport={"width":0,"height":0}, elements=[]) # Final fallback