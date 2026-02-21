"""
Pagination Handler.
Automatically detects and follows pagination links across product listing pages.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup

logger = logging.getLogger("scraper_agent")


class PaginationHandler:
    """Detects and handles pagination for multi-page product listings."""

    # Common "next page" link text patterns
    NEXT_PAGE_TEXT = [
        "next", "next page", "next →", "next »", "→", "»", "›",
        ">>", "load more", "show more", "view more",
    ]

    # Common pagination CSS selector patterns
    PAGINATION_SELECTORS = [
        "a.next", "a.next-page",
        "li.next a", "li.next-page a",
        ".pagination a.next",
        ".pagination .next a",
        ".pager .next a",
        "a[rel='next']",
        "link[rel='next']",
        "[aria-label='Next']",
        "[aria-label='Next page']",
        "a[data-testid='next-page']",
        "button.next",
        ".pagination-next a",
        "nav[aria-label='pagination'] a:last-child",
        ".s-pagination-next",       # Amazon
        ".a-last a",                # Amazon
    ]

    def __init__(self, base_url: str, max_pages: int = 50, custom_next_selector: Optional[str] = None):
        self.base_url = base_url
        self.max_pages = max_pages
        self.custom_next_selector = custom_next_selector
        self.visited_urls: set = set()
        self.current_page: int = 0

    def get_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """
        Find the URL for the next page of results.

        Args:
            soup: Parsed HTML of the current page
            current_url: URL of the current page

        Returns:
            URL of the next page, or None if no more pages
        """
        self.visited_urls.add(current_url)
        self.current_page += 1

        if self.current_page >= self.max_pages:
            logger.info(f"Reached maximum page limit ({self.max_pages})")
            return None

        # Strategy 1: Custom selector
        if self.custom_next_selector:
            url = self._find_by_selector(soup, self.custom_next_selector, current_url)
            if url:
                return url

        # Strategy 2: Standard pagination selectors
        url = self._find_by_standard_selectors(soup, current_url)
        if url:
            return url

        # Strategy 3: Text-based search
        url = self._find_by_text(soup, current_url)
        if url:
            return url

        # Strategy 4: URL pattern detection (page=N, /page/N, p=N, etc.)
        url = self._find_by_url_pattern(current_url)
        if url:
            return url

        logger.info("No more pages found")
        return None

    def _find_by_selector(
        self, soup: BeautifulSoup, selector: str, current_url: str
    ) -> Optional[str]:
        """Find next page link using a CSS selector."""
        try:
            element = soup.select_one(selector)
            if element:
                href = element.get("href")
                if href:
                    url = urljoin(current_url, href)
                    if url not in self.visited_urls:
                        logger.debug(f"Found next page via selector '{selector}': {url}")
                        return url
        except Exception:
            pass
        return None

    def _find_by_standard_selectors(
        self, soup: BeautifulSoup, current_url: str
    ) -> Optional[str]:
        """Try all standard pagination selectors."""
        for selector in self.PAGINATION_SELECTORS:
            url = self._find_by_selector(soup, selector, current_url)
            if url:
                return url
        return None

    def _find_by_text(
        self, soup: BeautifulSoup, current_url: str
    ) -> Optional[str]:
        """Find next page link by matching link text."""
        for text_pattern in self.NEXT_PAGE_TEXT:
            # Find links with matching text
            links = soup.find_all("a", href=True)
            for link in links:
                link_text = link.get_text(strip=True).lower()
                if link_text == text_pattern or link_text.startswith(text_pattern):
                    href = link.get("href")
                    if href and href != "#":
                        url = urljoin(current_url, href)
                        if url not in self.visited_urls:
                            logger.debug(
                                f"Found next page via text '{text_pattern}': {url}"
                            )
                            return url

            # Also check aria-label
            links_aria = soup.find_all(
                "a",
                attrs={"aria-label": lambda x: x and text_pattern in x.lower()},
                href=True,
            )
            for link in links_aria:
                href = link.get("href")
                if href and href != "#":
                    url = urljoin(current_url, href)
                    if url not in self.visited_urls:
                        logger.debug(f"Found next page via aria-label: {url}")
                        return url

        return None

    def _find_by_url_pattern(self, current_url: str) -> Optional[str]:
        """
        Detect pagination from URL patterns and generate the next page URL.
        Handles: ?page=2, ?p=2, /page/2/, ?start=24, ?offset=24, etc.
        """
        parsed = urlparse(current_url)
        params = parse_qs(parsed.query)

        # Common page parameter names
        page_params = ["page", "p", "pg", "pagenum", "page_num", "pagenumber"]

        for param in page_params:
            if param in params:
                try:
                    current_page_num = int(params[param][0])
                    params[param] = [str(current_page_num + 1)]
                    new_query = urlencode(params, doseq=True)
                    new_url = urlunparse(parsed._replace(query=new_query))
                    if new_url not in self.visited_urls:
                        logger.debug(f"Generated next page via URL pattern ({param}): {new_url}")
                        return new_url
                except (ValueError, IndexError):
                    continue

        # Check for path-based pagination: /page/2/
        path_match = re.search(r"/page/(\d+)", parsed.path)
        if path_match:
            current_page_num = int(path_match.group(1))
            new_path = parsed.path.replace(
                f"/page/{current_page_num}",
                f"/page/{current_page_num + 1}",
            )
            new_url = urlunparse(parsed._replace(path=new_path))
            if new_url not in self.visited_urls:
                logger.debug(f"Generated next page via path pattern: {new_url}")
                return new_url

        # Handle offset-based pagination
        offset_params = ["start", "offset", "from", "begin"]
        for param in offset_params:
            if param in params:
                try:
                    current_offset = int(params[param][0])
                    # Try common page sizes
                    for page_size in [24, 20, 12, 10, 48, 36, 25, 50]:
                        params[param] = [str(current_offset + page_size)]
                        new_query = urlencode(params, doseq=True)
                        new_url = urlunparse(parsed._replace(query=new_query))
                        if new_url not in self.visited_urls:
                            logger.debug(
                                f"Generated next page via offset ({param}+{page_size}): {new_url}"
                            )
                            return new_url
                except (ValueError, IndexError):
                    continue

        return None

    def get_all_page_urls(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """
        Get all available page URLs from a pagination bar.
        Useful for parallel scraping.

        Args:
            soup: Parsed HTML
            current_url: Current page URL

        Returns:
            List of all detected page URLs
        """
        page_urls = []

        # Find pagination container
        pagination_selectors = [
            ".pagination", ".pager", ".page-numbers",
            "nav[aria-label*='pagination']", ".paginator",
            "[class*='pagination']",
        ]

        for selector in pagination_selectors:
            pagination = soup.select_one(selector)
            if pagination:
                links = pagination.find_all("a", href=True)
                for link in links:
                    href = link.get("href")
                    if href and href != "#":
                        url = urljoin(current_url, href)
                        if url not in self.visited_urls and url not in page_urls:
                            page_urls.append(url)
                if page_urls:
                    logger.info(f"Found {len(page_urls)} page URLs in pagination bar")
                    break

        return page_urls

    def reset(self) -> None:
        """Reset the pagination handler state."""
        self.visited_urls.clear()
        self.current_page = 0
