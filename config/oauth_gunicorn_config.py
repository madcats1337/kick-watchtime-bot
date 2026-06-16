"""
Gunicorn config for the OAuth web server (core.oauth_server:app).

Purpose: make our server-context logging the SINGLE authority over the root
logger inside each gunicorn worker. Gunicorn configures its own logging when a
worker boots, which can leave a second handler on the root logger — causing every
propagated app log line to print twice (once raw "INFO:core.oauth_server:msg",
once formatted "[BOT] [-] msg"). Re-asserting our handler in post_worker_init
runs AFTER gunicorn's logging setup, so we win.
"""

import os

# Keep gunicorn's own logger quiet; we don't need its per-request INFO chatter.
loglevel = "warning"


def post_worker_init(worker):
    """After gunicorn has configured logging in this worker, re-assert ours so the
    root logger ends up with exactly our single server-context handler."""
    try:
        from utils.logging_config import setup_logging

        setup_logging("kick_oauth", log_level=os.getenv("LOG_LEVEL", "INFO"), source_tag="BOT")
    except Exception:
        # Never let a logging-setup hiccup crash the worker.
        pass
