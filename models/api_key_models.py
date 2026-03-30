from extensions import db
from datetime import datetime, timezone
from models.base import ActiveRecordMixin


class APIKey(ActiveRecordMixin, db.Model):
    """Stores API keys for various AI providers, scoped per user.
    Keys are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256)."""
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.unique_database_identifier_integer', ondelete='CASCADE'), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False)  # 'groq', 'openai', 'claude', 'gemini', 'openrouter'
    api_key = db.Column(db.String(500), nullable=False)   # Stored encrypted (Fernet token)
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)  # Fallback priority: lower = tried first
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('api_keys', lazy=True))

    # Supported providers — logos stored in static/assets/providers/
    PROVIDERS = {
        'groq': {'label': 'Groq', 'icon': 'G', 'logo': 'assets/providers/groq.svg', 'placeholder': 'gsk_...', 'docs_url': 'https://console.groq.com/keys'},
        'openai': {'label': 'OpenAI', 'icon': 'O', 'logo': 'assets/providers/openai.svg', 'placeholder': 'sk-...', 'docs_url': 'https://platform.openai.com/api-keys'},
        'claude': {'label': 'Claude (Anthropic)', 'icon': 'C', 'logo': 'assets/providers/anthropic.svg', 'placeholder': 'sk-ant-...', 'docs_url': 'https://console.anthropic.com/settings/keys'},
        'gemini': {'label': 'Google Gemini', 'icon': 'GM', 'logo': 'assets/providers/gemini.svg', 'placeholder': 'AIza...', 'docs_url': 'https://aistudio.google.com/app/apikey'},
        'openrouter': {'label': 'OpenRouter', 'icon': 'R', 'logo': 'assets/providers/openrouter.svg', 'placeholder': 'sk-or-...', 'docs_url': 'https://openrouter.ai/keys'},
    }

    # ── Encryption helpers ──────────────────────────────────────

    def set_key(self, plaintext_key: str):
        """Encrypt and store the API key."""
        from utils.encryption import encrypt_value
        self.api_key = encrypt_value(plaintext_key)

    def get_key(self) -> str:
        """Decrypt and return the API key."""
        from utils.encryption import decrypt_value
        return decrypt_value(self.api_key)

    def to_dict(self):
        config = self.PROVIDERS.get(self.provider, {})
        return {
            'id': self.id,
            'provider': self.provider,
            'label': config.get('label', self.provider),
            'logo': config.get('logo'),
            'docs_url': config.get('docs_url'),
            'placeholder': config.get('placeholder'),
            'is_active': self.is_active,
            'masked_key': self.masked_key,
            'updated_at': self.updated_at.strftime('%b %d, %Y') if self.updated_at else None,
        }

    @property
    def masked_key(self):
        """Return the decrypted key with middle portion masked for display."""
        decrypted = self.get_key()
        if not decrypted:
            return '••••••••'
        if len(decrypted) <= 8:
            return '••••••••'
        return f"{decrypted[:4]}••••••••{decrypted[-4:]}"

    def __repr__(self):
        return f'<APIKey {self.id}: {self.provider} active={self.is_active}>'

    @classmethod
    def get_user_keys(cls, user_id: int):
        return db.session.query(cls).filter_by(user_id=user_id).order_by(cls.order.asc()).all()

    @classmethod
    def get_active_user_keys(cls, user_id: int):
        return db.session.query(cls).filter_by(user_id=user_id, is_active=True).order_by(cls.order.asc()).all()

    @classmethod
    def get_by_provider(cls, user_id: int, provider: str):
        return db.session.query(cls).filter_by(user_id=user_id, provider=provider).first()

    @classmethod
    def get_active_user_keys_by_provider(cls, user_id: int, provider: str):
        return db.session.query(cls).filter_by(
            user_id=user_id, provider=provider, is_active=True
        ).order_by(cls.order.asc()).all()

    @classmethod
    def get_by_id_and_user(cls, key_id: int, user_id: int):
        return db.session.query(cls).filter_by(id=key_id, user_id=user_id).first()

    @classmethod
    def get_max_order_for_user(cls, user_id: int):
        from sqlalchemy import func
        return db.session.query(func.max(cls.order)).filter_by(user_id=user_id).scalar()
