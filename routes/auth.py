import logging
from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from extensions import limiter
from services.user_service import UserService

# Blueprint has no prefix — login and logout live at root per spec.
auth_bp = Blueprint('auth', __name__)
user_service = UserService()
logger = logging.getLogger(__name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    """
    Authenticate user. On success, redirect to first-login profile page or
    role-appropriate dashboard. Blacklisted users are denied with a generic message.
    """
    if current_user.is_authenticated:
        return _redirect_to_role_dashboard(current_user)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = user_service.authenticate(username, password)

        if user:
            if not user.is_active:
                return render_template('public/login.html',
                                       error='Your account has been suspended. Please contact an administrator.')

            login_user(user)

            # First-login: redirect to profile completion page (workflow §1e)
            if not user.boolean_flag_indicating_if_user_profile_has_been_completed:
                return redirect(url_for('onboarding.profile'))

            return _redirect_to_role_dashboard(user)

        return render_template('public/login.html', error='Invalid username or password.')

    return render_template('public/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Destroy session and redirect to login page (workflow §2b)."""
    logout_user()
    return redirect(url_for('auth.login'))


def _redirect_to_role_dashboard(user):
    """Map a user's role to its canonical dashboard URL."""
    if user.is_admin:
        return redirect(url_for('admin.dashboard'))
    elif user.is_ai:
        return redirect(url_for('ai_dashboard.index'))
    else:
        return redirect(url_for('dashboard.index', username=user.user_account_unique_username_string))
