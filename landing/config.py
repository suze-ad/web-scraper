"""
Production config for the brand profile landing server.
All settings can be overridden via environment variables.
"""

import os
from dataclasses import dataclass, field


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class LandingConfig:
    """Configuration for the landing Flask app and analyzer."""

    # Server
    host: str = field(default_factory=lambda: os.environ.get("LANDING_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("LANDING_PORT", 5000))
    debug: bool = field(default_factory=lambda: _env_bool("FLASK_DEBUG", False))
    env: str = field(default_factory=lambda: os.environ.get("FLASK_ENV", "production"))

    # Request validation
    max_url_length: int = field(default_factory=lambda: _env_int("LANDING_MAX_URL_LENGTH", 2048))
    request_timeout: int = field(default_factory=lambda: _env_int("LANDING_REQUEST_TIMEOUT", 60))

    # Rate limiting (simple in-memory: max requests per window per client)
    rate_limit_enabled: bool = field(default_factory=lambda: _env_bool("LANDING_RATE_LIMIT", True))
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("LANDING_RATE_LIMIT_PER_MINUTE", 10))

    # Security
    cors_origins: str = field(default_factory=lambda: os.environ.get("LANDING_CORS_ORIGINS", ""))
    block_private_ips: bool = field(default_factory=lambda: _env_bool("LANDING_BLOCK_PRIVATE_IPS", True))

    # Analyzer (passed to analyze_website)
    analyzer_timeout: int = field(default_factory=lambda: _env_int("LANDING_ANALYZER_TIMEOUT", 30))

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production" and not self.debug


def get_config() -> LandingConfig:
    return LandingConfig()
