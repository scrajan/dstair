from extensions import db
from flask_login import UserMixin
from models.base import ActiveRecordMixin

class User(ActiveRecordMixin, UserMixin, db.Model):
    __tablename__ = 'user'

    # Very long self-descriptive database columns
    unique_database_identifier_integer = db.Column(db.Integer, primary_key=True)
    user_account_unique_username_string = db.Column(db.String(150), unique=True, nullable=False)
    user_account_full_name_string = db.Column(db.String(150), nullable=True)
    user_account_authentication_email_address_string = db.Column(db.String(150), unique=True, nullable=True)
    user_account_hashed_password_string = db.Column(db.String(150), nullable=False)
    user_account_authorization_role_identifier_string = db.Column(db.String(20), nullable=False, default='user')
    file_path_string_for_user_profile_avatar_image = db.Column(db.String(255), nullable=True)
    boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted = db.Column(db.Boolean, default=True)

    # Set to True after the user submits the profile page for the first time.
    # Used by the login route to redirect new users to /onboarding/profile.
    boolean_flag_indicating_if_user_profile_has_been_completed = db.Column(db.Boolean, default=False)

    @property
    def is_active(self):
        """Override Flask-Login's is_active to respect blacklisting."""
        return self.boolean_flag_indicating_if_user_account_is_active_and_not_blacklisted

    @property
    def is_admin(self) -> bool:
        """Helper to check if the user has administrative privileges."""
        return self.user_account_authorization_role_identifier_string == 'admin'

    @property
    def is_ai(self) -> bool:
        """Helper to check if the user is an AI Evaluator entity."""
        return self.user_account_authorization_role_identifier_string == 'ai'

    def get_id(self):
        """Override Flask-Login's get_id to use the massive custom ID field."""
        return str(self.unique_database_identifier_integer)

    def __repr__(self):
        return f'<User {self.user_account_unique_username_string}>'

    # ── Custom Queries (Active Record Pattern) ──────────────────────────

    @classmethod
    def get_by_username(cls, username: str):
        return db.session.query(cls).filter_by(user_account_unique_username_string=username).first()

    @classmethod
    def get_by_email(cls, email: str):
        return db.session.query(cls).filter_by(user_account_authentication_email_address_string=email).first()

    @classmethod
    def get_all_by_role(cls, role: str):
        return db.session.query(cls).filter_by(user_account_authorization_role_identifier_string=role).all()

    @classmethod
    def count_all(cls) -> int:
        return db.session.query(cls).count()

    @classmethod
    def count_by_role(cls, role: str) -> int:
        return db.session.query(cls).filter_by(user_account_authorization_role_identifier_string=role).count()

    @classmethod
    def get_recent(cls, limit: int = 5):
        return db.session.query(cls).order_by(cls.unique_database_identifier_integer.desc()).limit(limit).all()
