from functools import wraps
from flask import redirect, url_for, abort
from flask_login import current_user

def admin_role_required_decorator(wrapped_route_handler_function):
    """Decorator to require admin role for a route"""
    @wraps(wrapped_route_handler_function)
    def internal_decorator_wrapper_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.user_account_authorization_role_identifier_string != 'admin':
            abort(403)  # Forbidden
        return wrapped_route_handler_function(*args, **kwargs)
    return internal_decorator_wrapper_function

def ai_role_required_decorator(wrapped_route_handler_function):
    """Decorator to require ai role for a route"""
    @wraps(wrapped_route_handler_function)
    def internal_decorator_wrapper_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.user_account_authorization_role_identifier_string != 'ai':
            abort(403)  # Forbidden
        return wrapped_route_handler_function(*args, **kwargs)
    return internal_decorator_wrapper_function
