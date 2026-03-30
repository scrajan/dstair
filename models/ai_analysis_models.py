from extensions import db
from datetime import datetime, timezone
from models.base import ActiveRecordMixin
from sqlalchemy.orm.attributes import flag_modified

class AIAnalysis(ActiveRecordMixin, db.Model):
    """
    Stores AI-generated evaluations for sovereign countries.
    Exactly one record per country — enforced by the Unique constraint on country.
    Decoupled from User and Analysis models — AI evaluations are global, not user-scoped.

    Status lifecycle: not_started → in_progress → completed
                                                 ↘ error
    """
    __tablename__ = 'ai_analyses'

    id = db.Column(db.Integer, primary_key=True)

    # FK to Country.code — one record per country enforced here.
    country = db.Column(db.String(100), db.ForeignKey('countries.code', onupdate='CASCADE'), unique=True, nullable=False, index=True)

    # Lifecycle state
    status = db.Column(db.String(20), default='not_started', index=True)

    # Structure: {"question_id": score_value}
    # Scores are on the 1–10 computational scale. Null until evaluation completes.
    ai_scores_for_all_questions = db.Column(db.JSON, default=dict)

    # Structure: {"question_id": "reasoning text"}
    # AI-generated rationale per question. Null until evaluation completes.
    ai_comments_for_all_questions = db.Column(db.JSON, default=dict)

    # Generation metadata: provider used, model version, generation timestamp, retries, etc.
    metadata_json = db.Column(db.JSON, default=dict)

    # created_at: when the record was first created (seed time or first evaluation trigger)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # updated_at: updated when evaluation completes or fails
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<AIAnalysis {self.country}: {self.status}>'

    @property
    def title(self):
        """Dynamic title for the UI archive list."""
        return f"AI Evaluation: {self.country}"

    @property
    def country_obj(self):
        """Lazy lookup of the Country model for this AI analysis (for flag/image access)."""
        from models.core_models import Country
        return Country.get_by_code(self.country)

    def to_dict(self):
        return {
            'id': self.id,
            'country': self.country,
            'title': self.title,
            'status': self.status,
            'ai_comments_for_all_questions': self.ai_comments_for_all_questions or {},
            'ai_scores_for_all_questions': self.ai_scores_for_all_questions or {},
            'metadata': self.metadata_json or {},
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }

    @classmethod
    def get_by_country(cls, country_code: str):
        return db.session.query(cls).filter_by(country=country_code).first()

    def mark_in_progress(self, commit: bool = True):
        """Reset to in_progress, clearing previous results per overwrite behavior spec."""
        self.status = 'in_progress'
        self.ai_scores_for_all_questions = None
        self.ai_comments_for_all_questions = None
        flag_modified(self, "ai_scores_for_all_questions")
        flag_modified(self, "ai_comments_for_all_questions")
        if commit:
            self.save()

    def mark_completed(self, scores: dict, comments: dict, metadata: dict = None, commit: bool = True):
        self.status = 'completed'
        self.ai_scores_for_all_questions = scores
        self.ai_comments_for_all_questions = comments
        if metadata:
            self.metadata_json = metadata
        flag_modified(self, "ai_scores_for_all_questions")
        flag_modified(self, "ai_comments_for_all_questions")
        if commit:
            self.save()

    def mark_error(self, error_msg: str, commit: bool = True):
        self.status = 'error'
        if not self.metadata_json:
            self.metadata_json = {}
        self.metadata_json['last_error'] = error_msg
        flag_modified(self, "metadata_json")
        if commit:
            self.save()
