from extensions import db
from datetime import datetime, timezone
from models.base import ActiveRecordMixin
from sqlalchemy.orm.attributes import flag_modified

class Analysis(ActiveRecordMixin, db.Model):
    """
    Represents a discrete session of evaluation conducted for a specific country by a human user.
    Stores the user's answers and keeps track of triggered anti-corruption tool IDs.

    Per spec:
    - No status field — all analyses are permanently editable.
    - No scores stored — computed exclusively by the frontend JS engine.
    - triggered_tools is a JSON list of integer IDs, not a many-to-many relationship.
    - country is a plain string — not a foreign key.
    """
    __tablename__ = 'analyses'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.unique_database_identifier_integer', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)

    # Plain string — NOT a FK to countries.code per spec.
    country = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    # Structure: {"SPHERE_NAME": {"question_id": rating_value}}
    # Rating values are raw 1–7 UI values. Frontend handles 1–10 conversion.
    answers = db.Column(db.JSON, default=dict)

    # Epoch milliseconds of the last successful AJAX save.
    # Used to detect and reject stale out-of-order responses.
    last_sync_timestamp = db.Column(db.BigInteger, default=0)

    # List of triggered tool IDs: [1, 5, 12, ...]
    # Recalculated by AnalysisService on every answer save.
    # Single source of truth — no join table exists or should be created.
    triggered_tools = db.Column(db.JSON, default=list)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ──────────────────────────────────────────────────
    user = db.relationship('User', backref=db.backref('analyses', lazy=True))

    @property
    def country_obj(self):
        """Lazy lookup of the Country model for this analysis (for flag/emoji access)."""
        from models.core_models import Country
        return Country.get_by_code(self.country) or Country.query.filter_by(name=self.country).first()

    @property
    def answers_dict(self):
        """Safely returns the answers dict or empty dict if null."""
        return self.answers or {}

    @property
    def triggered_tools_list(self):
        """Safely returns the triggered tool ID list or empty list if null."""
        return self.triggered_tools or []

    def __repr__(self):
        return f'<Analysis {self.id}: {self.title} ({self.country})>'

    def to_dict(self):
        """Standard dictionary serializer for API responses."""
        return {
            'id': self.id,
            'title': self.title,
            'country': self.country,
            'notes': self.notes,
            'answers': self.answers_dict,
            'triggered_tools': self.triggered_tools_list,
            'last_sync_timestamp': self.last_sync_timestamp,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }

    @classmethod
    def get_all_for_user(cls, user_id: int):
        return db.session.query(cls).filter_by(user_id=user_id).order_by(cls.updated_at.desc()).all()

    @classmethod
    def get_by_id_and_user(cls, id: int, user_id: int):
        return db.session.query(cls).filter_by(id=id, user_id=user_id).first()

    @classmethod
    def get_by_country_excluding_user(cls, country: str, exclude_user_id: int):
        """
        Get analyses for a given country, excluding the specified user.
        Returns up to 4 most recently updated, ordered by updated_at descending.
        No status filter — all analyses are permanently editable per spec.
        """
        from sqlalchemy.orm import joinedload
        return (
            db.session.query(cls)
            .options(joinedload(cls.user))
            .filter(cls.country == country, cls.user_id != exclude_user_id)
            .order_by(cls.updated_at.desc())
            .limit(4)
            .all()
        )

    @classmethod
    def count_total_for_user(cls, user_id: int) -> int:
        return db.session.query(cls).filter_by(user_id=user_id).count()

    @classmethod
    def get_unique_countries_count(cls, user_id: int) -> int:
        """Count of unique countries the user has analyzed."""
        from sqlalchemy import distinct, func
        return db.session.query(func.count(distinct(cls.country))).filter_by(user_id=user_id).scalar() or 0
