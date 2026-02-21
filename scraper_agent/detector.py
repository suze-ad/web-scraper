"""
Site Detection Layer.
Determines whether a website is static or dynamic (JavaScript-rendered)
to choose the appropriate scraping engine.
"""

import logging
import requests
from bs4 import BeautifulSoup
from typing import Tuple
from fake_useragent import UserAgent

logger = logging.getLogger("scraper_agent")


class SiteDetector:
    """Detects whether a website is static or requires JavaScript rendering."""

    # Indicators that a site uses heavy JavaScript rendering
    JS_FRAMEWORK_INDICATORS = [
        "react", "angular", "vue", "__NEXT_DATA__", "__NUXT__",
        "window.__INITIAL_STATE__", "window.__PRELOADED_STATE__",
        "data-reactroot", "data-reactid", "ng-app", "ng-controller",
        "v-app", "v-cloak", "data-v-", "_app.js", "_buildManifest.js",
        "webpack", "bundle.js", "chunk.js",
    ]

    # Common product container selectors to check for content presence
    PRODUCT_INDICATORS = [
        "product", "item", "listing", "card", "goods",
        "price", "add-to-cart", "buy-now",
    ]

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        try:
            self.ua = UserAgent()
        except Exception:
            self.ua = None

    def _get_headers(self) -> dict:
        """Generate request headers with a realistic user agent."""
        user_agent = self.ua.random if self.ua else (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def detect(self, url: str) -> Tuple[str, dict]:
        """
        Detect whether a site is static or dynamic.

        Args:
            url: The website URL to analyze

        Returns:
            Tuple of (site_type, analysis_info)
            site_type: "static" or "dynamic"
            analysis_info: Dict with detection details
        """
        logger.info(f"Analyzing site type for: {url}")
        analysis = {
            "url": url,
            "js_frameworks_found": [],
            "has_product_content": False,
            "product_indicators_found": [],
            "noscript_fallback": False,
            "confidence": 0.0,
        }

        try:
            response = requests.get(
                url, headers=self._get_headers(), timeout=self.timeout
            )
            response.raise_for_status()
            html = response.text
            soup = BeautifulSoup(html, "lxml")

            # Check for JS framework indicators
            html_lower = html.lower()
            for indicator in self.JS_FRAMEWORK_INDICATORS:
                if indicator.lower() in html_lower:
                    analysis["js_frameworks_found"].append(indicator)

            # Check for product content in static HTML
            for indicator in self.PRODUCT_INDICATORS:
                elements = soup.find_all(
                    attrs={"class": lambda c: c and indicator in str(c).lower()}
                )
                if elements:
                    analysis["has_product_content"] = True
                    analysis["product_indicators_found"].append(
                        f"{indicator} ({len(elements)} elements)"
                    )

            # Check for noscript fallback
            noscript = soup.find_all("noscript")
            if noscript:
                noscript_text = " ".join(tag.get_text() for tag in noscript)
                if any(kw in noscript_text.lower() for kw in ["enable javascript", "requires javascript"]):
                    analysis["noscript_fallback"] = True

            # Check if body content is minimal (likely JS-rendered)
            body = soup.find("body")
            body_text = body.get_text(strip=True) if body else ""
            body_children = len(list(body.children)) if body else 0

            # Decision logic
            js_score = len(analysis["js_frameworks_found"])
            content_score = len(analysis["product_indicators_found"])

            is_dynamic = False

            # Strong JS signals
            if js_score >= 3:
                is_dynamic = True
                analysis["confidence"] = 0.9

            # JS frameworks present but content also found statically
            elif js_score >= 1 and content_score == 0:
                is_dynamic = True
                analysis["confidence"] = 0.8

            # Minimal body content suggests JS rendering
            elif len(body_text) < 200 and body_children < 10:
                is_dynamic = True
                analysis["confidence"] = 0.7

            # Noscript fallback present
            elif analysis["noscript_fallback"]:
                is_dynamic = True
                analysis["confidence"] = 0.6

            # Static content with products found
            elif content_score > 0:
                is_dynamic = False
                analysis["confidence"] = 0.9

            else:
                # Default to static with lower confidence
                is_dynamic = False
                analysis["confidence"] = 0.5

            site_type = "dynamic" if is_dynamic else "static"
            logger.info(
                f"Site detected as: {site_type.upper()} "
                f"(confidence: {analysis['confidence']:.0%})"
            )
            logger.debug(f"JS frameworks found: {analysis['js_frameworks_found']}")
            logger.debug(f"Product indicators: {analysis['product_indicators_found']}")

            return site_type, analysis

        except requests.RequestException as e:
            logger.error(f"Error analyzing site {url}: {e}")
            # Default to dynamic on error (more robust scraping)
            analysis["confidence"] = 0.3
            return "dynamic", analysis
