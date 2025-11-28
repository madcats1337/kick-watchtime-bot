"""
Centralized logging configuration for the application
Provides structured logging with proper formatting and levels
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
import os


def setup_logging(app_name='app', log_level=None, log_file=None):
    """
    Setup application logging with console and optional file handlers
    
    Args:
        app_name: Name of the application (used in log messages)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file (enables file logging)
    
    Returns:
        logging.Logger: Configured logger instance
    """
    
    # Determine log level from environment or parameter
    if log_level is None:
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Convert string to logging level
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # Create logger
    logger = logging.getLogger(app_name)
    logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='[%(asctime)s] %(levelname)-8s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        fmt='[%(asctime)s] %(levelname)-8s %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(simple_formatter)
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
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(detailed_formatter)
            logger.addHandler(file_handler)
            
            logger.info(f"File logging enabled: {log_file}")
        except Exception as e:
            logger.error(f"Failed to setup file logging: {e}")
    
    # Prevent propagation to root logger
    logger.propagate = False
    
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

def log_route_access(logger, route, method='GET', user_id=None, server_id=None):
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
if __name__ == '__main__':
    # Setup logging
    logger = setup_logging('test_app', 'DEBUG', 'logs/test.log')
    
    # Test different log levels
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")
    
    # Test convenience functions
    log_route_access(logger, '/dashboard', 'GET', user_id=123, server_id=456)
    log_api_call(logger, 'Discord API', '/users/@me', 200, 0.45)
    
    try:
        raise ValueError("Test error")
    except Exception as e:
        log_error(logger, e, "Test error context")
