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

class Role(db.Model):
    __tablename__ = 'roles'
    role_id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100))

class School(db.Model):
    __tablename__ = 'schools'
    school_id = db.Column(db.Integer, primary_key=True)
    school_name = db.Column(db.String(100), nullable=False)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(128), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.school_id'))
    must_change_password = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Simplified role property for compatibility
    @property
    def role(self):
        role_obj = db.session.get(Role, self.role_id)
        return role_obj.role_name if role_obj else None

    @property
    def id(self):
        return self.user_id

    def get_id(self):
        return str(self.user_id)

class Subject(db.Model):
    __tablename__ = 'subjects'
    subject_id = db.Column(db.Integer, primary_key=True)
    subject_name = db.Column(db.String(100), nullable=False)

class Topic(db.Model):
    __tablename__ = 'topics'
    topic_id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'), nullable=False)
    topic_name = db.Column(db.String(100), nullable=False)

class LearningOutcome(db.Model):
    __tablename__ = 'learning_outcomes'
    outcome_id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.topic_id'), nullable=False)
    outcome_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

class MasteryRecord(db.Model):
    __tablename__ = 'mastery_records'
    mastery_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    knowledge_level = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class PracticalEvidence(db.Model):
    __tablename__ = 'practical_evidence'
    practical_id = db.Column(db.Integer, primary_key=True)
    learner_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    evidence_title = db.Column(db.String(255), nullable=False)
    teacher_status = db.Column(db.String(50), default='Pending Review')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BKTMastery(db.Model):
    __tablename__ = 'bkt_mastery'
    bkt_id = db.Column(db.Integer, primary_key=True)
    learner_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    concept_tag = db.Column(db.String(100), nullable=False)
    probability_mastery = db.Column(db.Float, default=0.20)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
