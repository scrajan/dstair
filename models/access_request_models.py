from extensions import db
from datetime import datetime, timezone
from models.base import ActiveRecordMixin


class AccessRequest(ActiveRecordMixin, db.Model):
    """
    Stores access requests submitted via the Contact Us page.
    Admin reviews these and can approve (generating credentials) or reject.
    """
    __tablename__ = 'access_requests'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    organization = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending', index=True)  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # If approved, link to the created user account
    created_user_id = db.Column(db.Integer, db.ForeignKey('user.unique_database_identifier_integer', ondelete='SET NULL'), nullable=True)
    created_user = db.relationship('User', backref=db.backref('access_request', uselist=False))

    @property
    def is_pending(self) -> bool:
        return self.status == 'pending'

    @property
    def is_approved(self) -> bool:
        return self.status == 'approved'

    @property
    def is_rejected(self) -> bool:
        return self.status == 'rejected'

    def mark_approved(self, user_id: int, commit: bool = True):
        """Transition the request to approved and link the new user ID."""
        self.status = 'approved'
        self.created_user_id = user_id
        self.reviewed_at = datetime.now(timezone.utc)
        if commit:
            self.save()

    def mark_rejected(self, commit: bool = True):
        """Transition the request to rejected."""
        self.status = 'rejected'
        self.reviewed_at = datetime.now(timezone.utc)
        if commit:
            self.save()

    def __repr__(self):
        return f'<AccessRequest {self.id}: {self.email} ({self.status})>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'organization': self.organization,
            'message': self.message,
            'status': self.status,
            'created_user_id': self.created_user_id,
            'created_at': self.created_at.strftime('%b %d, %Y %I:%M %p') if self.created_at else None,
            'reviewed_at': self.reviewed_at.strftime('%b %d, %Y %I:%M %p') if self.reviewed_at else None,
        }

    @classmethod
    def get_by_email_and_status(cls, email: str, status: str):
        return db.session.query(cls).filter_by(email=email, status=status).first()

    @classmethod
    def get_all_ordered_by_date(cls):
        return db.session.query(cls).order_by(cls.created_at.desc()).all()

    @classmethod
    def get_by_status_ordered(cls, status: str):
        return db.session.query(cls).filter_by(status=status).order_by(cls.created_at.desc()).all()

    @classmethod
    def count_by_status(cls, status: str) -> int:
        return db.session.query(cls).filter_by(status=status).count()
