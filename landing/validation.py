"""
Request validation for the landing API.
Blocks invalid or dangerous URLs (SSRF, private IPs, etc.).
"""

import re
from typing import Tuple
from urllib.parse import urlparse


# Scheme must be http or https only
ALLOWED_SCHEMES = {"http", "https"}

# Hosts that must not be reachable (SSRF / internal)
BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}

# Private / reserved IP ranges (we block by hostname; for production you may resolve and check)
PRIVATE_HOST_PATTERNS = [
    re.compile(r"^10\.", re.I),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[0-1])\.", re.I),
    re.compile(r"^192\.168\.", re.I),
    re.compile(r"^127\.", re.I),
    re.compile(r"^0\.", re.I),
    re.compile(r"^localhost$", re.I),
]


def is_valid_analyze_url(url: str, max_length: int = 2048, block_private: bool = True) -> Tuple[bool, str]:
    """
    Validate URL for /api/analyze. Returns (ok, error_message).
    """
    if not url or not isinstance(url, str):
        return False, "URL is required"
    url = url.strip()
    if len(url) > max_length:
        return False, f"URL must be at most {max_length} characters"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, "Only http and https URLs are allowed"
    host = (parsed.netloc or "").split(":")[0].lower()
    if not host:
        return False, "Invalid host"
    if host in BLOCKED_HOSTS:
        return False, "This URL is not allowed"
    if block_private:
        for pat in PRIVATE_HOST_PATTERNS:
            if pat.match(host):
                return False, "Private or internal URLs are not allowed"
    return True, ""
