from datetime import datetime

try:
    from flask_sqlalchemy import SQLAlchemy
    from flask_login import UserMixin
except ImportError:
    class _DummyType:
        def __call__(self, *args, **kwargs):
            return self

    class _DummySession:
        def remove(self):
            pass

    class _DummyDb:
        Model = object
        Integer = _DummyType()
        String = _DummyType()
        Text = _DummyType()
        Float = _DummyType()
        Boolean = _DummyType()
        DateTime = _DummyType()
        session = _DummySession()

        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, *args, **kwargs):
            pass

        def create_all(self, *args, **kwargs):
            pass

        def drop_all(self, *args, **kwargs):
            pass

        def Column(self, *args, **kwargs):
            return None

        def ForeignKey(self, *args, **kwargs):
            return None

        def relationship(self, *args, **kwargs):
            return None

        def Table(self, *args, **kwargs):
            return None

        def UniqueConstraint(self, *args, **kwargs):
            return None

        def Index(self, *args, **kwargs):
            return None

    class UserMixin:
        pass

    def SQLAlchemy(*args, **kwargs):
        return _DummyDb()

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False) # student, teacher, admin, parent, school_admin, researcher
    school = db.Column(db.String(100))
    full_name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    children = db.relationship('User', secondary='parent_student',
                               primaryjoin='User.id==parent_student.c.parent_id',
                               secondaryjoin='User.id==parent_student.c.student_id',
                               backref='parents')

# Association table for Parent-Student relationship
parent_student = db.Table('parent_student',
    db.Column('parent_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('student_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    topics = db.relationship("Topic", backref="subject", lazy=True)

class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    name = db.Column(db.String(100), nullable=False)
    order = db.Column(db.Integer)
    learning_outcomes = db.relationship("LearningOutcome", backref="topic", lazy=True)

class LearningOutcome(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    order = db.Column(db.Integer)
    notes = db.Column(db.Text)
    video_url = db.Column(db.String(200))
    examples = db.Column(db.Text)
    questions = db.relationship("Question", backref="learning_outcome", lazy=True)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'))
    text = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50)) # mcq, concept
    options = db.Column(db.Text) # JSON string of options for MCQ
    correct_answer = db.Column(db.String(200))

class MasteryRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'), nullable=False)
    knowledge_level = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'learning_outcome_id', name='uq_mastery_user_lo'),
        db.Index('ix_mastery_user_lo', 'user_id', 'learning_outcome_id'),
    )

class Evidence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'), nullable=False)
    type = db.Column(db.String(50))
    content = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    teacher_feedback = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_evidence_user', 'user_id'),
    )

class RecommendationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'), nullable=False)
    recommendation = db.Column(db.Text)
    explanation = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_rec_log_user_time', 'user_id', 'timestamp'),
    )

class AttemptLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'), nullable=False)
    correct = db.Column(db.Boolean, nullable=False)
    p_before = db.Column(db.Float, nullable=False)
    p_after = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_attempt_log_user_lo', 'user_id', 'learning_outcome_id'),
    )

class LearningResource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'), nullable=False)
    type = db.Column(db.String(50)) # notes, video, example
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    min_mastery = db.Column(db.Float, default=0.0)
    max_mastery = db.Column(db.Float, default=1.0)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(200))
    resource_type = db.Column(db.String(50))
    resource_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text)
