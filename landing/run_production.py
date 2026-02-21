#!/usr/bin/env python3
"""
Run the landing server with Gunicorn (production).
From project root:  cd landing && python run_production.py
Or:  cd landing && gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 server:app
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from config import get_config

config = get_config()
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
timeout = max(config.request_timeout, config.analyzer_timeout + 30)
bind = f"{config.host}:{config.port}"

os.chdir(os.path.dirname(os.path.abspath(__file__)))
cmd = [
    sys.executable, "-m", "gunicorn",
    "-w", str(workers),
    "-b", bind,
    "--timeout", str(timeout),
    "--access-logfile", "-",
    "--error-logfile", "-",
    "server:app",
]
subprocess.run(cmd)
