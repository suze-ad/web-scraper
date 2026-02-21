"""
Production Logging Module.
Supports colored console output, file logging, and structured JSON logging.
Uses Rich for beautiful console output when available.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False

try:
    from rich.logging import RichHandler
    from rich.console import Console
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for log aggregation systems."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # Include extra fields
        for key in ("url", "page", "products", "duration", "job_id"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


def setup_logger(
    name: str = "scraper_agent",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    json_logs: bool = False,
) -> logging.Logger:
    """
    Set up production-ready logger.

    Args:
        name: Logger name
        level: Logging level
        log_file: Optional path to log file
        json_logs: Enable structured JSON logging

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on re-init
    if logger.handlers:
        logger.handlers.clear()

    logger.setLevel(level)
    logger.propagate = False

    # ── Console Handler ──────────────────────────────────────────────
    if json_logs:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(JSONFormatter())
    elif HAS_RICH:
        console_handler = RichHandler(
            level=level,
            console=Console(stderr=True),
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=level == logging.DEBUG,
        )
    elif HAS_COLORLOG:
        console_formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s [%(levelname)-8s]%(reset)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)

    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # ── File Handler ─────────────────────────────────────────────────
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if json_logs:
            file_formatter = JSONFormatter()
        else:
            file_formatter = logging.Formatter(
                "%(asctime)s [%(levelname)-8s] %(name)s.%(funcName)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    return logger
