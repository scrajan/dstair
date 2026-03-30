from extensions import db
import sqlalchemy
from datetime import datetime, timezone
from models.base import ActiveRecordMixin

class Sphere(ActiveRecordMixin, db.Model):
    """ 
    Represents a categorical 'Sphere' of institutional review.
    Examples: 'CONSTITUTION', 'POLITICAL', 'ECONOMIC'.
    Spheres contain many Questions and are tied to ToolCriteria.
    """
    __tablename__ = 'spheres'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True) # Underlying ID, e.g., "CONSTITUTION"
    label = db.Column(db.String(100), nullable=False) # Frontend Display name, e.g., "Constitution"
    order = db.Column(db.Integer, default=0) # Controls display order in tabs
    
    # ── Relationships ──────────────────────────────────────────
    # 'selectin' loading prevents N+1 query problems when traversing relationships
    questions = db.relationship('Question', backref='sphere', lazy='selectin', cascade="all, delete-orphan")
    tool_criteria = db.relationship('ToolCriteria', backref='sphere', lazy='selectin', cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<Sphere {self.name}>'

    @classmethod
    def get_all_ordered(cls):
        return db.session.query(cls).order_by(cls.order).all()

    @classmethod
    def get_by_name(cls, name: str):
        return db.session.query(cls).filter_by(name=name).first()

class Question(ActiveRecordMixin, db.Model):
    """
    Represents a specific metric or parameter evaluated within a Sphere.
    Users answer these questions on a 1-7 scale to generate scores.
    """
    __tablename__ = 'questions'
    
    id = db.Column(db.Integer, primary_key=True)
    sphere_id = db.Column(db.Integer, db.ForeignKey('spheres.id'), nullable=False, index=True)
    order = db.Column(db.Integer, default=0) # Display order within the sphere tab
    content = db.Column(db.Text, nullable=False) # The actual questionnaire question
    
    # Dynamic labels shown on the extremes of the slider/radio buttons
    scale_min_label = db.Column(db.String(100))
    scale_max_label = db.Column(db.String(100))
    
    # Optional categorization: 'META-RULE', 'RULE', 'EXOGENOUS'
    type = db.Column(db.String(50)) 
    
    # Multiplier in the sphere score calculation engine (AnalysisService)
    # Default is 1=Low, 2=Medium, 3=High
    importance = db.Column(db.Integer, default=1) 
    help_info = db.Column(db.Text, nullable=True) # Tooltip context, will open when the user clicks on the more info button 
    
    # ── Relational Comments ────────────────────────────────────
    # Tracks human or AI remarks attached to this specific question context
    relational_comments = db.relationship('Comment', backref='question', lazy='selectin', cascade="all, delete-orphan", order_by="desc(Comment.created_at)")
    
    @property
    def serialize_comments(self):
        """Converts related non-AI comments to a dictionary format suitable for JSON API transmission."""
        from models.user_models import User
        from flask import g
        
        # Initialize a per-request cache to avoid N+1 database queries across the 50+ questions
        if not hasattr(g, 'user_avatar_cache'):
            g.user_avatar_cache = {}
            
        usernames = {c.user_display for c in self.relational_comments}
        missing_users = [u for u in usernames if u not in g.user_avatar_cache]
        
        if missing_users:
            users = User.query.filter(User.user_account_unique_username_string.in_(missing_users)).all()
            for u in users:
                g.user_avatar_cache[u.user_account_unique_username_string] = u

        results = []
        for c in self.relational_comments:
            user = g.user_avatar_cache.get(c.user_display)
            results.append({
                'id': c.id, 
                'user': c.user_display, 
                'user_full_name': user.user_account_full_name_string if user else c.user_display,
                'user_avatar': user.file_path_string_for_user_profile_avatar_image if user else None,
                'comment': c.text, 
                'date': c.created_at.strftime('%m/%d/%Y %I:%M:%S %p') if c.created_at else '',
                'analysis_id': c.analysis_id
            })
        return results
    
    def __repr__(self):
        return f'<Question {self.id} Sphere:{self.sphere_id}>'

    @classmethod
    def get_all_with_comments(cls):
        from models.core_models import Comment
        return db.session.query(cls).join(Comment).distinct().all()

    def add_comment(self, new_comment_dict: dict, analysis_id: int = None) -> Comment:
        """Adds a new comment to this question, persisting it via ActiveRecord pattern."""
        try:
            created_at = datetime.strptime(new_comment_dict.get('date', ''), '%m/%d/%Y %I:%M:%S %p')
        except (ValueError, TypeError):
            created_at = datetime.now(timezone.utc)

        comment = Comment(
            id=new_comment_dict['id'],
            question_id=self.id,
            analysis_id=analysis_id,
            user_display=new_comment_dict['user'],
            text=new_comment_dict['comment'],
            created_at=created_at
        )
        return comment.save()

    def remove_comment(self, comment_id: str) -> bool:
        """Removes a comment from this question context."""
        comment = Comment.get_by_id(comment_id)
        if comment and comment.question_id == self.id:
            comment.delete()
            return True
        return False

class Comment(ActiveRecordMixin, db.Model):
    """
    Stores qualitative feedback, contextual notes, or AI reasoning 
    attached to a specific parameter (Question).
    """
    __tablename__ = 'comments'
    
    # Uses a UUID string rather than integer for distributed scalability
    id = db.Column(db.String(36), primary_key=True) 
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', ondelete='CASCADE'), nullable=False, index=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analyses.id', ondelete='SET NULL'), nullable=True, index=True)
    user_display = db.Column(db.String(150), nullable=False) # Name of user
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<Comment {self.id} Question:{self.question_id}>'

    @classmethod
    def get_recent_with_questions(cls, limit: int = 50):
        from models.core_models import Question
        return (
            db.session.query(cls, Question)
            .join(Question)
            .order_by(cls.created_at.desc())
            .limit(limit)
            .all()
        )

    @classmethod
    def count_all(cls) -> int:
        return db.session.query(cls).count()

# ── UGC Sanitization Logic ──────────────────────────────────────
# Ensures all qualitative inputs are stripped of malicious HTML/JS.
@sqlalchemy.event.listens_for(Comment, 'before_insert')
@sqlalchemy.event.listens_for(Comment, 'before_update')
def sanitize_comment_text(mapper, connection, target):
    from utils.sanitizer import sanitize_comment
    if target.text:
        target.text = sanitize_comment(target.text)

class Tool(ActiveRecordMixin, db.Model):
    """
    Represents an institutional reform methodology or tool (e.g., "Stakeholder Mapping").
    Recommended to users based on calculated Sphere scores.
    """
    __tablename__ = 'tools'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False) # Short summary card text
    content = db.Column(db.Text, nullable=True) # Full rich-text HTML content for modals
    
    # ── Relationships ──────────────────────────────────────────
    # The conditions under which this tool is recommended
    criteria = db.relationship('ToolCriteria', backref='tool', lazy='selectin', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Tool {self.title}>'

    @classmethod
    def get_all_with_criteria(cls):
        from sqlalchemy.orm import joinedload
        return db.session.query(cls).options(joinedload(cls.criteria)).all()

class ToolCriteria(ActiveRecordMixin, db.Model):
    """
    Defines a logical rule for triggering a Tool recommendation.
    For example: "If [sphere_id] score is <= 0.4, trigger".
    A Tool with multiple criteria requires ALL to be met (Logical AND).
    """
    __tablename__ = 'tool_criteria'
    
    id = db.Column(db.Integer, primary_key=True)
    tool_id = db.Column(db.Integer, db.ForeignKey('tools.id'), nullable=False, index=True)
    sphere_id = db.Column(db.Integer, db.ForeignKey('spheres.id'), nullable=False, index=True)
    
    # The maximum allowed score before the tool is hidden
    min_score_threshold = db.Column(db.Float, nullable=False) 
    
    def __repr__(self):
        return f'<ToolCriteria Tool:{self.tool_id} Sphere:{self.sphere_id} Threshold:{self.min_score_threshold}>'

class Country(ActiveRecordMixin, db.Model):
    """
    Represents a sovereign country evaluated within DSTAIR.
    Provides a standardized core list to be universally referenced across Analysis workflows.
    """
    __tablename__ = 'countries'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False, unique=True, index=True) # e.g., 'Afghanistan'
    name = db.Column(db.String(100), nullable=False)
    order = db.Column(db.Integer, default=0) # Display order prioritizing certain countries if needed
    iso2_code = db.Column(db.String(2), nullable=True)  # ISO 3166-1 alpha-2, e.g. 'AF', 'US'
    image_url = db.Column(db.Text, nullable=True)  # Relative path from Flask static root, e.g. 'assets/countries/061_France.jpg'

    @property
    def hero_image_static_url(self):
        """Flask static URL for the country hero image. Returns None if not set."""
        if self.image_url:
            from flask import url_for
            return url_for('static', filename=self.image_url)
        return None

    @property
    def flag_url(self):
        """CDN flag image URL (flagcdn.com). Returns None if iso2_code not set."""
        if self.iso2_code:
            return f"https://flagcdn.com/w40/{self.iso2_code.lower()}.png"
        return None

    @property
    def flag_emoji(self):
        """Unicode flag emoji derived from iso2_code (no DB storage needed)."""
        if self.iso2_code and len(self.iso2_code) == 2:
            a, b = self.iso2_code.upper()
            return chr(0x1F1E6 + ord(a) - ord('A')) + chr(0x1F1E6 + ord(b) - ord('A'))
        return ''
    
    def __repr__(self):
        return f'<Country {self.code}: {self.name}>'

    @classmethod
    def get_all_ordered(cls):
        return db.session.query(cls).order_by(cls.order, cls.name).all()

    @classmethod
    def get_by_code(cls, code: str):
        return db.session.query(cls).filter_by(code=code).first()
