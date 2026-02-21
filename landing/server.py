"""
Landing page server — production-ready.
Serves the single-page app and /api/analyze for website profile.
"""

import logging
import os
import time
from collections import defaultdict
from threading import Lock

from flask import Flask, request, jsonify, send_from_directory

from analyzer import analyze_website
from config import get_config
from validation import is_valid_analyze_url

# Load .env from project root if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__, static_folder="static", static_url_path="")
LANDING_ROOT = os.path.dirname(os.path.abspath(__file__))
config = get_config()

# Logging
log_level = logging.DEBUG if config.debug else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("landing")

# Simple in-memory rate limit: (ip -> list of request timestamps)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = Lock()
RATE_WINDOW_SEC = 60


def _rate_limit_exceeded(ip: str) -> bool:
    if not config.rate_limit_enabled:
        return False
    now = time.monotonic()
    with _rate_limit_lock:
        times = _rate_limit_store[ip]
        # Drop timestamps outside window
        times[:] = [t for t in times if now - t < RATE_WINDOW_SEC]
        if len(times) >= config.rate_limit_per_minute:
            return True
        times.append(now)
    return False


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if config.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if config.cors_origins:
        origin = request.headers.get("Origin", "")
        if origin and origin in [o.strip() for o in config.cors_origins.split(",") if o.strip()]:
            response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/analyze", methods=["OPTIONS"])
def analyze_options():
    return "", 204


@app.route("/")
def index():
    return send_from_directory(LANDING_ROOT, "index.html")


@app.route("/health")
def health():
    """Liveness: is the process up."""
    return jsonify({"status": "ok"}), 200


@app.route("/ready")
def ready():
    """Readiness: can serve traffic (e.g. OpenAI key present for analyze)."""
    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    return jsonify({"status": "ready", "openai_configured": has_key}), 200


@app.route("/api/analyze", methods=["POST"])
def analyze():
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown"
    if _rate_limit_exceeded(client_ip):
        logger.warning("Rate limit exceeded for %s", client_ip)
        return jsonify({"error": "Too many requests. Please try again later."}), 429

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    ok, err = is_valid_analyze_url(
        url,
        max_length=config.max_url_length,
        block_private=config.block_private_ips,
    )
    if not ok:
        return jsonify({"error": err}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info("Analyzing url=%s client=%s", url[:80], client_ip)
    try:
        result = analyze_website(url, timeout=config.analyzer_timeout)
    except Exception as e:
        logger.exception("Analyze failed for %s: %s", url[:80], e)
        return jsonify({"error": "Analysis failed. Please try again."}), 500

    if result.get("error"):
        logger.info("Analysis returned error for %s: %s", url[:80], result.get("error"))
        return jsonify(result), 422

    logger.info("Analysis success for %s", url[:80])
    return jsonify(result)


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def method_not_allowed(_e):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(_e):
    logger.exception("Unhandled error")
    return jsonify({"error": "An unexpected error occurred"}), 500


if __name__ == "__main__":
    logger.info("Starting server %s:%s debug=%s", config.host, config.port, config.debug)
    app.run(host=config.host, port=config.port, debug=config.debug, threaded=True)
