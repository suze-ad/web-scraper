"""
Product Scraping Agent
A production-ready, modular web scraping framework for extracting
product listings from any e-commerce website.

Usage:
    from scraper_agent import ProductScrapingAgent, ScraperConfig

    agent = ProductScrapingAgent()
    df = agent.scrape("https://example.com/products", export_csv=True)
"""

__version__ = "2.0.0"
__author__ = "Scraper Agent"

from scraper_agent.agent import ProductScrapingAgent
from scraper_agent.config import ScraperConfig

__all__ = ["ProductScrapingAgent", "ScraperConfig"]
