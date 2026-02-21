"""
Custom Exception Hierarchy for the Scraping Agent.
Provides granular error handling for production reliability.
"""


class ScraperAgentError(Exception):
    """Base exception for all scraper agent errors."""

    def __init__(self, message: str = "", url: str = "", details: str = ""):
        self.url = url
        self.details = details
        full_msg = message
        if url:
            full_msg += f" [URL: {url}]"
        if details:
            full_msg += f" — {details}"
        super().__init__(full_msg)


# ── Network & HTTP Errors ────────────────────────────────────────────────

class FetchError(ScraperAgentError):
    """Failed to fetch a page."""
    pass


class TimeoutError(FetchError):
    """Request timed out."""
    pass


class HTTPError(FetchError):
    """HTTP status code error (4xx, 5xx)."""

    def __init__(self, status_code: int, **kwargs):
        self.status_code = status_code
        super().__init__(message=f"HTTP {status_code}", **kwargs)


class RateLimitedError(HTTPError):
    """Server returned 429 Too Many Requests."""

    def __init__(self, retry_after: float = 0, **kwargs):
        self.retry_after = retry_after
        super().__init__(status_code=429, **kwargs)


class BlockedError(FetchError):
    """Detected as bot / blocked by WAF / CAPTCHA."""
    pass


# ── Robots & Compliance Errors ───────────────────────────────────────────

class RobotsTxtError(ScraperAgentError):
    """robots.txt violation or read failure."""
    pass


class DisallowedByRobotsTxt(RobotsTxtError):
    """URL is disallowed by robots.txt rules."""
    pass


# ── Parsing & Extraction Errors ──────────────────────────────────────────

class ParsingError(ScraperAgentError):
    """Failed to parse HTML content."""
    pass


class NoProductsFoundError(ParsingError):
    """No product containers detected on the page."""
    pass


class ExtractionError(ParsingError):
    """Failed to extract a specific field from a product container."""
    pass


# ── Pagination Errors ────────────────────────────────────────────────────

class PaginationError(ScraperAgentError):
    """Error during pagination handling."""
    pass


# ── Engine Errors ────────────────────────────────────────────────────────

class EngineError(ScraperAgentError):
    """Scraper engine initialization or runtime error."""
    pass


class BrowserError(EngineError):
    """Browser-specific engine error (Playwright/Selenium)."""
    pass


class NoBrowserAvailableError(EngineError):
    """Neither Playwright nor Selenium is available."""
    pass


# ── Database Errors ──────────────────────────────────────────────────────

class DatabaseError(ScraperAgentError):
    """Database connection or query error."""
    pass


# ── Configuration Errors ─────────────────────────────────────────────────

class ConfigurationError(ScraperAgentError):
    """Invalid or missing configuration."""
    pass


# ── Circuit Breaker ──────────────────────────────────────────────────────

class CircuitBreakerOpenError(ScraperAgentError):
    """Circuit breaker is open — too many consecutive failures."""
    pass
