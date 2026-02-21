"""
Brand profile analyzer using OpenAI.
Fetches a page, extracts deterministic color evidence, asks OpenAI for structured
profile fields, then validates/corrects weak output.
"""

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MAX_HTML_CHARS = 90_000
HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_RE = re.compile(r"rgba?\s*\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", re.I)
HSL_RE = re.compile(r"hsla?\s*\(\s*(\d+)\s*,\s*(\d+)%?\s*,\s*(\d+)%?", re.I)
CSS_VAR_COLOR_RE = re.compile(
    r"--(?:primary|brand|accent|main|theme|color)[^:]*:\s*(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|hsla?\([^)]+\))",
    re.I,
)
logger = logging.getLogger(__name__)

GENERIC_NEUTRALS = {
    "ffffff", "000000", "f5f5f5", "f8f8f8", "fafafa", "eeeeee", "e5e5e5",
    "dddddd", "cccccc", "f0f0f0", "e0e0e0", "d0d0d0", "333333", "111111",
    "222222", "444444", "555555", "666666", "777777", "888888", "999999",
    "aaaaaa", "bbbbbb",
}


def _trim_html(html: str, max_chars: int = MAX_HTML_CHARS) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    text = str(soup)
    return text[:max_chars] + "\n... [truncated]" if len(text) > max_chars else text


def _fetch_html(url: str, timeout: int = 30) -> str:
    """
    Fetch HTML with retries and hostname fallbacks.
    Handles flaky domains by trying both www and apex host forms.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.netloc
    scheme = parsed.scheme or "https"
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""

    candidates = [url]
    if host.startswith("www."):
        apex = host[4:]
        candidates.append(f"{scheme}://{apex}{path}{query}")
    else:
        candidates.append(f"{scheme}://www.{host}{path}{query}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    last_exc = None
    for candidate in candidates:
        try:
            # tuple timeout = (connect_timeout, read_timeout)
            resp = session.get(candidate, headers=headers, timeout=(12, timeout))
            resp.raise_for_status()
            if resp.encoding is None:
                resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.RequestException as exc:
            last_exc = exc
            continue

    if last_exc:
        raise last_exc
    raise requests.RequestException("Failed to fetch URL")


def _hex_normalize(raw: str) -> str:
    c = raw.lower().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    elif len(c) == 8:
        c = c[:6]
    elif len(c) != 6:
        return ""
    return "#" + c


def _rgb_to_hex(r, g, b) -> str:
    rr = max(0, min(255, int(r)))
    gg = max(0, min(255, int(g)))
    bb = max(0, min(255, int(b)))
    return "#{:02x}{:02x}{:02x}".format(rr, gg, bb)


def _hsl_to_hex(h, s, l) -> str:
    h = int(h) % 360
    s = max(0, min(100, int(s))) / 100.0
    l_val = max(0, min(100, int(l))) / 100.0
    c = (1 - abs(2 * l_val - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l_val - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return _rgb_to_hex(int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))


def _is_neutral(hex_color: str) -> bool:
    c = hex_color.lower().lstrip("#")
    if c in GENERIC_NEUTRALS:
        return True
    if len(c) != 6:
        return False
    r = int(c[0:2], 16)
    g = int(c[2:4], 16)
    b = int(c[4:6], 16)
    spread = max(r, g, b) - min(r, g, b)
    if spread < 15:
        return True
    return False


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    c = hex_color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _color_distance(a: str, b: str) -> float:
    r1, g1, b1 = _hex_to_rgb(a)
    r2, g2, b2 = _hex_to_rgb(b)
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


def _collect_colors_from_css(css_text: str, counts: Counter, weight: int = 1) -> None:
    """Parse HEX, RGB, and HSL colors from a CSS string into the counter."""
    for m in CSS_VAR_COLOR_RE.finditer(css_text):
        val = m.group(1).strip()
        if val.startswith("#"):
            normalized = _hex_normalize(val)
            if normalized:
                counts[normalized] += weight * 5
        elif val.lower().startswith("rgb"):
            rm = RGB_RE.search(val)
            if rm:
                counts[_rgb_to_hex(rm.group(1), rm.group(2), rm.group(3))] += weight * 5
        elif val.lower().startswith("hsl"):
            hm = HSL_RE.search(val)
            if hm:
                counts[_hsl_to_hex(hm.group(1), hm.group(2), hm.group(3))] += weight * 5

    for m in HEX_RE.finditer(css_text):
        normalized = _hex_normalize(m.group(1))
        if normalized:
            counts[normalized] += weight

    for m in RGB_RE.finditer(css_text):
        counts[_rgb_to_hex(m.group(1), m.group(2), m.group(3))] += weight

    for m in HSL_RE.finditer(css_text):
        counts[_hsl_to_hex(m.group(1), m.group(2), m.group(3))] += weight


def _pick_top_diverse(ranked: List[str], n: int = 3, min_dist: float = 60.0) -> List[str]:
    """Pick top N colors that are visually distinct from each other."""
    if len(ranked) <= n:
        return ranked[:n]
    selected: List[str] = [ranked[0]]
    for candidate in ranked[1:]:
        if len(selected) >= n:
            break
        if all(_color_distance(candidate, s) >= min_dist for s in selected):
            selected.append(candidate)
    # Backfill if we couldn't find enough diverse colors
    if len(selected) < n:
        for candidate in ranked:
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= n:
                break
    return selected[:n]


def _extract_brand_colors(html: str, base_url: str = "") -> List[str]:
    """
    Extract brand colors from all available sources:
    1. meta theme-color / msapplication-TileColor
    2. CSS custom properties (--primary, --brand, --accent, etc.)
    3. Inline style attributes
    4. <style> blocks
    5. Linked external stylesheets
    Returns exactly 3 diverse, non-neutral hex colors.
    """
    soup = BeautifulSoup(html, "lxml")
    counts: Counter = Counter()

    # Source 1: meta tags
    for meta_name in ["theme-color", "msapplication-TileColor"]:
        tag = soup.find("meta", attrs={"name": meta_name})
        if tag and tag.get("content"):
            val = tag["content"].strip()
            if val.startswith("#"):
                counts[_hex_normalize(val)] += 30
            elif val.lower().startswith("rgb"):
                rm = RGB_RE.search(val)
                if rm:
                    counts[_rgb_to_hex(rm.group(1), rm.group(2), rm.group(3))] += 30

    # Source 2 + 3 + 4: <style> blocks and inline styles
    css_sources: List[str] = []
    for st in soup.find_all("style"):
        if st.string:
            css_sources.append(st.string)
    for el in soup.find_all(style=True):
        css_sources.append(el.get("style", ""))

    for css in css_sources:
        _collect_colors_from_css(css, counts, weight=2)

    # Source 5: external stylesheets
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/css,*/*;q=0.1",
    }
    for link in soup.find_all("link", rel=lambda r: r and "stylesheet" in r):
        href = link.get("href")
        if not href:
            continue
        css_url = urljoin(base_url, href)
        try:
            r = requests.get(css_url, headers=headers, timeout=8)
            if r.ok:
                _collect_colors_from_css(r.text, counts, weight=1)
        except Exception:
            continue

    counts.pop("", None)

    ranked_all = [c for c, _ in counts.most_common(40)]
    non_neutral = [c for c in ranked_all if not _is_neutral(c)]

    if not ranked_all:
        return []

    # Build candidate pool: prefer non-neutrals, backfill from all
    if len(non_neutral) >= 3:
        result = _pick_top_diverse(non_neutral, 3)
    elif non_neutral:
        pool = list(non_neutral)
        for c in ranked_all:
            if c not in pool:
                pool.append(c)
        result = _pick_top_diverse(pool, 3)
    else:
        result = _pick_top_diverse(ranked_all, 3)

    # Pad to exactly 3 with dark-neutral fallbacks if site yielded fewer
    if len(result) < 3:
        dark_fill = ["#1a1a2e", "#16213e", "#0f3460"]
        for nf in dark_fill:
            if nf not in result and all(_color_distance(nf, s) >= 40 for s in result):
                result.append(nf)
            if len(result) >= 3:
                break

    return result[:3]


def _extract_evidence_text(html: str) -> Dict[str, Any]:
    """Get factual snippets (title/meta/headings/nav) to ground AI output."""
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(strip=True) if soup.title else "")[:180]
    meta = ""
    meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta_tag and meta_tag.get("content"):
        meta = meta_tag["content"].strip()[:400]

    headings = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        t = h.get_text(" ", strip=True)
        if t and len(t) < 120 and t not in headings:
            headings.append(t)
    headings = headings[:20]

    nav_items = []
    for nav in soup.find_all(["nav", "header"])[:2]:
        for a in nav.find_all("a"):
            t = a.get_text(" ", strip=True)
            if 1 < len(t) < 40 and t.lower() not in {"home", "about", "contact", "blog", "login", "sign in"}:
                nav_items.append(t)
    nav_items = list(dict.fromkeys(nav_items))[:20]

    return {"title": title, "meta_description": meta, "headings": headings, "nav_items": nav_items}


def _default_profile(url: str, error: str = "Analysis failed") -> Dict[str, Any]:
    p = urlparse(url)
    return {
        "website_url": url,
        "domain": p.netloc or url,
        "title": "",
        "welcome_message": "",
        "role": "",
        "scope": "",
        "out_of_scope": "",
        "brand_colors": [],
        "brand_tone": [],
        "products_and_services": [],
        "target_audience": [],
        "brand_description": "",
        "knowledge_base": {"about": [], "faqs": [], "positioning": []},
        "error": error,
    }


def _lines_from_text(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[\n;•]+", text)
    return [p.strip("- ").strip() for p in parts if p.strip()]


def _is_too_generic(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    generic = [
        "welcome to our website",
        "we are here to help",
        "your trusted partner",
        "innovative solutions for your business",
    ]
    return any(g in t for g in generic)


def _post_validate(data: Dict[str, Any], evidence: Dict[str, Any], deterministic_colors: List[str], url: str) -> Dict[str, Any]:
    title = data.get("title") or evidence.get("title") or (urlparse(url).netloc or "our brand")
    brand_desc = (data.get("brand_description") or evidence.get("meta_description") or "").strip()

    # Force deterministic colors as source of truth; always exactly 3 when possible
    colors = deterministic_colors or (data.get("brand_colors") or [])
    if isinstance(colors, list):
        colors = [_hex_normalize(c) for c in colors if isinstance(c, str) and c.startswith("#")]
    data["brand_colors"] = colors[:3]

    # Welcome message
    wm = (data.get("welcome_message") or "").strip()
    if _is_too_generic(wm):
        if brand_desc:
            wm = f"Welcome to {title}. {brand_desc.split('.')[0].strip()}."
        else:
            wm = f"Welcome to {title}. We're here to help you quickly find what you need."
    data["welcome_message"] = wm

    # Role
    role = (data.get("role") or "").strip()
    if _is_too_generic(role):
        offerings = data.get("products_and_services") or []
        if offerings:
            role = f"{offerings[0]} assistant"
        else:
            role = "Brand support assistant"
    data["role"] = role

    # Scope / out_of_scope to minimum 3 lines each
    scope_lines = _lines_from_text(data.get("scope", ""))
    if len(scope_lines) < 3:
        seed = data.get("products_and_services") or evidence.get("nav_items") or []
        scope_lines = []
        for item in seed[:5]:
            scope_lines.append(f"Help with {item}")
        scope_lines.extend([
            "Answer questions about offerings",
            "Provide basic guidance and navigation",
        ])
    data["scope"] = "\n".join(list(dict.fromkeys(scope_lines))[:5])

    out_lines = _lines_from_text(data.get("out_of_scope", ""))
    if len(out_lines) < 3:
        out_lines = [
            "No legal, medical, or financial advice",
            "No account-specific actions without verification",
            "No commitments beyond published company policies",
        ]
    data["out_of_scope"] = "\n".join(list(dict.fromkeys(out_lines))[:5])

    # Clean arrays
    for key in ["brand_tone", "products_and_services", "target_audience"]:
        val = data.get(key) or []
        if isinstance(val, str):
            val = _lines_from_text(val)
        data[key] = [str(x).strip() for x in val if str(x).strip()][:10]

    # Knowledge base shape
    kb = data.get("knowledge_base") or {}
    data["knowledge_base"] = {
        "about": [str(x).strip() for x in (kb.get("about") or []) if str(x).strip()][:5],
        "faqs": [str(x).strip() for x in (kb.get("faqs") or []) if str(x).strip()][:12],
        "positioning": [str(x).strip() for x in (kb.get("positioning") or []) if str(x).strip()][:12],
    }
    if not data["knowledge_base"]["about"] and brand_desc:
        data["knowledge_base"]["about"] = [brand_desc]

    # Core identity
    data["title"] = title
    data["domain"] = data.get("domain") or (urlparse(url).netloc or url)
    data["website_url"] = data.get("website_url") or url
    data["brand_description"] = brand_desc
    data["error"] = None
    return data


def analyze_website(url: str, api_key: str = None, timeout: int = 15) -> Dict[str, Any]:
    """Fetch URL and use OpenAI to generate a high-quality, structured brand profile."""
    try:
        out = _analyze_website_inner(url, api_key=api_key, timeout=timeout)
        if out.get("error"):
            logger.info("analyze_website error for %s: %s", url[:80], out.get("error"))
        return out
    except Exception as exc:
        logger.warning("analyze_website exception for %s: %s", url[:80], exc)
        return _default_profile(url, f"Unexpected error: {exc}")


def _analyze_website_inner(url: str, api_key: str = None, timeout: int = 15) -> Dict[str, Any]:
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _default_profile(url, "OPENAI_API_KEY not set. Set it in the environment or pass api_key.")

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        html = _fetch_html(url, timeout=timeout)
    except requests.RequestException as e:
        return _default_profile(url, str(e))

    try:
        deterministic_colors = _extract_brand_colors(html, base_url=url)
    except Exception:
        deterministic_colors = []

    evidence = _extract_evidence_text(html)

    try:
        from openai import OpenAI
    except ImportError:
        return _default_profile(url, "Install openai: pip install openai")

    trimmed = _trim_html(html)
    system = """You are a strict website brand analyst.
Rules:
- Be factual and grounded in provided evidence.
- Do NOT invent claims, certifications, or audience segments.
- If uncertain, keep it concise and neutral.
- welcome_message and role must be specific to this site, not generic.
- scope and out_of_scope must each contain 3-5 concrete lines.

Return ONLY valid JSON with exact keys:
welcome_message, role, scope, out_of_scope, brand_colors, brand_tone,
products_and_services, target_audience, brand_description, knowledge_base, title, domain

knowledge_base must be object: {about:[], faqs:[], positioning:[]}."""

    user = f"""URL: {url}
Evidence:
- title: {evidence.get("title")}
- meta_description: {evidence.get("meta_description")}
- headings: {evidence.get("headings")}
- nav_items: {evidence.get("nav_items")}
- color_candidates (trust these most): {deterministic_colors}

HTML excerpt:
{trimmed}

Build the JSON profile now."""

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        content = (resp.choices[0].message.content or "").strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content)
        data = json.loads(content)
    except json.JSONDecodeError:
        return _default_profile(url, "Invalid JSON from OpenAI")
    except Exception as e:
        return _default_profile(url, str(e))

    if not isinstance(data, dict):
        return _default_profile(url, "Invalid response from OpenAI")

    def _to_str(val) -> str:
        if isinstance(val, list):
            return "\n".join(str(x) for x in val)
        return (str(val) if val else "").strip()

    normalized = {
        "website_url": url,
        "domain": data.get("domain") or (urlparse(url).netloc or url),
        "title": _to_str(data.get("title")),
        "welcome_message": _to_str(data.get("welcome_message")),
        "role": _to_str(data.get("role")),
        "scope": _to_str(data.get("scope")),
        "out_of_scope": _to_str(data.get("out_of_scope")),
        "brand_colors": data.get("brand_colors") or [],
        "brand_tone": data.get("brand_tone") or [],
        "products_and_services": data.get("products_and_services") or [],
        "target_audience": data.get("target_audience") or [],
        "brand_description": _to_str(data.get("brand_description")),
        "knowledge_base": data.get("knowledge_base") or {"about": [], "faqs": [], "positioning": []},
        "error": None,
    }
    return _post_validate(normalized, evidence, deterministic_colors, url)
