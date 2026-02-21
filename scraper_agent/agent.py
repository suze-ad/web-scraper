"""
Product Scraping Agent — OpenAI-powered.
Fetches pages, uses OpenAI to extract products (or rule-based fallback), paginates, outputs DataFrame/CSV.
"""

import logging
import re
import signal
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd

from scraper_agent.config import ScraperConfig
from scraper_agent.logger import setup_logger
from scraper_agent.detector import SiteDetector
from scraper_agent.robots_checker import RobotsChecker
from scraper_agent.rate_limiter import RateLimiter
from scraper_agent.pagination import PaginationHandler
from scraper_agent.parser import ProductParser
from scraper_agent.data_cleaner import DataCleaner
from scraper_agent.output_formatter import OutputFormatter
from scraper_agent.engines.static_scraper import StaticScraper
from scraper_agent.engines.dynamic_scraper import DynamicScraper
from scraper_agent.exceptions import ScraperAgentError

logger = logging.getLogger("scraper_agent")


class ProductScrapingAgent:
    """
    Scraping agent with OpenAI extraction.
    Set OPENAI_API_KEY and use_openai=True to have the model read the page and extract products.
    Otherwise uses rule-based parsing (selectors + ProductParser).
    """

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        for w in self.config.validate():
            logger.warning(f"Config: {w}")

        self.logger = setup_logger(
            level=self.config.get_log_level(),
            log_file=self.config.log_file,
            json_logs=self.config.log_json,
        )

        self.detector = SiteDetector(timeout=self.config.dynamic_detection_timeout)
        self.robots_checker = RobotsChecker()
        self.rate_limiter = RateLimiter(self.config.rate_limit)
        self.data_cleaner = DataCleaner()
        self.output_formatter = OutputFormatter(self.config.output_dir)

        self._scraper = None
        self._shutdown_requested = False
        self._original_sigint = None
        self._original_sigterm = None

    def scrape(
        self,
        url: str,
        export_csv: bool = False,
        export_json: bool = False,
        force_engine: Optional[str] = None,
    ) -> pd.DataFrame:
        """Scrape product listings; return DataFrame. Optionally export CSV/JSON."""
        job_id = str(uuid.uuid4())[:8]
        self._install_signal_handlers()

        try:
            self.logger.info("=" * 50)
            self.logger.info(f"  SCRAPING JOB [{job_id}]")
            self.logger.info("=" * 50)
            self.logger.info(f"URL: {url}")

            if not self._validate_url(url):
                self.logger.error(f"Invalid URL: {url}")
                return pd.DataFrame()

            if self.config.respect_robots_txt and not self.robots_checker.can_fetch(url):
                self.logger.error("robots.txt disallows this URL.")
                return pd.DataFrame()

            if self.config.respect_robots_txt:
                delay = self.robots_checker.get_crawl_delay(url)
                if delay > 0:
                    self.config.rate_limit.min_delay = max(self.config.rate_limit.min_delay, delay)

            site_type = force_engine or self.detector.detect(url)[0]
            self._init_scraper(site_type)

            all_products = self._scrape_all_pages(url)

            validated = self._validate_products(all_products, url)
            cleaned = self.data_cleaner.clean(validated)
            df = self.output_formatter.to_dataframe(cleaned)

            if export_csv and not df.empty:
                path = self.output_formatter.to_csv(df, self.config.csv_filename)
                self.logger.info(f"CSV: {path}")
            if export_json and not df.empty:
                path = self.output_formatter.to_json(df)
                self.logger.info(f"JSON: {path}")

            self.output_formatter.print_summary(df)
            return df

        except KeyboardInterrupt:
            self.logger.warning("Interrupted")
            return pd.DataFrame()
        except ScraperAgentError as e:
            self.logger.error(str(e))
            return pd.DataFrame()
        except Exception as e:
            self.logger.error(str(e), exc_info=True)
            return pd.DataFrame()
        finally:
            self._close_scraper()
            self._restore_signal_handlers()

    def _validate_url(self, url: str) -> bool:
        try:
            p = urlparse(url)
            return p.scheme in ("http", "https") and bool(p.netloc)
        except Exception:
            return False

    def _init_scraper(self, site_type: str) -> None:
        self._close_scraper()
        if site_type == "dynamic":
            try:
                self._scraper = DynamicScraper(self.config)
            except Exception as e:
                self.logger.warning(f"Dynamic engine failed: {e}, using static")
                self._scraper = StaticScraper(self.config)
        else:
            self._scraper = StaticScraper(self.config)

    def _close_scraper(self) -> None:
        if self._scraper:
            try:
                self._scraper.close()
            except Exception:
                pass
            self._scraper = None

    def _scrape_all_pages(self, start_url: str) -> List[Dict[str, Any]]:
        all_products: List[Dict[str, Any]] = []
        parsed = urlparse(start_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        use_openai = self.config.use_openai and bool(self.config.openai_api_key)
        if use_openai:
            from scraper_agent.openai_extractor import extract_products_with_openai

        parser = ProductParser(base_url=base_url, custom_selectors=self.config.custom_selectors)
        pagination = PaginationHandler(
            base_url=base_url,
            max_pages=self.config.max_pages,
            custom_next_selector=self.config.custom_selectors.get("next_page"),
        )

        current_url = start_url
        page_num = 0
        consecutive_empty = 0

        while current_url and not self._shutdown_requested:
            page_num += 1
            self.logger.info(f"Page {page_num}: {current_url}")

            self.rate_limiter.wait()
            html = self._scraper.fetch_page(current_url)

            if not html:
                self.rate_limiter.report_error()
                if self.rate_limiter.should_retry:
                    self.rate_limiter.wait()
                    html = self._scraper.fetch_page(current_url)
                if not html:
                    self.logger.error("Fetch failed, stopping")
                    break
            self.rate_limiter.report_success()

            if use_openai:
                try:
                    page_products = extract_products_with_openai(
                        html,
                        current_url,
                        api_key=self.config.openai_api_key,
                        model=self.config.openai_model,
                    )
                except Exception as e:
                    self.logger.warning(f"OpenAI extraction failed: {e}")
                    page_products = []
            else:
                soup = self._scraper.parse_html(html)
                containers = self._scraper.find_product_containers(soup)
                if not containers and page_num == 1:
                    containers = self._fallback_product_search(soup)
                if not containers:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        break
                    current_url = pagination.get_next_page_url(soup, current_url)
                    continue
                consecutive_empty = 0
                page_products = parser.parse_all(containers)
                for p in page_products:
                    p["source_url"] = current_url

            if not page_products:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0
                all_products.extend(page_products)

            soup = self._scraper.parse_html(html) if html else None
            if not soup:
                current_url = None
            elif self.config.respect_robots_txt and soup:
                next_url = pagination.get_next_page_url(soup, current_url)
                if next_url and not self.robots_checker.can_fetch(next_url):
                    break
                current_url = next_url
            elif soup:
                current_url = pagination.get_next_page_url(soup, current_url)
            else:
                current_url = None

        self.logger.info(f"Total: {len(all_products)} products from {page_num} page(s)")
        return all_products

    def _validate_products(
        self, products: List[Dict[str, Any]], source_url: str
    ) -> List[Dict[str, Any]]:
        validated = []
        for p in products:
            try:
                from scraper_agent.models import ProductData
                validated.append(ProductData(
                    name=p.get("name", ""),
                    price=p.get("price"),
                    price_numeric=p.get("price_numeric"),
                    availability=p.get("availability", "Unknown"),
                    product_url=p.get("product_url"),
                    image_url=p.get("image_url"),
                    source_url=p.get("source_url", source_url),
                ).model_dump())
            except Exception:
                validated.append(p)
        return validated

    def _fallback_product_search(self, soup) -> list:
        price_pattern = re.compile(r'[\$€£¥₹]\s*\d+|[\d,]+\.\d{2}')
        elements = soup.find_all(string=price_pattern)
        if not elements:
            return []
        first_grandparent = None
        for el in elements:
            parent = el.find_parent(["div", "li", "article", "section"])
            if parent:
                gp = parent.find_parent(["div", "li", "article", "section", "ul"])
                if gp:
                    first_grandparent = gp
                    break
        if not first_grandparent:
            return []
        children = list(first_grandparent.find_all(recursive=False))
        return children if len(children) >= 2 else []

    def _install_signal_handlers(self) -> None:
        try:
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_shutdown)
            if sys.platform != "win32":
                self._original_sigterm = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, self._handle_shutdown)
        except (OSError, ValueError):
            pass

    def _restore_signal_handlers(self) -> None:
        try:
            if self._original_sigint:
                signal.signal(signal.SIGINT, self._original_sigint)
            if getattr(self, "_original_sigterm", None) and sys.platform != "win32":
                signal.signal(signal.SIGTERM, self._original_sigterm)
        except (OSError, ValueError):
            pass

    def _handle_shutdown(self, signum, frame) -> None:
        self._shutdown_requested = True

    def close(self) -> None:
        self._close_scraper()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
