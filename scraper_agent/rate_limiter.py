"""
Rate Limiter module.
Implements adaptive rate limiting with exponential backoff.
"""

import logging
import random
import time
from scraper_agent.config import RateLimitConfig

logger = logging.getLogger("scraper_agent")


class RateLimiter:
    """Adaptive rate limiter that respects server load constraints."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._last_request_time: float = 0.0
        self._consecutive_errors: int = 0

    def wait(self) -> None:
        """Wait the appropriate amount of time before the next request."""
        now = time.time()
        elapsed = now - self._last_request_time

        # Calculate base delay
        base_delay = 1.0 / self.config.requests_per_second

        # Add jitter to appear more human-like
        delay = random.uniform(
            max(base_delay, self.config.min_delay),
            self.config.max_delay,
        )

        # Apply backoff if there have been consecutive errors
        if self._consecutive_errors > 0:
            backoff = self.config.backoff_factor ** self._consecutive_errors
            delay = min(delay * backoff, 60.0)  # Cap at 60 seconds
            logger.debug(
                f"Applying backoff (errors: {self._consecutive_errors}): "
                f"delay = {delay:.1f}s"
            )

        # Only wait if we haven't waited long enough since last request
        remaining = delay - elapsed
        if remaining > 0:
            logger.debug(f"Rate limiting: waiting {remaining:.1f}s")
            time.sleep(remaining)

        self._last_request_time = time.time()

    def report_success(self) -> None:
        """Report a successful request to reduce backoff."""
        self._consecutive_errors = max(0, self._consecutive_errors - 1)

    def report_error(self) -> None:
        """Report a failed request to increase backoff."""
        self._consecutive_errors += 1
        logger.warning(
            f"Consecutive errors: {self._consecutive_errors}/"
            f"{self.config.max_retries}"
        )

    @property
    def should_retry(self) -> bool:
        """Check if we should continue retrying."""
        return self._consecutive_errors < self.config.max_retries

    def reset(self) -> None:
        """Reset the rate limiter state."""
        self._consecutive_errors = 0
        self._last_request_time = 0.0
