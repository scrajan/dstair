"""
Application configuration definitions across multiple environments.
Handles environment variables and base Flask settings.
"""
import os
import logging
from datetime import timedelta
from dotenv import load_dotenv

# Load key-value pairs from .env file into os.environ
load_dotenv()

DEFAULT_SECRET_KEY = 'dev-secret-key-INSECURE-change-immediately'

class Config:
    """
    Base configuration containing common settings for all environments.
    """
    DEFAULT_SECRET_KEY = DEFAULT_SECRET_KEY
    # Security key for session signing and CSRF tokens
    SECRET_KEY = os.getenv('SECRET_KEY', DEFAULT_SECRET_KEY)
    
    # Disable SQLAlchemy event system tracking to save memory
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Database connection string
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///database.db')

    # ── Session Security ──────────────────────────────────────
    # Prevent JavaScript access to session cookie
    SESSION_COOKIE_HTTPONLY = True
    # Restrict cross-site requests embedding the cookie
    SESSION_COOKIE_SAMESITE = 'Lax'
    # How long before a session automatically expires
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # ── CSRF (Flask-WTF) ──────────────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # CSRF tokens expire after 1 hour

    # ── Logging ───────────────────────────────────────────────
    LOG_LEVEL = logging.INFO

    # ── Upload Limits ────────────────────────────────────────
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB max upload size

    # ── Application Specific ──────────────────────────────────
    # Flag to trigger the database seeder on application launch
    AUTO_INIT_DB = True

class DevelopmentConfig(Config):
    """
    Development configuration enabling debugging tools.
    """
    DEBUG = True
    LOG_LEVEL = logging.DEBUG
    # Allow session cookies on unencrypted HTTP connections during dev
    SESSION_COOKIE_SECURE = False

class ProductionConfig(Config):
    """
    Production configuration enforcing stricter security limits.
    """
    DEBUG = False
    # Enforce HTTPS-only transmission for session cookies in prod
    SESSION_COOKIE_SECURE = True
    LOG_LEVEL = logging.WARNING

class TestingConfig(Config):
    """
    Testing configuration utilizing an isolated in-memory database.
    """
    TESTING = True
    # In-memory SQLite DB is entirely temporary for the duration of the test suite
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    # Disable CSRF checks during automated testing
    WTF_CSRF_ENABLED = False
    LOGIN_DISABLED = False


def is_insecure_secret_key(secret_key: str) -> bool:
    """Return True when a secret key matches the known insecure development fallback."""
    if not secret_key:
        return True
    return secret_key == DEFAULT_SECRET_KEY or 'INSECURE' in secret_key


def validate_runtime_config(app, config_class) -> None:
    """Validate runtime configuration after Flask has loaded the config object."""
    if isinstance(config_class, type) and issubclass(config_class, ProductionConfig):
        if is_insecure_secret_key(app.config.get('SECRET_KEY')):
            raise RuntimeError(
                "FATAL: SECRET_KEY contains insecure default value. "
                "Set a strong SECRET_KEY in .env before running in production."
            )
