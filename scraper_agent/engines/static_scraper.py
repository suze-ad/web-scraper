"""
Static Scraper Engine — Production Grade.
Uses Requests + BeautifulSoup with proxy support, session rotation, and retry logic.
"""

import logging
import time
from typing import Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper_agent.config import ScraperConfig
from scraper_agent.engines.base import BaseScraper
from scraper_agent.exceptions import FetchError, HTTPError, TimeoutError, BlockedError

try:
    from fake_useragent import UserAgent
    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

logger = logging.getLogger("scraper_agent")


class StaticScraper(BaseScraper):
    """
    Production scraper engine for static HTML websites.
    Features: session pooling, proxy support, bot-detection evasion, retry logic.
    """

    # Response size limits
    MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB

    # Bot-detection indicators in response
    BOT_INDICATORS = [
        "captcha", "cf-browser-verification", "challenge-platform",
        "just a moment", "checking your browser", "access denied",
        "are you a robot", "verify you are human",
    ]

    def __init__(self, config: ScraperConfig, proxies: Optional[Dict[str, str]] = None):
        super().__init__(config)
        self._proxies = proxies
        self.session = self._create_session()
        self._request_count = 0
        self._total_bytes = 0

    def _create_session(self) -> requests.Session:
        """Create a production-configured requests session."""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.config.rate_limit.max_retries,
            backoff_factor=self.config.rate_limit.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update(self._get_headers())

        if self._proxies:
            session.proxies.update(self._proxies)
            logger.debug(f"Session using proxy: {list(self._proxies.values())[0]}")

        return session

    def _get_headers(self) -> dict:
        """Generate realistic browser headers."""
        if self.config.user_agent:
            user_agent = self.config.user_agent
        elif HAS_FAKE_UA:
            try:
                user_agent = UserAgent().random
            except Exception:
                user_agent = self._default_user_agent()
        else:
            user_agent = self._default_user_agent()

        return {
            "User-Agent": user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    @staticmethod
    def _default_user_agent() -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    def set_proxies(self, proxies: Dict[str, str]) -> None:
        """Update session proxies (for proxy rotation)."""
        self._proxies = proxies
        self.session.proxies.update(proxies)

    def rotate_user_agent(self) -> None:
        """Rotate to a new user agent for the session."""
        self.session.headers.update(self._get_headers())

    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch page HTML with production error handling.

        Args:
            url: URL to fetch

        Returns:
            HTML content string or None on failure

        Raises:
            BlockedError: If bot detection is triggered
            HTTPError: On non-recoverable HTTP errors
        """
        start_time = time.time()

        try:
            logger.debug(f"Fetching (static): {url}")
            response = self.session.get(
                url,
                timeout=self.config.timeout,
                allow_redirects=True,
                stream=True,
            )

            # Check content length before downloading
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.MAX_RESPONSE_SIZE:
                logger.warning(f"Response too large ({content_length} bytes): {url}")
                response.close()
                return None

            # Read content
            response.raise_for_status()

            if response.encoding is None:
                response.encoding = response.apparent_encoding

            html = response.text
            self._request_count += 1
            self._total_bytes += len(html.encode("utf-8", errors="ignore"))

            latency = time.time() - start_time

            # Check for bot detection
            if self._is_blocked(html):
                logger.warning(f"Bot detection triggered on {url}")
                raise BlockedError(
                    message="Bot detection triggered",
                    url=url,
                    details="Response contains CAPTCHA or challenge page",
                )

            logger.debug(
                f"Fetched {url} - {response.status_code}, "
                f"{len(html):,} chars, {latency:.1f}s"
            )
            return html

        except BlockedError:
            raise
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            logger.error(f"HTTP {status} fetching {url}")
            raise HTTPError(status_code=status, url=url)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout ({self.config.timeout}s) fetching {url}")
            raise TimeoutError(message="Request timed out", url=url)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {url} - {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {url} - {e}")
            return None

    def _is_blocked(self, html: str) -> bool:
        """Detect if the response is a bot challenge/block page."""
        html_lower = html.lower()
        # Short responses with bot indicators are likely blocks
        if len(html) < 5000:
            return any(indicator in html_lower for indicator in self.BOT_INDICATORS)
        return False

    def get_metrics(self) -> dict:
        """Return engine metrics."""
        return {
            "engine": "static",
            "requests": self._request_count,
            "total_bytes": self._total_bytes,
            "total_mb": f"{self._total_bytes / (1024*1024):.1f}",
        }

    def close(self) -> None:
        """Close the requests session."""
        if self.session:
            self.session.close()
            logger.debug("Static scraper session closed")
