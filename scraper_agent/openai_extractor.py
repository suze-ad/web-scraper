"""
OpenAI-powered extraction.
Sends page HTML to the model and gets structured product data (or brand profile).
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scraper_agent")

# Max chars to send per request (leave room for response)
MAX_HTML_CHARS = 90_000


def _trim_html(html: str, max_chars: int = MAX_HTML_CHARS) -> str:
    """Remove script/style and truncate to fit context."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    text = str(soup)
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

    system = """You are an expert at extracting product listing data from HTML.
Your task: from the HTML of a product listing page, extract every product/card/item.
For each product return: name, price (as shown, e.g. "$19.99"), availability ("In Stock" or "Out of Stock" or "Unknown"), product_url (link to product page), image_url (main product image).
If a field is missing, use null. Return ONLY a valid JSON array of objects, no markdown or explanation.
Example: [{"name":"Product A","price":"$10.99","availability":"In Stock","product_url":"https://...","image_url":"https://..."}]"""

    user = f"""Page URL: {page_url}

HTML (excerpt):
{trimmed}

Extract all products. Return a JSON array only."""

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
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

    system = """You are an expert at analyzing websites and summarizing brand identity.
From the HTML provided, extract and infer:

1. brand_colors: list of hex codes (e.g. ["#1a1a1a","#0066cc"]) that appear to be the main brand colors. Include theme-color if present. Max 10.
2. brand_tone: list of 2-5 tone descriptors, e.g. ["Professional", "Friendly", "Minimal"].
3. products_and_services: list of short phrases describing what they offer (e.g. "E-commerce", "SaaS platform", "Consulting").
4. target_audience: list of audience segments (e.g. "Businesses", "Developers", "B2B").
5. brand_description: one short paragraph summarizing the company/site (2-4 sentences).
6. knowledge_base: object with three arrays:
   - about: 1-3 sentences about the company/mission.
   - faqs: any FAQ questions (and answers if visible) as short strings.
   - positioning: key value props, taglines, or differentiators (short phrases).

Return ONLY valid JSON with these exact keys. No markdown, no explanation."""

    user = f"""URL: {url}

HTML (excerpt):
{trimmed}

Analyze and return the JSON object only."""

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
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
