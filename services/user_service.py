import logging
from werkzeug.security import generate_password_hash, check_password_hash
from models import User
from utils.sanitizer import sanitize_input

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self):
        pass

    # ── Authentication ──────────────────────────────────────

    def authenticate(self, username: str, password: str):
        """Verify credentials and return the User if valid, else None."""
        user = User.get_by_username(username)
        if user and check_password_hash(user.user_account_hashed_password_string, password):
            return user
        return None

    # ── Queries ─────────────────────────────────────────────

    def get_user_by_id(self, user_id):
        """Fetch a single user by their primary key."""
        return User.get_by_id(user_id)

    def get_all_users(self):
        """Return all users EXCEPT the AI evaluator, who is hidden from admins per spec."""
        return [u for u in User.get_all() if u.user_account_authorization_role_identifier_string != 'ai']

    def get_dashboard_stats(self):
        """Fetch aggregate system metrics for the Admin Dashboard."""
        return {
            'total_users': User.count_all(),
            'admin_count': User.count_by_role('admin'),
            'user_count': User.count_by_role('user'),
            'ai_count': User.count_by_role('ai'),
            # COORDINATION: Increase sample size to ensure we get non-AI users for the list
            'recent_users': [u for u in User.get_recent(30) if u.user_account_authorization_role_identifier_string != 'ai'][:5]
        }

    # ── User CRUD ───────────────────────────────────────────

    def check_username_exists(self, username, exclude_user_id=None):
        """Check if a username is already taken, optionally excluding a specific user ID."""
        user = User.get_by_username(username)
        if user and user.unique_database_identifier_integer != exclude_user_id:
            return True
        return False

    def check_email_exists(self, email, exclude_user_id=None):
        """Check if an email is already taken, optionally excluding a specific user ID."""
        user = User.get_by_email(email)
        if user and user.unique_database_identifier_integer != exclude_user_id:
            return True
        return False

    def create_user(self, username, password, role='user', name=None, email=None):
        """Provision a new user account with strict role enforcement."""
        # COORDINATION: Admins cannot create Admin or AI roles
        if role in ['admin', 'ai']:
            raise ValueError(f"Cannot manually create {role} role via the application. Role-based restrictions apply.")
            
        if User.get_by_username(username):
            raise ValueError(f"User {username} already exists")
        if email and self.check_email_exists(email):
            raise ValueError("Email already exists")

        new_user = User(
            user_account_unique_username_string=sanitize_input(username),
            user_account_full_name_string=sanitize_input(name) if name else None,
            user_account_authentication_email_address_string=sanitize_input(email) if email else None,
            user_account_hashed_password_string=generate_password_hash(password, method='scrypt'),
            user_account_authorization_role_identifier_string=role
        )
        return new_user.save()

    def update_user(self, user_id, username=None, password=None, role=None, name=None, email=None):
        """
        Updates an existing user's record. 
        Only updates fields that are explicitly provided (not None).
        """
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        # COORDINATION: Protect restricted accounts from standard admin manipulation
        # Admins cannot touch AI users or other admins (except themselves)
        if user.user_account_authorization_role_identifier_string == 'ai':
            raise ValueError("Standard admins cannot modify AI Evaluator accounts.")
        if user.user_account_authorization_role_identifier_string == 'admin' and user_id != user.unique_database_identifier_integer:
             raise ValueError("Admins cannot modify other admin accounts.")

        # Prevent unauthorized role escalation and maintain single admin rule
        if role and role != user.user_account_authorization_role_identifier_string:
            if user.user_account_authorization_role_identifier_string == 'admin':
                 raise ValueError("The administrator role is fixed and cannot be changed.")
            if role in ['admin', 'ai']:
                 raise ValueError(f"Cannot manually assign {role} role. Role-based restrictions apply.")
            user.user_account_authorization_role_identifier_string = role

        # Validate unique constraints before persisting
        if username and self.check_username_exists(username, user_id):
            raise ValueError("Username already exists")
        if email and self.check_email_exists(email, user_id):
            raise ValueError("Email already exists")

        # Apply updates with sanitization
        if username:
            user.user_account_unique_username_string = sanitize_input(username)
        if email:
            user.user_account_authentication_email_address_string = sanitize_input(email)
        if name:
            user.user_account_full_name_string = sanitize_input(name)
        if password:
            user.user_account_hashed_password_string = generate_password_hash(password, method='scrypt')

        return user.save()

    def update_profile(self, user, name, email, profile_image=None):
        """Update the profile of the currently logged-in user."""
        if email:
            existing = User.get_by_email(email)
            if existing and existing.unique_database_identifier_integer != user.unique_database_identifier_integer:
                raise ValueError("Email already in use")

        if name:
            user.user_account_full_name_string = sanitize_input(name)
        if email:
            user.user_account_authentication_email_address_string = sanitize_input(email)
        if profile_image:
            user.file_path_string_for_user_profile_avatar_image = profile_image
            
        return user.save()

    def delete_user(self, user_id, requesting_user_id=None):
        """Permanently remove a user from the system with safety checks."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        
        # Security: Prevent deleting self or protected roles
        if requesting_user_id and user_id == requesting_user_id:
            raise ValueError("Cannot delete your own account")
        if user.user_account_authorization_role_identifier_string == 'admin':
            raise ValueError("Cannot delete admin users")
        if user.user_account_authorization_role_identifier_string == 'ai':
            raise ValueError("Cannot delete the AI system user")

        user.delete()

    def toggle_blacklist(self, user_id, requesting_user_id=None):
        """Toggle a user's is_active_user status. Returns the new is_active_user value."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        
        # Security: Protected roles cannot be blacklisted
        if user.user_account_authorization_role_identifier_string == 'ai':
            raise ValueError("Cannot blacklist the AI system user")
        if user.user_account_authorization_role_identifier_string == 'admin':
            raise ValueError("Cannot blacklist admin users")
        if requesting_user_id and user_id == requesting_user_id:
            raise ValueError("Cannot blacklist your own account")

        user.boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted = not user.boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted
        user.save()
        return user.boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted

    # ── Comments (admin view) ──────────────────────────────

    def get_aggregated_comments(self, limit=50):
        """Fetch recent comments across all questions for admin review."""
        from models.core_models import Comment
        
        results = Comment.get_recent_with_questions(limit)

        all_comments = []
        for comment, question in results:
            all_comments.append({
                'id': comment.id,
                'user': comment.user_display,
                'comment': comment.text,
                'date': comment.created_at.strftime('%m/%d/%Y %I:%M:%S %p'),
                'question_id': question.id,
                'question_content': question.content,
                'analysis_id': comment.analysis_id
            })

        total = Comment.count_all()
        return all_comments, total
