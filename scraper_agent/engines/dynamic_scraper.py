"""
Dynamic Scraper Engine — Production Grade.
Uses Playwright (preferred) or Selenium for JavaScript-rendered websites.
Includes proxy support, stealth mode, and robust error handling.
"""

import logging
import time
from typing import Dict, Optional

from scraper_agent.config import ScraperConfig
from scraper_agent.engines.base import BaseScraper
from scraper_agent.exceptions import (
    BrowserError, FetchError, NoBrowserAvailableError, TimeoutError,
)

logger = logging.getLogger("scraper_agent")

# Feature detection
PLAYWRIGHT_AVAILABLE = False
SELENIUM_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

if not PLAYWRIGHT_AVAILABLE:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import TimeoutException, WebDriverException
        SELENIUM_AVAILABLE = True
    except ImportError:
        pass


class DynamicScraper(BaseScraper):
    """
    Production scraper engine for JavaScript-rendered websites.
    Auto-selects Playwright or Selenium with stealth and proxy support.
    """

    def __init__(self, config: ScraperConfig, proxies: Optional[Dict[str, str]] = None):
        super().__init__(config)
        self._proxies = proxies
        self._playwright = None
        self._browser = None
        self._context = None
        self._selenium_driver = None
        self._engine = None
        self._request_count = 0
        self._total_bytes = 0

        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """Initialize the best available browser engine."""
        if PLAYWRIGHT_AVAILABLE:
            self._init_playwright()
        elif SELENIUM_AVAILABLE:
            self._init_selenium()
        else:
            raise NoBrowserAvailableError(
                "No dynamic scraping engine available. "
                "Install: pip install playwright && playwright install chromium  OR  "
                "pip install selenium"
            )

    def _init_playwright(self) -> None:
        """Initialize Playwright with stealth and optional proxy."""
        try:
            self._playwright = sync_playwright().start()

            launchers = {
                "chromium": self._playwright.chromium,
                "firefox": self._playwright.firefox,
                "webkit": self._playwright.webkit,
            }
            launcher = launchers.get(self.config.browser_type, self._playwright.chromium)

            launch_args = {"headless": self.config.headless}

            # Proxy support
            if self._proxies:
                proxy_url = self._proxies.get("http") or self._proxies.get("https", "")
                if proxy_url:
                    launch_args["proxy"] = {"server": proxy_url}
                    logger.debug(f"Playwright using proxy: {proxy_url}")

            self._browser = launcher.launch(**launch_args)

            # Stealth context
            self._context = self._browser.new_context(
                user_agent=(
                    self.config.user_agent or
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                java_script_enabled=True,
                locale="en-US",
                timezone_id="America/New_York",
            )

            # Block unnecessary resources for speed
            self._context.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf}", lambda route: route.abort())

            self._engine = "playwright"
            logger.info(f"Playwright initialized ({self.config.browser_type}, headless={self.config.headless})")

        except Exception as e:
            logger.warning(f"Playwright init failed: {e}")
            self._cleanup_playwright()
            if SELENIUM_AVAILABLE:
                logger.info("Falling back to Selenium...")
                self._init_selenium()
            else:
                raise BrowserError(f"Failed to initialize Playwright: {e}")

    def _init_selenium(self) -> None:
        """Initialize Selenium with stealth and optional proxy."""
        try:
            options = ChromeOptions()

            if self.config.headless:
                options.add_argument("--headless=new")

            # Stealth options
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-infobars")

            ua = self.config.user_agent or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            options.add_argument(f"--user-agent={ua}")

            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            # Proxy support
            if self._proxies:
                proxy_url = self._proxies.get("http") or self._proxies.get("https", "")
                if proxy_url:
                    options.add_argument(f"--proxy-server={proxy_url}")

            self._selenium_driver = webdriver.Chrome(options=options)
            self._selenium_driver.set_page_load_timeout(self.config.page_load_timeout / 1000)

            # Anti-detection script
            self._selenium_driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            )

            self._engine = "selenium"
            logger.info("Selenium initialized (Chrome, headless={})".format(self.config.headless))

        except Exception as e:
            raise BrowserError(f"Failed to initialize Selenium: {e}")

    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch page HTML after JavaScript rendering."""
        if self._engine == "playwright":
            return self._fetch_playwright(url)
        elif self._engine == "selenium":
            return self._fetch_selenium(url)
        else:
            logger.error("No scraping engine initialized")
            return None

    def _fetch_playwright(self, url: str) -> Optional[str]:
        """Fetch with Playwright — full JS rendering."""
        page = None
        start = time.time()
        try:
            logger.debug(f"Fetching (Playwright): {url}")
            page = self._context.new_page()

            page.goto(url, timeout=self.config.page_load_timeout, wait_until="networkidle")

            if self.config.wait_for_selector:
                page.wait_for_selector(self.config.wait_for_selector, timeout=self.config.page_load_timeout)

            self._playwright_scroll(page)

            html = page.content()
            self._request_count += 1
            self._total_bytes += len(html.encode("utf-8", errors="ignore"))

            logger.debug(f"Fetched {url} - {len(html):,} chars, {time.time()-start:.1f}s (Playwright)")
            return html

        except PlaywrightTimeout:
            logger.error(f"Playwright timeout: {url}")
            raise TimeoutError(message="Playwright page load timed out", url=url)
        except Exception as e:
            logger.error(f"Playwright error: {url} - {e}")
            return None
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def _playwright_scroll(self, page) -> None:
        """Scroll page to trigger lazy loading."""
        try:
            page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 300;
                        const timer = setInterval(() => {
                            const scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= scrollHeight) {
                                clearInterval(timer);
                                window.scrollTo(0, 0);
                                resolve();
                            }
                        }, 100);
                    });
                }
            """)
            page.wait_for_timeout(1000)
        except Exception:
            pass

    def _fetch_selenium(self, url: str) -> Optional[str]:
        """Fetch with Selenium — full JS rendering."""
        start = time.time()
        try:
            logger.debug(f"Fetching (Selenium): {url}")
            self._selenium_driver.get(url)

            WebDriverWait(self._selenium_driver, self.config.page_load_timeout / 1000).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            if self.config.wait_for_selector:
                WebDriverWait(self._selenium_driver, self.config.page_load_timeout / 1000).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, self.config.wait_for_selector))
                )

            self._selenium_scroll()

            html = self._selenium_driver.page_source
            self._request_count += 1
            self._total_bytes += len(html.encode("utf-8", errors="ignore"))

            logger.debug(f"Fetched {url} - {len(html):,} chars, {time.time()-start:.1f}s (Selenium)")
            return html

        except TimeoutException:
            logger.error(f"Selenium timeout: {url}")
            raise TimeoutError(message="Selenium page load timed out", url=url)
        except WebDriverException as e:
            logger.error(f"Selenium error: {url} - {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def _selenium_scroll(self) -> None:
        """Scroll with Selenium to trigger lazy loading."""
        try:
            import time as _time
            for _ in range(5):
                self._selenium_driver.execute_script("window.scrollBy(0, 300);")
                _time.sleep(0.3)
            self._selenium_driver.execute_script("window.scrollTo(0, 0);")
            _time.sleep(0.5)
        except Exception:
            pass

    def get_metrics(self) -> dict:
        """Return engine metrics."""
        return {
            "engine": f"dynamic ({self._engine})",
            "requests": self._request_count,
            "total_bytes": self._total_bytes,
            "total_mb": f"{self._total_bytes / (1024*1024):.1f}",
        }

    def _cleanup_playwright(self) -> None:
        """Clean up Playwright resources."""
        for obj in (self._context, self._browser, self._playwright):
            try:
                if obj:
                    if hasattr(obj, "close"):
                        obj.close()
                    elif hasattr(obj, "stop"):
                        obj.stop()
            except Exception:
                pass
        self._context = self._browser = self._playwright = None

    def close(self) -> None:
        """Clean up all browser resources."""
        if self._engine == "playwright":
            self._cleanup_playwright()
            logger.debug("Playwright closed")
        elif self._engine == "selenium":
            try:
                if self._selenium_driver:
                    self._selenium_driver.quit()
            except Exception:
                pass
            self._selenium_driver = None
            logger.debug("Selenium closed")
