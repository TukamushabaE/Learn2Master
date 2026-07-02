from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column('user_id', db.Integer, primary_key=True)
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
    db.Column('parent_id', db.Integer, db.ForeignKey('users.user_id'), primary_key=True),
    db.Column('student_id', db.Integer, db.ForeignKey('users.user_id'), primary_key=True)
)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column('subject_id', db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    topics = db.relationship("Topic", backref="subject", lazy=True)

class Topic(db.Model):
    __tablename__ = 'topics'
    id = db.Column('topic_id', db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'))
    name = db.Column(db.String(100), nullable=False)
    order = db.Column(db.Integer)
    learning_outcomes = db.relationship("LearningOutcome", backref="topic", lazy=True)

class LearningOutcome(db.Model):
    __tablename__ = 'learning_outcomes'
    id = db.Column('outcome_id', db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.topic_id'))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    order = db.Column(db.Integer)
    notes = db.Column(db.Text)
    video_url = db.Column(db.String(200))
    examples = db.Column(db.Text)
    questions = db.relationship("Question", backref="learning_outcome", lazy=True)

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column('question_id', db.Integer, primary_key=True)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'))
    text = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50)) # mcq, concept
    options = db.Column(db.Text) # JSON string of options for MCQ
    correct_answer = db.Column(db.String(200))

class MasteryRecord(db.Model):
    __tablename__ = 'mastery_records'
    id = db.Column('mastery_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    knowledge_level = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'learning_outcome_id', name='uq_mastery_user_lo'),

    )

class Evidence(db.Model):
    __tablename__ = 'evidence_portfolio'
    id = db.Column('evidence_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    type = db.Column(db.String(50))
    content = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    teacher_feedback = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (

    )

class RecommendationLog(db.Model):
    __tablename__ = 'recommendations'
    id = db.Column('recommendation_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    recommendation = db.Column(db.Text)
    explanation = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (

    )

class AttemptLog(db.Model):
    __tablename__ = 'assessment_attempts'
    id = db.Column('attempt_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    correct = db.Column(db.Boolean, nullable=False)
    p_before = db.Column(db.Float, nullable=False)
    p_after = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (

    )

class LearningResource(db.Model):
    __tablename__ = 'learning_resources'
    id = db.Column('resource_id', db.Integer, primary_key=True)
    learning_outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    type = db.Column(db.String(50)) # notes, video, example
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    min_mastery = db.Column(db.Float, default=0.0)
    max_mastery = db.Column(db.Float, default=1.0)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column('audit_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    action = db.Column(db.String(200))
    resource_type = db.Column(db.String(50))
    resource_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text)


class StudentSubjectAssignment(db.Model):
    __tablename__ = 'student_subject_assignments'
    id = db.Column('assignment_id', db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

class TeacherKBUpload(db.Model):
    __tablename__ = 'teacher_kb_uploads'
    id = db.Column('upload_id', db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_size_bytes = db.Column(db.Integer, nullable=False)
    summary_size_bytes = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
