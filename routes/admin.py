import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user
from extensions import limiter
from utils.decorators import admin_role_required_decorator
from services.user_service import UserService
from services.access_request_service import AccessRequestService

# Initialize Blueprint for the central admin panel operations
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
user_service = UserService()
access_request_service = AccessRequestService()
logger = logging.getLogger(__name__)

@admin_bp.route('/dashboard')
@admin_role_required_decorator
def dashboard():
    """
    Admin Dashboard Page (HTML).
    Displays high-level system metrics, usage stats, and recent user signups.
    Uses @admin_role_required_decorator decorator to bounce standard users.
    """
    stats = user_service.get_dashboard_stats()
    pending_count = access_request_service.get_pending_count()
    
    return render_template('admin/dashboard.html', 
                          total_users=stats['total_users'],
                          admin_count=stats['admin_count'],
                          user_count=stats['user_count'],
                          ai_count=stats['ai_count'],
                          recent_users=stats['recent_users'],
                          pending_requests=pending_count)

@admin_bp.route('/users')
@admin_role_required_decorator
def users():
    """
    User Management Roster Page (HTML).
    Lists all users to allow modification of roles or account deletion.
    """
    all_users = user_service.get_all_users()
    return render_template('admin/users.html', users=all_users)

@admin_bp.route('/comments')
@admin_role_required_decorator
def comments():
    """
    Comment Moderation Page (HTML).
    Allows admins to review all feedback dropped by users and AI across 
    all questions globally.
    """
    limit = request.args.get('limit', 50, type=int)
    display_comments, total_comments = user_service.get_aggregated_comments(limit)
    
    return render_template('admin/comments.html', 
                         comments=display_comments, 
                         total=total_comments, 
                         limit=limit)

@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@admin_role_required_decorator
def edit_user(user_id):
    """
    Update a user's full name and email (workflow §7c).
    Username and role are not exposed — admins cannot change them.
    """
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()

    target_user = user_service.get_user_by_id(user_id)
    if not target_user:
        flash('User not found', 'error')
        return redirect(url_for('admin.users'))

    try:
        user_service.update_user(
            user_id,
            target_user.user_account_unique_username_string,
            role=target_user.user_account_authorization_role_identifier_string,
            name=name,
            email=email
        )
        flash('User updated successfully', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception:
        logger.exception('Error updating user %s', user_id)
        flash('An unexpected error occurred while updating the user', 'error')

    return redirect(url_for('admin.users'))

@admin_bp.route('/users/create', methods=['POST'])
@admin_role_required_decorator
def create_user():
    """
    Form Submission Endpoint: Manually provisions a new user account.
    """
    username = request.form.get('username')
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    
    # COORDINATION: Admins can ONLY create 'user' role accounts. 
    # AI and Admin roles are restricted/singular per spec.
    role = 'user'
    
    if not username or not password:
        flash('Username and Password are required', 'error')
        return redirect(url_for('admin.users'))
        
    try:
        user_service.create_user(
            username=username, 
            name=name, 
            email=email, 
            password=password, 
            role=role
        )
        flash('User created successfully', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception:
        logger.exception('Error creating user')
        flash('An unexpected error occurred while creating the user', 'error')
        
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_role_required_decorator
def delete_user(user_id):
    """
    Form Submission Endpoint: Obliterates a user from the DB.
    Includes safeguard inside service layer preventing self-deletion.
    """
    try:
        user_service.delete_user(user_id, current_user.unique_database_identifier_integer)
        flash('User deleted successfully', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception:
        logger.exception('Error deleting user %s', user_id)
        flash('An unexpected error occurred while deleting the user', 'error')
        
    return redirect(url_for('admin.users'))

# ── Access Request Management ────────────────────────────────────

@admin_bp.route('/access-requests')
@admin_role_required_decorator
def access_requests():
    """Admin page to review access requests submitted from the Contact Us page."""
    status_filter = request.args.get('status', 'pending')
    requests_list = access_request_service.get_requests(status_filter)
    pending_count = access_request_service.get_pending_count()
    
    return render_template('admin/access_requests.html', 
                         requests=requests_list, 
                         status_filter=status_filter,
                         pending_count=pending_count)


@admin_bp.route('/access-requests/<int:request_id>/approve', methods=['POST'])
@admin_role_required_decorator
def approve_access_request(request_id):
    """
    Approve an access request: auto-generate credentials, create user account,
    and return mailto link for onboarding delivery.
    """
    try:
        result = access_request_service.approve_request(request_id)
        return jsonify({
            'success': True,
            'username': result['username'],
            'password': result['password'],
            'mailto_link': result.get('mailto_link'),
            'email_sent': result.get('email_sent', False),
            'message': f'User account created for {result["req_name"]}'
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception('Error approving access request %s', request_id)
        return jsonify({'success': False, 'error': 'Failed to approve request'}), 500


@admin_bp.route('/access-requests/<int:request_id>/reject', methods=['POST'])
@admin_role_required_decorator
def reject_access_request(request_id):
    """Reject an access request."""
    try:
        access_request_service.reject_request(request_id)
        return jsonify({'success': True, 'message': 'Request rejected'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception('Error rejecting access request %s', request_id)
        return jsonify({'success': False, 'error': 'Failed to reject request'}), 500

@admin_bp.route('/access-requests/<int:request_id>/delete', methods=['POST'])
@admin_role_required_decorator
def delete_access_request(request_id):
    """Delete an access request record."""
    try:
        access_request_service.delete_request(request_id)
        return jsonify({'success': True, 'message': 'Request deleted'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception('Error deleting access request %s', request_id)
        return jsonify({'success': False, 'error': 'Failed to delete request'}), 500


# ── User Blacklisting ────────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/blacklist', methods=['POST'])
@admin_role_required_decorator
def toggle_blacklist(user_id):
    """Toggle a user's active/blacklisted status."""
    try:
        result = user_service.toggle_blacklist(user_id, current_user.unique_database_identifier_integer)
        flash(f'User {"unblacklisted" if result else "blacklisted"} successfully', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        logger.exception('Error toggling blacklist for user %s', user_id)
        flash('An unexpected error occurred', 'error')
    
    return redirect(url_for('admin.users'))



