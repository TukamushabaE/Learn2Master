from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False) # student, teacher, admin
    school = db.Column(db.String(100))
    # Indices are implicitly created for unique=True

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

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcome.id'))
    text = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50)) # mcq, concept
    options = db.Column(db.Text)
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
