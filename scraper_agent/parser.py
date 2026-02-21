"""
Structured Parser.
Extracts product data fields from HTML product container elements.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import Tag

logger = logging.getLogger("scraper_agent")


class ProductParser:
    """Extracts structured product data from HTML elements."""

    # Price regex patterns to match various currency formats
    PRICE_PATTERNS = [
        r'[\$€£¥₹]\s*[\d,]+\.?\d*',       # $12.99, €12,99
        r'[\d,]+\.?\d*\s*[\$€£¥₹]',         # 12.99$, 12,99€
        r'[\d,]+\.\d{2}',                    # 12.99
        r'(?:USD|EUR|GBP|INR)\s*[\d,]+\.?\d*',  # USD 12.99
        r'[\d,]+\.?\d*\s*(?:USD|EUR|GBP|INR)',   # 12.99 USD
        r'Price:\s*[\$€£¥₹]?\s*[\d,]+\.?\d*',   # Price: $12.99
    ]

    # Availability status indicators
    IN_STOCK_INDICATORS = [
        "in stock", "available", "add to cart", "buy now",
        "add to bag", "in-stock", "ships from",
    ]
    OUT_OF_STOCK_INDICATORS = [
        "out of stock", "sold out", "unavailable", "not available",
        "out-of-stock", "currently unavailable", "notify me",
    ]

    def __init__(self, base_url: str, custom_selectors: Optional[dict] = None):
        self.base_url = base_url
        self.custom_selectors = custom_selectors or {}

    def parse_product(self, container: Tag) -> Optional[Dict[str, Any]]:
        """
        Extract product data from a single product container element.

        Args:
            container: BeautifulSoup Tag representing one product

        Returns:
            Dict with product data, or None if extraction failed
        """
        product = {
            "name": self._extract_name(container),
            "price": self._extract_price(container),
            "availability": self._extract_availability(container),
            "product_url": self._extract_product_url(container),
            "image_url": self._extract_image_url(container),
        }

        # Only return if we got at least a name or price
        if product["name"] or product["price"]:
            return product

        logger.debug("Skipping container: could not extract name or price")
        return None

    def parse_all(self, containers: List[Tag]) -> List[Dict[str, Any]]:
        """
        Parse all product containers and return structured data.

        Args:
            containers: List of product container elements

        Returns:
            List of product data dictionaries
        """
        products = []
        for i, container in enumerate(containers):
            try:
                product = self.parse_product(container)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug(f"Error parsing product container {i}: {e}")
                continue

        logger.info(f"Parsed {len(products)} products from {len(containers)} containers")
        return products

    # ── Name Extraction ──────────────────────────────────────────────────

    def _extract_name(self, container: Tag) -> Optional[str]:
        """Extract product name from container."""
        # Custom selector
        custom = self.custom_selectors.get("product_name")
        if custom:
            el = container.select_one(custom)
            if el:
                return self._clean_text(el.get_text())

        # Strategy 1: Schema.org markup
        name_el = container.find(attrs={"itemprop": "name"})
        if name_el:
            return self._clean_text(name_el.get_text())

        # Strategy 2: Common name selectors
        name_selectors = [
            "[data-testid='product-name']",
            "[data-testid='product-title']",
            ".product-name", ".product-title", ".product-heading",
            ".item-name", ".item-title",
            "h2 a", "h3 a", "h4 a",
            "h2", "h3", "h4",
            ".title a", ".name a",
            "[class*='product-name']", "[class*='product-title']",
            "[class*='productName']", "[class*='productTitle']",
            "a.product-link",
        ]

        for selector in name_selectors:
            try:
                el = container.select_one(selector)
                if el:
                    text = self._clean_text(el.get_text())
                    if text and len(text) > 2:
                        return text
            except Exception:
                continue

        # Strategy 3: First meaningful link text in container
        for a_tag in container.find_all("a", href=True):
            text = self._clean_text(a_tag.get_text())
            if text and len(text) > 5 and not text.startswith(("http", "www")):
                return text

        return None

    # ── Price Extraction ─────────────────────────────────────────────────

    def _extract_price(self, container: Tag) -> Optional[str]:
        """Extract product price from container."""
        # Custom selector
        custom = self.custom_selectors.get("product_price")
        if custom:
            el = container.select_one(custom)
            if el:
                return self._extract_price_text(el.get_text())

        # Strategy 1: Schema.org markup
        price_el = container.find(attrs={"itemprop": "price"})
        if price_el:
            price_val = price_el.get("content") or price_el.get_text()
            if price_val:
                return self._clean_text(str(price_val))

        # Strategy 2: Common price selectors
        price_selectors = [
            "[data-testid='product-price']",
            "[data-testid='price']",
            ".price", ".product-price", ".item-price",
            ".sale-price", ".current-price",
            ".a-price .a-offscreen",   # Amazon
            ".a-price",                 # Amazon
            "span[data-price]",
            "[class*='price']",
            "[class*='Price']",
            ".cost", ".amount",
            "ins .amount",             # WooCommerce sale price
            ".special-price",
        ]

        for selector in price_selectors:
            try:
                el = container.select_one(selector)
                if el:
                    # Check for data attributes first
                    price = el.get("data-price") or el.get("content")
                    if price:
                        return self._clean_text(str(price))

                    text = el.get_text()
                    price = self._extract_price_text(text)
                    if price:
                        return price
            except Exception:
                continue

        # Strategy 3: Regex search in full container text
        text = container.get_text()
        return self._extract_price_text(text)

    def _extract_price_text(self, text: str) -> Optional[str]:
        """Extract price value from text using regex patterns."""
        if not text:
            return None

        text = text.strip()
        for pattern in self.PRICE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return self._clean_text(match.group(0))

        return None

    # ── Availability Extraction ──────────────────────────────────────────

    def _extract_availability(self, container: Tag) -> str:
        """Extract product availability status."""
        # Custom selector
        custom = self.custom_selectors.get("availability")
        if custom:
            el = container.select_one(custom)
            if el:
                return self._determine_availability(el.get_text())

        # Strategy 1: Schema.org markup
        avail_el = container.find(attrs={"itemprop": "availability"})
        if avail_el:
            content = avail_el.get("content", "") or avail_el.get("href", "")
            if "InStock" in content or "instock" in content.lower():
                return "In Stock"
            elif "OutOfStock" in content or "outofstock" in content.lower():
                return "Out of Stock"

        # Strategy 2: Common availability selectors
        avail_selectors = [
            ".availability", ".stock-status", ".stock",
            "[data-testid='availability']",
            "[class*='availability']", "[class*='stock']",
            ".product-availability",
        ]

        for selector in avail_selectors:
            try:
                el = container.select_one(selector)
                if el:
                    return self._determine_availability(el.get_text())
            except Exception:
                continue

        # Strategy 3: Check full container text
        text = container.get_text().lower()
        return self._determine_availability(text)

    def _determine_availability(self, text: str) -> str:
        """Determine availability from text content."""
        text_lower = text.lower().strip()

        for indicator in self.OUT_OF_STOCK_INDICATORS:
            if indicator in text_lower:
                return "Out of Stock"

        for indicator in self.IN_STOCK_INDICATORS:
            if indicator in text_lower:
                return "In Stock"

        return "Unknown"

    # ── URL Extraction ───────────────────────────────────────────────────

    def _extract_product_url(self, container: Tag) -> Optional[str]:
        """Extract product detail page URL."""
        # Custom selector
        custom = self.custom_selectors.get("product_url")
        if custom:
            el = container.select_one(custom)
            if el:
                href = el.get("href")
                if href:
                    return urljoin(self.base_url, href)

        # Strategy 1: Schema.org
        url_el = container.find(attrs={"itemprop": "url"})
        if url_el:
            href = url_el.get("href") or url_el.get("content")
            if href:
                return urljoin(self.base_url, href)

        # Strategy 2: First meaningful link (usually product title link)
        name_links = container.select("h2 a, h3 a, h4 a, .product-name a, .product-title a")
        if name_links:
            href = name_links[0].get("href")
            if href:
                return urljoin(self.base_url, href)

        # Strategy 3: Any link that looks like a product page
        for a_tag in container.find_all("a", href=True):
            href = a_tag.get("href", "")
            if any(kw in href.lower() for kw in ["/product", "/item", "/p/", "/dp/", "/pd/"]):
                return urljoin(self.base_url, href)

        # Strategy 4: First link in container
        first_link = container.find("a", href=True)
        if first_link:
            href = first_link.get("href")
            if href and href != "#":
                return urljoin(self.base_url, href)

        return None

    # ── Image URL Extraction ─────────────────────────────────────────────

    def _extract_image_url(self, container: Tag) -> Optional[str]:
        """Extract product image URL."""
        # Custom selector
        custom = self.custom_selectors.get("product_image")
        if custom:
            el = container.select_one(custom)
            if el:
                src = self._get_image_src(el)
                if src:
                    return urljoin(self.base_url, src)

        # Strategy 1: Schema.org
        img_el = container.find(attrs={"itemprop": "image"})
        if img_el:
            src = self._get_image_src(img_el)
            if src:
                return urljoin(self.base_url, src)

        # Strategy 2: Find product images
        img_selectors = [
            ".product-image img", ".product-img img",
            ".item-image img", ".thumbnail img",
            "[data-testid='product-image'] img",
            "img.product-image", "img.product-img",
            "[class*='product-image'] img",
            "[class*='productImage'] img",
            "img",  # Fallback: first img in container
        ]

        for selector in img_selectors:
            try:
                el = container.select_one(selector)
                if el:
                    src = self._get_image_src(el)
                    if src and not self._is_icon_or_placeholder(src):
                        return urljoin(self.base_url, src)
            except Exception:
                continue

        return None

    def _get_image_src(self, img: Tag) -> Optional[str]:
        """Get the best image source from an img tag (handles lazy loading)."""
        # Check various src attributes (lazy loading patterns)
        for attr in ["src", "data-src", "data-lazy-src", "data-original",
                      "data-srcset", "srcset", "data-image", "data-zoom-image"]:
            src = img.get(attr)
            if src:
                # For srcset, take the first URL
                if "," in str(src):
                    src = src.split(",")[0].strip().split(" ")[0]
                if src and not src.startswith("data:"):
                    return src
        return None

    def _is_icon_or_placeholder(self, src: str) -> bool:
        """Check if an image URL is likely an icon or placeholder."""
        src_lower = src.lower()
        skip_patterns = [
            "icon", "logo", "badge", "placeholder", "blank",
            "pixel", "spacer", "loading", "spinner",
            "1x1", "transparent",
        ]
        return any(pattern in src_lower for pattern in skip_patterns)

    # ── Utilities ────────────────────────────────────────────────────────

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean and normalize extracted text."""
        if not text:
            return ""
        # Remove extra whitespace, newlines, tabs
        text = re.sub(r'\s+', ' ', text).strip()
        return text
