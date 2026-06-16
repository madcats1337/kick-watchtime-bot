"""
Centralized logging configuration for the application
Provides structured logging with proper formatting and levels
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils.log_context import get_server


class ServerContextFilter(logging.Filter):
    """Stamp every log record with the active Discord server.

    Produces ``record.server_ctx`` like ``"[BOT] [Nick Cleveland Fam]"``. The
    server name is read from the per-context ``log_context`` ContextVar (set per
    request in the dashboard, per command/event/task in the bot). When no server
    is in context it falls back to ``"[<source_tag>] [-]"`` so columns stay aligned
    and the formatter can never raise ``KeyError``.
    """

    def __init__(self, source_tag=""):
        super().__init__()
        self.source_tag = (source_tag or "").strip()

    def filter(self, record):
        try:
            _server_id, server_name = get_server()
        except Exception:
            server_name = None
        prefix = f"[{self.source_tag}] " if self.source_tag else ""
        # Display the human-readable name; fall back to "-" when unknown.
        record.server_ctx = f"{prefix}[{server_name or '-'}]"
        return True


# Sentinel so we only install the root handler once per process even if
# setup_logging() is called multiple times.
_ROOT_HANDLER_INSTALLED = "_server_ctx_root_handler"

_RECORD_FACTORY_INSTALLED = False


def _install_record_factory():
    """Guarantee every LogRecord has a ``server_ctx`` attribute.

    The ServerContextFilter normally sets it, but a record could reach our
    formatter via a handler that lacks the filter. Setting a default on the
    record factory means the ``%(server_ctx)s`` formatter can never KeyError.
    """
    global _RECORD_FACTORY_INSTALLED
    if _RECORD_FACTORY_INSTALLED:
        return
    base_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base_factory(*args, **kwargs)
        if not hasattr(record, "server_ctx"):
            record.server_ctx = "[-]"
        return record

    logging.setLogRecordFactory(factory)
    _RECORD_FACTORY_INSTALLED = True


def setup_logging(app_name="app", log_level=None, log_file=None, source_tag=""):
    """
    Setup application logging with console and optional file handlers

    Args:
        app_name: Name of the application (used in log messages)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file (enables file logging)
        source_tag: Per-process tag prepended to every line ("BOT" / "DASH")

    Returns:
        logging.Logger: Configured logger instance
    """

    # Determine log level from environment or parameter
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Convert string to logging level
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Ensure every record carries server_ctx (defense in depth for the formatter).
    _install_record_factory()

    # Create logger
    logger = logging.getLogger(app_name)
    logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatters. %(server_ctx)s sits right after the level so the
    # "[SOURCE] [server]" tag auto-prepends to every message.
    detailed_formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s %(server_ctx)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    simple_formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s %(server_ctx)s %(message)s", datefmt="%H:%M:%S"
    )

    context_filter = ServerContextFilter(source_tag)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(simple_formatter)
    console_handler.addFilter(context_filter)
    logger.addHandler(console_handler)

    # File handler (if log_file specified)
    if log_file:
        try:
            # Create logs directory if it doesn't exist
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            # Rotating file handler (10MB max, keep 5 backups)
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10 MB
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(detailed_formatter)
            file_handler.addFilter(context_filter)
            logger.addHandler(file_handler)

            logger.info(f"File logging enabled: {log_file}")
        except Exception as e:
            logger.error(f"Failed to setup file logging: {e}")

    # Prevent propagation to root logger (this named logger has its own handlers)
    logger.propagate = False

    # Install a handler on the ROOT logger too, so module loggers created with
    # logging.getLogger(__name__) (which propagate to root and otherwise fall to
    # Python's lastResort handler) also get the server-context prefix. Guarded so
    # repeated setup_logging() calls don't stack duplicate handlers.
    root = logging.getLogger()
    if not getattr(root, _ROOT_HANDLER_INSTALLED, False):
        root.setLevel(numeric_level)
        root_handler = logging.StreamHandler(sys.stdout)
        root_handler.setLevel(numeric_level)
        root_handler.setFormatter(simple_formatter)
        root_handler.addFilter(context_filter)
        root.addHandler(root_handler)
        setattr(root, _ROOT_HANDLER_INSTALLED, True)

    return logger


def get_logger(name):
    """
    Get a logger instance by name

    Args:
        name: Logger name (typically module name)

    Returns:
        logging.Logger: Logger instance
    """
    return logging.getLogger(name)


# Convenience functions for common logging patterns


def log_route_access(logger, route, method="GET", user_id=None, server_id=None):
    """Log route access with context"""
    context = []
    if user_id:
        context.append(f"user={user_id}")
    if server_id:
        context.append(f"server={server_id}")

    context_str = f" [{', '.join(context)}]" if context else ""
    logger.info(f"{method} {route}{context_str}")


def log_db_query(logger, query, params=None, execution_time=None):
    """Log database query execution"""
    msg = f"DB Query: {query[:100]}..."
    if execution_time:
        msg += f" ({execution_time:.3f}s)"
    logger.debug(msg)


def log_api_call(logger, api_name, endpoint, status_code=None, duration=None):
    """Log external API calls"""
    msg = f"API Call: {api_name} -> {endpoint}"
    if status_code:
        msg += f" [HTTP {status_code}]"
    if duration:
        msg += f" ({duration:.2f}s)"
    logger.info(msg)


def log_error(logger, error, context=None):
    """Log error with optional context"""
    if context:
        logger.error(f"{context}: {error}", exc_info=True)
    else:
        logger.error(str(error), exc_info=True)


# Example usage:
if __name__ == "__main__":
    # Setup logging
    logger = setup_logging("test_app", "DEBUG", "logs/test.log")

    # Test different log levels
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")

    # Test convenience functions
    log_route_access(logger, "/dashboard", "GET", user_id=123, server_id=456)
    log_api_call(logger, "Discord API", "/users/@me", 200, 0.45)

    try:
        raise ValueError("Test error")
    except Exception as e:
        log_error(logger, e, "Test error context")
