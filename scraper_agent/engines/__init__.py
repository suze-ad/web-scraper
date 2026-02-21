"""Scraping engine modules."""

from scraper_agent.engines.base import BaseScraper
from scraper_agent.engines.static_scraper import StaticScraper
from scraper_agent.engines.dynamic_scraper import DynamicScraper

__all__ = ["BaseScraper", "StaticScraper", "DynamicScraper"]
