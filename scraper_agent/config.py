"""
Configuration for the scraping agent.
Supports environment variables and .env. Simplified for OpenAI-first flow.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(key: str, default=None, cast=None):
    val = os.environ.get(key, default)
    if val is None:
        return default
    if cast is not None and val is not default:
        try:
            return cast(val)
        except (ValueError, TypeError):
            return default
    return val


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


@dataclass
class RateLimitConfig:
    min_delay: float = _env("SCRAPER_MIN_DELAY", 1.0, float)
    max_delay: float = _env("SCRAPER_MAX_DELAY", 3.0, float)
    max_retries: int = _env("SCRAPER_MAX_RETRIES", 3, int)


@dataclass
class ScraperConfig:
    """Scraper configuration. OpenAI is used for extraction when api_key is set."""

    # Request
    timeout: int = _env("SCRAPER_TIMEOUT", 30, int)
    max_pages: int = _env("SCRAPER_MAX_PAGES", 50, int)
    user_agent: Optional[str] = _env("SCRAPER_USER_AGENT", None)
    respect_robots_txt: bool = _env_bool("SCRAPER_RESPECT_ROBOTS", True)

    # OpenAI (product extraction and analysis)
    openai_api_key: Optional[str] = _env("OPENAI_API_KEY", None)
    use_openai: bool = _env_bool("SCRAPER_USE_OPENAI", True)  # use OpenAI when key is set
    openai_model: str = _env("SCRAPER_OPENAI_MODEL", "gpt-4o-mini")

    # Browser (dynamic sites)
    headless: bool = _env_bool("SCRAPER_HEADLESS", True)
    browser_type: str = _env("SCRAPER_BROWSER", "chromium")
    page_load_timeout: int = _env("SCRAPER_PAGE_TIMEOUT", 30000, int)
    dynamic_detection_timeout: int = _env("SCRAPER_DETECT_TIMEOUT", 5, int)

    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

    # Output
    output_dir: str = _env("SCRAPER_OUTPUT_DIR", "output")
    csv_filename: str = _env("SCRAPER_CSV_FILENAME", "products.csv")

    # Logging
    log_level: str = _env("SCRAPER_LOG_LEVEL", "INFO")
    log_file: Optional[str] = _env("SCRAPER_LOG_FILE", "scraper.log")
    log_json: bool = _env_bool("SCRAPER_LOG_JSON", False)

    # Optional: rule-based fallback selectors (used when not using OpenAI)
    custom_selectors: Dict[str, Optional[str]] = field(default_factory=lambda: {
        "product_container": None,
        "product_name": None,
        "product_price": None,
        "product_url": None,
        "product_image": None,
        "availability": None,
        "next_page": None,
    })

    def get_log_level(self) -> int:
        return getattr(logging, self.log_level.upper(), logging.INFO)

    def validate(self) -> List[str]:
        warnings = []
        if self.use_openai and not self.openai_api_key:
            warnings.append("OPENAI_API_KEY not set; set it or use rule-based extraction (use_openai=False)")
        if self.timeout < 5:
            warnings.append("Timeout < 5s may cause failures")
        return warnings
