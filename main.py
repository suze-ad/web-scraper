#!/usr/bin/env python3
"""
Product Scraping Agent — OpenAI-powered CLI.

Usage:
  python main.py <URL> --csv
  python main.py <URL> --no-openai   # rule-based extraction (no API key needed)
  Set OPENAI_API_KEY for AI extraction (default).
"""

import argparse
import os
import sys

from scraper_agent.config import ScraperConfig, RateLimitConfig
from scraper_agent.agent import ProductScrapingAgent

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False


def parse_args():
    p = argparse.ArgumentParser(
        description="Product Scraping Agent (OpenAI-powered)",
        epilog='Examples: %(prog)s "http://books.toscrape.com" --csv',
    )
    p.add_argument("url", help="Website URL to scrape")
    p.add_argument("--engine", choices=["auto", "static", "dynamic"], default="auto")
    p.add_argument("--max-pages", type=int, default=50)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--no-robots", action="store_true")
    p.add_argument("--csv", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--no-openai", action="store_true", help="Use rule-based extraction (no OpenAI)")
    p.add_argument("--openai-key", type=str, default=os.environ.get("OPENAI_API_KEY"), help="OpenAI API key (default: OPENAI_API_KEY)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def build_config(args):
    return ScraperConfig(
        timeout=args.timeout,
        max_pages=args.max_pages,
        respect_robots_txt=not args.no_robots,
        rate_limit=RateLimitConfig(min_delay=args.delay),
        output_dir=args.output_dir,
        log_level=args.log_level,
        use_openai=not args.no_openai,
        openai_api_key=args.openai_key,
    )


def main():
    args = parse_args()
    if HAS_RICH:
        console.print(Panel.fit("[bold cyan]Product Scraping Agent[/bold cyan]\n[dim]OpenAI-powered[/dim]", border_style="cyan"))
    else:
        print("Product Scraping Agent — OpenAI-powered")

    config = build_config(args)
    if config.use_openai and not config.openai_api_key:
        print("Warning: OPENAI_API_KEY not set. Use --no-openai for rule-based extraction or set the key.")
        sys.exit(1)

    agent = ProductScrapingAgent(config=config)
    try:
        df = agent.scrape(
            url=args.url,
            export_csv=args.csv,
            export_json=args.json,
            force_engine=None if args.engine == "auto" else args.engine,
        )
        if df.empty:
            print("No products found. Try --engine dynamic or --no-openai")
            sys.exit(1)
        if HAS_RICH:
            t = Table(title="Products")
            t.add_column("Name", style="cyan", max_width=40)
            t.add_column("Price", style="green")
            t.add_column("Availability", style="yellow")
            for _, row in df.head(10).iterrows():
                t.add_row(str(row.get("name", ""))[:40], str(row.get("price", "")), str(row.get("availability", "")))
            console.print(t)
        else:
            print(df[["name", "price", "availability"]].head(10).to_string())
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
