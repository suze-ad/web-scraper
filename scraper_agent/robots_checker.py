"""
Robots.txt compliance checker.
Ensures the agent respects website crawling rules.
"""

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Dict

logger = logging.getLogger("scraper_agent")


class RobotsChecker:
    """Checks robots.txt rules for a given website."""

    def __init__(self, user_agent: str = "*"):
        self.user_agent = user_agent
        self._parsers: Dict[str, RobotFileParser] = {}

    def _get_parser(self, url: str) -> RobotFileParser:
        """Get or create a RobotFileParser for the given URL's domain."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        if base_url not in self._parsers:
            robots_url = f"{base_url}/robots.txt"
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
                logger.info(f"Loaded robots.txt from {robots_url}")
            except Exception as e:
                logger.warning(f"Could not read robots.txt from {robots_url}: {e}")
                # If we can't read robots.txt, allow all by default
                parser = RobotFileParser()
                parser.allow_all = True

            self._parsers[base_url] = parser

        return self._parsers[base_url]

    def can_fetch(self, url: str) -> bool:
        """
        Check if the given URL can be fetched according to robots.txt rules.

        Args:
            url: The URL to check

        Returns:
            True if fetching is allowed, False otherwise
        """
        try:
            parser = self._get_parser(url)
            allowed = parser.can_fetch(self.user_agent, url)
            if not allowed:
                logger.warning(f"robots.txt disallows fetching: {url}")
            return allowed
        except Exception as e:
            logger.warning(f"Error checking robots.txt for {url}: {e}")
            return True  # Allow on error to not block legitimate scraping

    def get_crawl_delay(self, url: str) -> float:
        """
        Get the crawl delay specified in robots.txt.

        Args:
            url: The URL to check

        Returns:
            Crawl delay in seconds, or 0 if not specified
        """
        try:
            parser = self._get_parser(url)
            delay = parser.crawl_delay(self.user_agent)
            return float(delay) if delay else 0.0
        except Exception:
            return 0.0
