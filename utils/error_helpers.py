"""
Error handling helpers and decorators for Flask routes
Reduces repetitive try/except patterns and JSON error responses
"""

from functools import wraps
from flask import jsonify, g
import logging

logger = logging.getLogger(__name__)


def api_error_handler(func):
    """
    Decorator for API endpoints that automatically handles exceptions
    and returns proper JSON error responses
    
    Usage:
        @app.route('/api/data')
        @api_error_handler
        def get_data():
            # Your code here
            return jsonify({'success': True, 'data': data})
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            logger.warning(f"Validation error in {func.__name__}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 400
        except PermissionError as e:
            logger.warning(f"Permission denied in {func.__name__}: {e}")
            return jsonify({'success': False, 'error': 'Permission denied'}), 403
        except FileNotFoundError as e:
            logger.warning(f"Not found in {func.__name__}: {e}")
            return jsonify({'success': False, 'error': 'Resource not found'}), 404
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    return wrapper


def db_error_handler(func):
    """
    Decorator specifically for database operations
    Handles common database errors with proper logging
    
    Usage:
        @db_error_handler
        def save_user(user_data):
            # Database operations here
            return user_id
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Database error in {func.__name__}: {e}", exc_info=True)
            raise  # Re-raise for caller to handle
    return wrapper


def require_server_context(func):
    """
    Decorator that ensures g.server_id exists before executing route
    Returns 404 if subdomain not registered
    
    Usage:
        @app.route('/dashboard')
        @login_required
        @require_server_context
        def dashboard():
            # g.server_id is guaranteed to exist here
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not g.server_id:
            from flask import render_template
            return render_template('error.html',
                message="This subdomain is not registered. Please contact the administrator."), 404
        return func(*args, **kwargs)
    return wrapper


# Helper functions for common response patterns

def json_success(data=None, message=None, **kwargs):
    """
    Create standardized success JSON response
    
    Args:
        data: Optional data to include
        message: Optional success message
        **kwargs: Additional fields to include
    
    Returns:
        JSON response with success=True
    """
    response = {'success': True}
    if data is not None:
        response['data'] = data
    if message:
        response['message'] = message
    response.update(kwargs)
    return jsonify(response)


def json_error(error, status_code=400, **kwargs):
    """
    Create standardized error JSON response
    
    Args:
        error: Error message string
        status_code: HTTP status code (default 400)
        **kwargs: Additional fields to include
    
    Returns:
        JSON response with success=False and given status code
    """
    response = {'success': False, 'error': str(error)}
    response.update(kwargs)
    return jsonify(response), status_code


def validate_required_fields(data, required_fields):
    """
    Validate that all required fields are present in data dict
    
    Args:
        data: Dictionary to validate
        required_fields: List of required field names
    
    Returns:
        tuple: (is_valid: bool, missing_fields: list)
    
    Usage:
        is_valid, missing = validate_required_fields(request.form, ['username', 'email'])
        if not is_valid:
            return json_error(f"Missing fields: {', '.join(missing)}", 400)
    """
    missing = [field for field in required_fields if not data.get(field)]
    return (len(missing) == 0, missing)


def safe_int(value, default=0):
    """
    Safely convert value to integer with fallback
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
    
    Returns:
        int: Converted value or default
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default=0.0):
    """
    Safely convert value to float with fallback
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
    
    Returns:
        float: Converted value or default
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# Context manager for exception logging

class log_exceptions:
    """
    Context manager that logs exceptions with custom context
    
    Usage:
        with log_exceptions("fetching user data", user_id=123):
            user = get_user(123)
    """
    def __init__(self, operation, **context):
        self.operation = operation
        self.context = context
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            context_str = ', '.join(f"{k}={v}" for k, v in self.context.items())
            logger.error(f"Error during {self.operation} [{context_str}]: {exc_val}", exc_info=True)
        return False  # Don't suppress exception


# Example usage patterns
if __name__ == '__main__':
    # Example 1: API error handler
    from flask import Flask
    app = Flask(__name__)
    
    @app.route('/api/test')
    @api_error_handler
    def test_api():
        # Errors automatically converted to JSON responses
        raise ValueError("Test error")
    
    # Example 2: Validation
    data = {'username': 'john'}
    is_valid, missing = validate_required_fields(data, ['username', 'email', 'password'])
    if not is_valid:
        print(f"Missing: {missing}")
    
    # Example 3: Safe conversions
    user_id = safe_int(request.args.get('id'), default=0)
    
    # Example 4: Exception logging
    with log_exceptions("database operation", table="users"):
        # Your code here
        pass
