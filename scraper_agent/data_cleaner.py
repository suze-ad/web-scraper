"""
Data Cleaner.
Cleans, normalizes, and deduplicates scraped product data.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scraper_agent")


class DataCleaner:
    """Cleans and normalizes raw product data."""

    def clean(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Clean and normalize a list of product records.

        Args:
            products: Raw product data dictionaries

        Returns:
            Cleaned and deduplicated product list
        """
        if not products:
            return []

        cleaned = []
        for product in products:
            try:
                cleaned_product = self._clean_product(product)
                if cleaned_product:
                    cleaned.append(cleaned_product)
            except Exception as e:
                logger.debug(f"Error cleaning product: {e}")
                continue

        # Deduplicate
        before_dedup = len(cleaned)
        cleaned = self._deduplicate(cleaned)
        removed = before_dedup - len(cleaned)
        if removed > 0:
            logger.info(f"Removed {removed} duplicate products")

        logger.info(f"Cleaned data: {len(cleaned)} products retained")
        return cleaned

    def _clean_product(self, product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Clean a single product record."""
        cleaned = {}

        # Clean name
        name = product.get("name")
        if name:
            name = self._clean_name(name)
        if not name or len(name) < 2:
            return None  # Skip products without valid names
        cleaned["name"] = name

        # Clean price
        price = product.get("price")
        cleaned["price"] = self._clean_price(price) if price else None
        cleaned["price_numeric"] = self._extract_numeric_price(price) if price else None

        # Clean availability
        availability = product.get("availability", "Unknown")
        cleaned["availability"] = self._clean_availability(availability)

        # Clean URLs
        cleaned["product_url"] = self._clean_url(product.get("product_url"))
        cleaned["image_url"] = self._clean_url(product.get("image_url"))

        return cleaned

    def _clean_name(self, name: str) -> str:
        """Clean product name."""
        # Remove excessive whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        # Remove common junk prefixes/suffixes
        junk_patterns = [
            r'^(New|Sale|Hot|Best Seller|Trending)[\s!:|-]+',
            r'\s*\(?\d+\s*reviews?\)?$',
            r'\s*-\s*$',
        ]
        for pattern in junk_patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE).strip()
        # Truncate extremely long names
        if len(name) > 300:
            name = name[:297] + "..."
        return name

    def _clean_price(self, price: str) -> Optional[str]:
        """Clean and normalize price string."""
        if not price:
            return None

        price = price.strip()

        # Extract price pattern
        match = re.search(r'([\$€£¥₹]?\s*[\d,]+\.?\d*\s*[\$€£¥₹]?)', price)
        if match:
            return match.group(1).strip()

        return price if any(c.isdigit() for c in price) else None

    def _extract_numeric_price(self, price: str) -> Optional[float]:
        """Extract numeric value from price string."""
        if not price:
            return None

        # Remove currency symbols and whitespace
        cleaned = re.sub(r'[^\d.,]', '', price)

        # Handle European format (1.234,56 → 1234.56)
        if ',' in cleaned and '.' in cleaned:
            if cleaned.index(',') > cleaned.index('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            # Could be thousands separator or decimal
            parts = cleaned.split(',')
            if len(parts[-1]) == 2:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')

        try:
            return round(float(cleaned), 2)
        except (ValueError, TypeError):
            return None

    def _clean_availability(self, availability: str) -> str:
        """Normalize availability status."""
        if not availability:
            return "Unknown"

        text = availability.lower().strip()
        if any(kw in text for kw in ["in stock", "available", "in-stock"]):
            return "In Stock"
        elif any(kw in text for kw in ["out of stock", "sold out", "unavailable", "out-of-stock"]):
            return "Out of Stock"
        elif any(kw in text for kw in ["pre-order", "preorder", "coming soon"]):
            return "Pre-Order"
        elif any(kw in text for kw in ["limited", "few left", "low stock"]):
            return "Limited Stock"
        return "Unknown"

    def _clean_url(self, url: Optional[str]) -> Optional[str]:
        """Clean and validate a URL."""
        if not url:
            return None

        url = url.strip()

        # Remove tracking parameters (basic)
        url = re.sub(r'[&?](utm_[^&]*|ref=[^&]*|tag=[^&]*)', '', url)

        # Validate basic URL structure
        if url.startswith(("http://", "https://", "//")):
            if url.startswith("//"):
                url = "https:" + url
            return url

        return None

    def _deduplicate(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate products based on name + price combination."""
        seen = set()
        unique = []

        for product in products:
            # Create a deduplication key
            key = (
                product.get("name", "").lower().strip(),
                product.get("price", ""),
            )
            if key not in seen:
                seen.add(key)
                unique.append(product)

        return unique
