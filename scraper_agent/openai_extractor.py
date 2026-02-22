"""
OpenAI-powered extraction.
Sends page HTML to the model and gets structured product data (or brand profile).
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scraper_agent")

# Max chars to send (smaller = faster API, fewer tokens)
MAX_HTML_CHARS = 42_000

# Fast strip of script/style/noscript without full HTML parse
_SCRIPT_STYLE_RE = re.compile(
    r"<(?:script|style|noscript)[^>]*>.*?</(?:script|style|noscript)>",
    re.DOTALL | re.IGNORECASE,
)


def _trim_html(html: str, max_chars: int = MAX_HTML_CHARS) -> str:
    """Remove script/style/noscript via regex and truncate. No BeautifulSoup."""
    text = _SCRIPT_STYLE_RE.sub("", html)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def extract_products_with_openai(
    html: str,
    page_url: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> List[Dict[str, Any]]:
    """
    Send page HTML to OpenAI and return a list of product dicts.

    Each product has: name, price, availability, product_url, image_url.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Install openai: pip install openai")

    trimmed = _trim_html(html)

    system = """Extract product listing data from HTML. For each product return: name, price (e.g. "$19.99"), availability ("In Stock"/"Out of Stock"/"Unknown"), product_url, image_url. Use null if missing. Return ONLY a JSON array, no markdown. Example: [{"name":"Product A","price":"$10.99","availability":"In Stock","product_url":"https://...","image_url":"https://..."}]"""

    user = f"URL: {page_url}\n\nHTML:\n{trimmed}\n\nExtract all products. JSON array only."

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        timeout=45.0,
    )
    content = (resp.choices[0].message.content or "").strip()

    # Parse JSON (handle optional markdown code block)
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```\s*$", "", content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"OpenAI returned invalid JSON: {e}")
        return []

    if not isinstance(data, list):
        return []

    products = []
    for item in data:
        if not isinstance(item, dict):
            continue
        products.append({
            "name": item.get("name") or "",
            "price": item.get("price"),
            "price_numeric": None,  # filled by data_cleaner
            "availability": (item.get("availability") or "Unknown").strip()[:50],
            "product_url": item.get("product_url"),
            "image_url": item.get("image_url"),
            "source_url": page_url,
        })
    return products


def analyze_brand_with_openai(
    html: str,
    url: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    """
    Send page HTML to OpenAI and return a structured brand profile.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Install openai: pip install openai")

    trimmed = _trim_html(html)

    system = """From HTML extract: brand_colors (hex codes, max 10), brand_tone (2-5 words), products_and_services (short phrases), target_audience (segments), brand_description (short paragraph), knowledge_base: {about: [], faqs: [], positioning: []}. Return only valid JSON with these keys, no markdown."""

    user = f"URL: {url}\n\nHTML:\n{trimmed}\n\nAnalyze and return JSON only."

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        timeout=45.0,
    )
    content = (resp.choices[0].message.content or "").strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```\s*$", "", content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"OpenAI brand analysis invalid JSON: {e}")
        return _default_brand_profile(url)

    if not isinstance(data, dict):
        return _default_brand_profile(url)

    # Normalize to our expected shape
    return {
        "website_url": url,
        "domain": data.get("domain") or (url.split("/")[2] if "/" in url else url),
        "title": data.get("title", ""),
        "brand_colors": data.get("brand_colors") or [],
        "brand_tone": data.get("brand_tone") or [],
        "products_and_services": data.get("products_and_services") or [],
        "target_audience": data.get("target_audience") or [],
        "brand_description": data.get("brand_description") or "",
        "knowledge_base": data.get("knowledge_base") or {"about": [], "faqs": [], "positioning": []},
        "error": None,
    }


def _default_brand_profile(url: str) -> Dict[str, Any]:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return {
        "website_url": url,
        "domain": parsed.netloc or url,
        "title": "",
        "brand_colors": [],
        "brand_tone": [],
        "products_and_services": [],
        "target_audience": [],
        "brand_description": "",
        "knowledge_base": {"about": [], "faqs": [], "positioning": []},
        "error": "Analysis failed",
    }
