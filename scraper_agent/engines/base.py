"""
Base Scraper Engine.
Abstract base class that defines the interface for all scraper engines.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from bs4 import BeautifulSoup

from scraper_agent.config import ScraperConfig

logger = logging.getLogger("scraper_agent")


class BaseScraper(ABC):
    """Abstract base class for scraper engines."""

    def __init__(self, config: ScraperConfig):
        self.config = config

    @abstractmethod
    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch the HTML content of a page.

        Args:
            url: The URL to fetch

        Returns:
            HTML content as string, or None on failure
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Clean up resources (browser instances, sessions, etc.)."""
        pass

    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML string into a BeautifulSoup object."""
        return BeautifulSoup(html, "lxml")

    def find_product_containers(self, soup: BeautifulSoup) -> List:
        """
        Find product container elements on the page using common patterns.

        Args:
            soup: Parsed HTML

        Returns:
            List of product container elements
        """
        custom = self.config.custom_selectors.get("product_container")
        if custom:
            containers = soup.select(custom)
            if containers:
                logger.debug(f"Found {len(containers)} containers via custom selector")
                return containers

        # Common product container patterns (ordered by specificity)
        selector_patterns = [
            # Data attributes
            "[data-component-type='s-search-result']",   # Amazon
            "[data-testid='product-card']",
            "[data-product-id]",
            "[data-item-id]",
            "[data-pid]",
            "[data-sku]",
            # Schema.org markup
            "[itemtype*='schema.org/Product']",
            "[typeof='Product']",
            # Common class patterns
            ".product-card",
            ".product-item",
            ".product-tile",
            ".product-grid-item",
            ".product-listing",
            ".product",
            ".s-result-item",
            ".grid-item",
            ".listing-item",
            ".search-result",
            # E-commerce specific
            ".shopify-section product",
            ".woocommerce-loop-product",
            "li.product",
            ".col .product-miniature",
            # Broader patterns with underscores and camelCase
            "[class*='product-card']",
            "[class*='product-item']",
            "[class*='ProductCard']",
            "[class*='productCard']",
            "[class*='product_card']",
            "[class*='product_pod']",
            "[class*='product_item']",
            "[class*='productItem']",
            "[class*='ProductItem']",
            # Article-based product containers
            "article.product_pod",
            "article.product",
            "article[class*='product']",
            # Div-based
            "div[class*='product']",
            "div[class*='Product']",
            # List-based
            "li[class*='product']",
            "li[class*='Product']",
        ]

        for selector in selector_patterns:
            try:
                containers = soup.select(selector)
                if len(containers) >= 2:  # At least 2 products to be a valid listing
                    logger.info(
                        f"Found {len(containers)} product containers "
                        f"with selector: {selector}"
                    )
                    return containers
            except Exception:
                continue

        # Fallback: look for repeated similar structures
        logger.warning("No standard product containers found, attempting heuristic detection")
        return self._heuristic_container_detection(soup)

    def _heuristic_container_detection(self, soup: BeautifulSoup) -> List:
        """
        Fallback heuristic: find groups of similar elements that look like product listings.
        """
        candidates = []

        # Look for list items or divs that contain both price-like and link content
        for parent in soup.find_all(["ul", "ol", "div", "section"]):
            children = parent.find_all(recursive=False)
            if len(children) < 3:
                continue

            # Check if children have similar structure
            child_tags = [child.name for child in children]
            if len(set(child_tags)) <= 2:  # Mostly same tag type
                # Check if they contain price-like text
                price_count = 0
                link_count = 0
                for child in children:
                    text = child.get_text()
                    if any(sym in text for sym in ["$", "€", "£", "¥", "₹", "price"]):
                        price_count += 1
                    if child.find("a"):
                        link_count += 1

                if price_count >= len(children) * 0.5 and link_count >= len(children) * 0.5:
                    candidates = children
                    logger.info(
                        f"Heuristic detection found {len(candidates)} "
                        f"potential product containers"
                    )
                    return candidates

        return candidates

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
