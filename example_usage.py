#!/usr/bin/env python3
"""
Example Usage - Product Scraping Agent

Demonstrates how to use the scraping agent programmatically.
"""

from scraper_agent.config import ScraperConfig, RateLimitConfig
from scraper_agent.agent import ProductScrapingAgent


def example_basic():
    """Basic usage — auto-detect everything, just provide a URL."""
    agent = ProductScrapingAgent()
    df = agent.scrape("https://books.toscrape.com", export_csv=True)
    print(df.head())
    return df


def example_custom_config():
    """Custom configuration for more control."""
    config = ScraperConfig(
        max_pages=5,
        timeout=20,
        headless=True,
        respect_robots_txt=True,
        rate_limit=RateLimitConfig(
            min_delay=1.5,
            max_delay=3.0,
            max_retries=3,
        ),
        output_dir="output",
        csv_filename="custom_products.csv",
        log_level="INFO",
    )

    agent = ProductScrapingAgent(config=config)
    df = agent.scrape(
        "https://books.toscrape.com",
        export_csv=True,
        export_json=True,
    )
    return df


def example_custom_selectors():
    """Using custom CSS selectors for a specific website."""
    config = ScraperConfig(
        max_pages=3,
        custom_selectors={
            "product_container": "article.product_pod",
            "product_name": "h3 a",
            "product_price": ".price_color",
            "product_url": "h3 a",
            "product_image": ".thumbnail img",
            "availability": ".availability",
            "next_page": "li.next a",
        },
    )

    agent = ProductScrapingAgent(config=config)
    df = agent.scrape("https://books.toscrape.com", export_csv=True)
    return df


def example_force_engine():
    """Force a specific scraping engine."""
    agent = ProductScrapingAgent()

    # Force static engine (Requests + BeautifulSoup)
    df_static = agent.scrape(
        "https://books.toscrape.com",
        force_engine="static",
    )

    # Force dynamic engine (Playwright/Selenium) for JS-heavy sites
    # df_dynamic = agent.scrape(
    #     "https://www.example-spa.com/products",
    #     force_engine="dynamic",
    # )

    return df_static


def example_with_context_manager():
    """Using the agent as a context manager for automatic cleanup."""
    config = ScraperConfig(max_pages=2)

    with ProductScrapingAgent(config=config) as agent:
        df = agent.scrape("https://books.toscrape.com", export_csv=True)
        print(f"Scraped {len(df)} products")
        return df


if __name__ == "__main__":
    print("=" * 60)
    print("  Running Basic Example")
    print("=" * 60)
    df = example_basic()

    if not df.empty:
        print(f"\nSuccessfully scraped {len(df)} products!")
        print(f"Columns: {list(df.columns)}")
        print(f"\nFirst 3 products:")
        print(df[["name", "price", "availability"]].head(3).to_string())
