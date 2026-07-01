from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column('user_id', db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.school_id'))
    full_name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))
    title = db.Column(db.String(100))
    account_status = db.Column(db.String(20), default='Active')
    security_level = db.Column(db.Integer, default=1)
    must_change_password = db.Column(db.Integer, default=0)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.String(50))
    last_login_at = db.Column(db.String(50))
    created_at = db.Column(db.String(50), default=datetime.utcnow().isoformat())

    # Relationships
    role_obj = db.relationship('Role', backref='users', lazy=True)
    school = db.relationship('School', backref='users', lazy=True)

    @property
    def role_name_str(self):
        return self.role_obj.role_name if self.role_obj else 'learner'

    # Flask-Login needs 'role' as a property if templates use current_user.role
    @property
    def role(self):
        return self.role_obj.role_name if self.role_obj else 'learner'

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column('role_id', db.Integer, primary_key=True)
    role_name = db.Column(db.String(20), unique=True, nullable=False)
    display_name = db.Column(db.String(80), nullable=False)

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column('school_id', db.Integer, primary_key=True)
    school_name = db.Column(db.String(100), unique=True, nullable=False)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column('subject_id', db.Integer, primary_key=True)
    subject_name = db.Column(db.String(100), nullable=False)
    topics = db.relationship("Topic", backref="subject", lazy=True)

class Topic(db.Model):
    __tablename__ = 'topics'
    id = db.Column('topic_id', db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'))
    topic_title = db.Column(db.String(100), nullable=False)
    class_level = db.Column(db.String(50))
    learning_outcomes = db.relationship("LearningOutcome", backref="topic", lazy=True)

class LearningOutcome(db.Model):
    __tablename__ = 'learning_outcomes'
    id = db.Column('outcome_id', db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.topic_id'))
    outcome_code = db.Column(db.String(20), nullable=False)
    outcome_name = db.Column(db.String(200), nullable=False)
    outcome_description = db.Column(db.Text)
    mastery_threshold = db.Column(db.Integer, default=80)
    practical_required = db.Column(db.Integer, default=0)
    teacher_review_required = db.Column(db.Integer, default=0)
    sequence_order = db.Column(db.Integer)
    questions = db.relationship("Question", backref="learning_outcome", lazy=True)

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column('question_id', db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('assessments.assessment_id'))
    learning_outcome_id = db.Column('learning_outcome_id', db.Integer, db.ForeignKey('learning_outcomes.outcome_id'))
    question_text = db.Column(db.Text, nullable=False)
    concept_tag = db.Column(db.String(100))
    marks = db.Column(db.Integer, default=1)

class Assessment(db.Model):
    __tablename__ = 'assessments'
    id = db.Column('assessment_id', db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer)
    assessment_title = db.Column(db.String(100))
    assessment_type = db.Column(db.String(20)) # pretest, practice, posttest

class MasteryRecord(db.Model):
    __tablename__ = 'mastery_records'
    id = db.Column('mastery_id', db.Integer, primary_key=True)
    user_id = db.Column('learner_id', db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    learning_outcome_id = db.Column('outcome_id', db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    knowledge_level = db.Column('mastery_score', db.Float, default=0.0)
    mastery_status = db.Column(db.String(20))
    mastery_level = db.Column(db.String(20))
    last_updated = db.Column('updated_at', db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('learner_id', 'outcome_id', name='uq_mastery_user_lo'),
    )

class PracticalEvidence(db.Model):
    __tablename__ = 'practical_evidence'
    id = db.Column('practical_id', db.Integer, primary_key=True)
    user_id = db.Column('learner_id', db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    learning_outcome_id = db.Column('outcome_id', db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    evidence_title = db.Column(db.String(200))
    evidence_description = db.Column(db.Text)
    file_path = db.Column(db.String(200))
    teacher_status = db.Column(db.String(20), default='Pending Review')
    teacher_comment = db.Column(db.Text)
    timestamp = db.Column('created_at', db.DateTime, default=datetime.utcnow)

class Recommendation(db.Model):
    __tablename__ = 'recommendations'
    id = db.Column('recommendation_id', db.Integer, primary_key=True)
    user_id = db.Column('learner_id', db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    outcome_id = db.Column(db.Integer, db.ForeignKey('learning_outcomes.outcome_id'), nullable=False)
    recommendation_reason = db.Column(db.Text)
    recommendation_type = db.Column(db.String(50))
    timestamp = db.Column('created_at', db.DateTime, default=datetime.utcnow)

class AttemptLog(db.Model):
    __tablename__ = 'assessment_attempts'
    id = db.Column('attempt_id', db.Integer, primary_key=True)
    user_id = db.Column('learner_id', db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    assessment_id = db.Column(db.Integer, db.ForeignKey('assessments.assessment_id'), nullable=False)
    score = db.Column(db.Float, default=0.0)
    weak_concepts = db.Column(db.Text)
    timestamp = db.Column('attempted_at', db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column('audit_id', db.Integer, primary_key=True)
    user_id = db.Column('actor_id', db.Integer, db.ForeignKey('users.user_id'))
    action = db.Column(db.String(200))
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.String(50))
    timestamp = db.Column('created_at', db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text)
