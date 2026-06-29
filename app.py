import os
import logging
from logging.handlers import RotatingFileHandler
from functools import wraps
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from whitenoise import WhiteNoise
from werkzeug.security import generate_password_hash, check_password_hash
from engine import calculate_bkt, get_recommendation, AIEngine
from models import db, User, Subject, Topic, LearningOutcome, MasteryRecord, Evidence, RecommendationLog, AttemptLog, LearningResource

app = Flask(__name__)
app.wsgi_app = WhiteNoise(app.wsgi_app, root="static/", prefix="static/")

# Logging Configuration
if not app.debug:
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/learn2master.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Learn2Master startup')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///learn2master.db')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))

db.init_app(app)

@app.template_filter('from_json')
def from_json_filter(s):
    return json.loads(s)

migrate = Migrate(app, db)

# Rate Limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)
csrf = CSRFProtect(app)

# Security Headers
csp = {
    "default-src": ["'self'", "cdn.jsdelivr.net"],
    "script-src": ["'self'", "cdn.jsdelivr.net", "'unsafe-inline'"],
    "style-src": ["'self'", "cdn.jsdelivr.net", "'unsafe-inline'"]
}
if not app.debug:
    Talisman(app, content_security_policy=csp, force_https=True)
else:
    Talisman(app, content_security_policy=csp, force_https=False)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if current_user.role not in roles:
                flash("Access denied.")
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/health')
def health():
    return {"status": "healthy"}, 200


@app.route('/sync/assessments', methods=['POST'])
@login_required
@role_required('student')
def sync_assessments():
    data = request.json
    if not data or 'attempts' not in data:
        return {"error": "Invalid data format"}, 400

    for attempt in data['attempts']:
        lo_id = attempt.get('learning_outcome_id')
        correct = attempt.get('correct')
        timestamp_str = attempt.get('timestamp')

        if not lo_id or correct is None:
            continue

        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        existing = AttemptLog.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id, timestamp=ts).first()
        if existing: continue

        mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
        if not mastery:
            mastery = MasteryRecord(user_id=current_user.id, learning_outcome_id=lo_id, knowledge_level=0.3)
            db.session.add(mastery)

        p_before = mastery.knowledge_level
        new_level, reasoning = calculate_bkt(p_before, correct)
        rec, expl = get_recommendation(new_level)

        log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=f"{expl} | Sync")
        db.session.add(log)

        new_attempt = AttemptLog(user_id=current_user.id, learning_outcome_id=lo_id, correct=correct, p_before=p_before, p_after=new_level, timestamp=ts)
        db.session.add(new_attempt)

        mastery.knowledge_level = new_level

    log_action("Offline synchronization", details=f"Synced {len(data['attempts'])} attempts")
    db.session.commit()
    return {"status": "synced"}, 200


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'student':
        subjects = Subject.query.all()
        # Calculate overall mastery
        masteries = MasteryRecord.query.filter_by(user_id=current_user.id).all()
        avg_mastery = sum([m.knowledge_level for m in masteries]) / len(masteries) if masteries else 0.0

        # Recent activity
        recent_attempts = AttemptLog.query.filter_by(user_id=current_user.id).order_by(AttemptLog.timestamp.desc()).limit(5).all()

        return render_template('student_dashboard.html', subjects=subjects, avg_mastery=avg_mastery, recent_attempts=recent_attempts)
    elif current_user.role == 'teacher':
        return redirect(url_for('teacher_dashboard_home'))
    elif current_user.role == 'admin':
        recent_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
        return render_template('admin_dashboard.html', recent_logs=recent_logs)
    return "Unknown role"

@app.route('/teacher/dashboard')
@login_required
@role_required('teacher')
def teacher_dashboard_home():
    # Student mastery overview
    students = User.query.filter_by(role='student', school=current_user.school).all()
    student_stats = []
    for s in students:
        masteries = MasteryRecord.query.filter_by(user_id=s.id).all()
        avg = sum([m.knowledge_level for m in masteries]) / len(masteries) if masteries else 0.0
        student_stats.append({'user': s, 'avg_mastery': avg})

    # At-risk learners (avg mastery < 0.4)
    at_risk = [s for s in student_stats if s['avg_mastery'] < 0.4]

    return render_template('teacher_dashboard.html', student_stats=student_stats, at_risk=at_risk)


@app.route('/subject/<int:subject_id>')
@login_required
@role_required('student', 'teacher', 'admin')
def view_subject(subject_id):
    subject = db.get_or_404(Subject, subject_id)
    return render_template('subject.html', subject=subject)

@app.route('/learning_outcome/<int:lo_id>')
@login_required
@role_required('student', 'teacher', 'admin')
def view_lo(lo_id):
    lo = db.get_or_404(LearningOutcome, lo_id)

    # Check for sequential locking (only for students)
    is_locked = False
    if current_user.role == 'student':
        previous_los = LearningOutcome.query.filter(
            LearningOutcome.topic_id == lo.topic_id,
            LearningOutcome.order < lo.order
        ).all()

        for prev_lo in previous_los:
            prev_mastery = MasteryRecord.query.filter_by(
                user_id=current_user.id,
                learning_outcome_id=prev_lo.id
            ).first()
            if not prev_mastery or prev_mastery.knowledge_level < 0.85:
                is_locked = True
                break

    mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
    knowledge_level = mastery.knowledge_level if mastery else 0.0

    # Adaptive resource selection
    resources = LearningResource.query.filter(
        LearningResource.learning_outcome_id == lo_id,
        LearningResource.min_mastery <= knowledge_level,
        LearningResource.max_mastery >= knowledge_level
    ).all()

    rec, expl = get_recommendation(knowledge_level)
    return render_template('learning_outcome.html', lo=lo, knowledge_level=knowledge_level, recommendation=rec, explanation=expl, is_locked=is_locked, resources=resources)


@app.route('/lo/<int:lo_id>/quiz', methods=['GET', 'POST'])
@login_required
@role_required('student')
def take_quiz(lo_id):
    lo = db.get_or_404(LearningOutcome, lo_id)
    questions = Question.query.filter_by(learning_outcome_id=lo_id).all()

    if request.method == 'POST':
        correct_count = 0
        total = len(questions)
        if total == 0:
            flash('No questions available for this learning outcome.', 'warning')
            return redirect(url_for('view_lo', lo_id=lo_id))

        for q in questions:
            answer = request.form.get(f'question_{q.id}')
            if answer == q.correct_answer:
                correct_count += 1

        is_correct = (correct_count / total) >= 0.7

        mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
        if not mastery:
            mastery = MasteryRecord(user_id=current_user.id, learning_outcome_id=lo_id, knowledge_level=0.3)
            db.session.add(mastery)

        p_before = mastery.knowledge_level
        new_level, reasoning = calculate_bkt(p_before, is_correct)
        rec, expl = get_recommendation(new_level)

        full_explanation = f"{expl} | Quiz Score: {correct_count}/{total} | AI: {reasoning['message']}"
        log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=full_explanation)
        db.session.add(log)

        attempt = AttemptLog(user_id=current_user.id, learning_outcome_id=lo_id, correct=is_correct, p_before=p_before, p_after=new_level)
        db.session.add(attempt)

        mastery.knowledge_level = new_level
        db.session.commit()

        flash(f'Quiz completed! You got {correct_count} out of {total} correct.', 'success')
        return redirect(url_for('view_lo', lo_id=lo_id))

    return render_template('quiz.html', lo=lo, questions=questions)

    correct = correct_val == 'true'
    mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()

    # Initialize with p_init if not exists
    if not mastery:
        p_init = 0.3 # BKT default
        mastery = MasteryRecord(user_id=current_user.id, learning_outcome_id=lo_id, knowledge_level=p_init)
        db.session.add(mastery)

    p_before = mastery.knowledge_level
    new_level, reasoning = calculate_bkt(p_before, correct)
    rec, expl = get_recommendation(new_level)

    # Enrich explanation with AI reasoning for XAI
    full_explanation = f"{expl} | AI Insight: {reasoning['message']}"

    log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=full_explanation)
    db.session.add(log)

    attempt = AttemptLog(
        user_id=current_user.id,
        learning_outcome_id=lo_id,
        correct=correct,
        p_before=p_before,
        p_after=new_level
    )
    db.session.add(attempt)

    mastery.knowledge_level = new_level
    db.session.commit()
    return redirect(url_for('view_lo', lo_id=lo_id))

@app.route('/teacher/evidence')
@login_required
@role_required('teacher')
def teacher_evidence():
    # Filter by teacher's school for basic multi-tenancy support
    evidences = Evidence.query.join(User).filter(User.school == current_user.school).all()
    return render_template('teacher_evidence.html', evidences=evidences)

@app.route('/teacher/recommendations')
@login_required
@role_required('teacher')
def teacher_recommendations():
    logs = RecommendationLog.query.join(User).filter(User.school == current_user.school).order_by(RecommendationLog.timestamp.desc()).limit(100).all()
    return render_template('teacher_recommendations.html', logs=logs)

@app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/lo/<int:lo_id>/evidence', methods=['POST'])
@login_required
@role_required('student')
def submit_evidence(lo_id):
    content = request.form.get('content')
    if not content or len(content.strip()) == 0:
        flash('Evidence content cannot be empty')
        return redirect(url_for('view_lo', lo_id=lo_id))
    evidence_type = request.form.get('type', 'text')

    evidence = Evidence(
        user_id=current_user.id,
        learning_outcome_id=lo_id,
        type=evidence_type,
        content=content,
        status='pending'
    )
    db.session.add(evidence)
    db.session.commit()
    flash("Evidence submitted successfully and is awaiting teacher review.")
    return redirect(url_for('view_lo', lo_id=lo_id))


@app.route('/teacher/evidence/<int:evidence_id>/review', methods=['POST'])
@login_required
@role_required('teacher')
def review_evidence(evidence_id):
    evidence = db.get_or_404(Evidence, evidence_id)
    # Security: Ensure student is in the same school as teacher
    if evidence.user.school != current_user.school:
        flash('Unauthorized access to evidence.')
        return redirect(url_for('teacher_evidence'))

    status = request.form.get('status')
    if status not in ['approved', 'rejected']:
        flash('Invalid status')
        return redirect(url_for('teacher_evidence'))
    feedback = request.form.get('feedback')

    evidence.status = status
    evidence.teacher_feedback = feedback

    if status == 'approved':
        mastery = MasteryRecord.query.filter_by(
            user_id=evidence.user_id,
            learning_outcome_id=evidence.learning_outcome_id
        ).first()
        if not mastery:
            mastery = MasteryRecord(user_id=evidence.user_id, learning_outcome_id=evidence.learning_outcome_id)
            db.session.add(mastery)
        mastery.knowledge_level = 0.99

    log_action(f"Evidence {status}", resource_type="Evidence", resource_id=evidence.id, details=f"Student ID: {evidence.user_id}")
    db.session.commit()
    flash(f"Evidence {status} successfully.")
    return redirect(url_for('teacher_evidence'))

    feedback = request.form.get('feedback')

    evidence.status = status
    evidence.teacher_feedback = feedback

    # If approved, boost mastery to 1.0 (or 0.99)
    if status == 'approved':
        mastery = MasteryRecord.query.filter_by(
            user_id=evidence.user_id,
            learning_outcome_id=evidence.learning_outcome_id
        ).first()
        if not mastery:
            mastery = MasteryRecord(user_id=evidence.user_id, learning_outcome_id=evidence.learning_outcome_id)
            db.session.add(mastery)
        mastery.knowledge_level = 0.99

    db.session.commit()
    flash(f"Evidence {status} successfully.")
    return redirect(url_for('teacher_evidence'))

@app.route('/student/progress')
@login_required
@role_required('student')
def view_progress():
    attempts = AttemptLog.query.filter_by(user_id=current_user.id).order_by(AttemptLog.timestamp.desc()).all()
    return render_template('progress.html', attempts=attempts)



from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    role = SelectField('Role', choices=[('student', 'Student'), ('teacher', 'Teacher'), ('parent', 'Parent')], validators=[DataRequired()])
    school = StringField('School', validators=[DataRequired()])
    submit = SubmitField('Sign Up')

class ProfileForm(FlaskForm):
    full_name = StringField('Full Name', validators=[Length(max=120)])
    bio = TextAreaField('Bio', validators=[Length(max=500)])
    submit = SubmitField('Update Profile')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password, role=form.role.data, school=form.school.data)
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data
        current_user.bio = form.bio.data
        db.session.commit()
        flash('Your profile has been updated!', 'success')
        return redirect(url_for('profile'))
    elif request.method == 'GET':
        form.full_name.data = current_user.full_name
        form.bio.data = current_user.bio
    return render_template('profile.html', form=form)

@app.route('/admin/audit')
@login_required
@role_required('admin')
def admin_audit():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(100).all()
    return render_template('admin_audit.html', logs=logs)

def log_action(action, resource_type=None, resource_id=None, details=None):
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.session.add(log)
    db.session.commit()
import csv
import io
from flask import make_response

@app.route('/student/report/export')
@login_required
@role_required('student')
def export_student_report():
    attempts = AttemptLog.query.filter_by(user_id=current_user.id).order_by(AttemptLog.timestamp.desc()).all()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Timestamp', 'Learning Outcome', 'Result', 'Mastery Before', 'Mastery After'])
    for a in attempts:
        cw.writerow([a.timestamp, a.learning_outcome.name, 'Correct' if a.correct else 'Incorrect', a.p_before, a.p_after])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=my_progress_report.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/admin/report/usage')
@login_required
@role_required('admin')
def admin_usage_report():
    # Simple aggregation for admin
    total_users = User.query.count()
    total_attempts = AttemptLog.query.count()
    total_evidence = Evidence.query.count()

    return render_template('admin_report.html', total_users=total_users, total_attempts=total_attempts, total_evidence=total_evidence)

@app.route('/ai/tutor', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def ai_tutor():
    user_input = request.json.get('message', '')

    # Security: Input validation
    if not isinstance(user_input, str) or not user_input.strip():
        return {"response": "I didn't quite catch that. Could you please rephrase your question?"}, 400

    if len(user_input) > 1000:
        return {"response": "That's a very long question! Could you please shorten it so I can assist you better?"}, 400

    # Gather rich context for the AI Engine
    mastery_records = MasteryRecord.query.filter_by(user_id=current_user.id).all()
    avg_mastery = sum([m.knowledge_level for m in mastery_records]) / len(mastery_records) if mastery_records else 0.0
    recent = AttemptLog.query.filter_by(user_id=current_user.id).order_by(AttemptLog.timestamp.desc()).first()
    gaps = AIEngine.analyze_knowledge_gaps(mastery_records)

    context = {
        "username": current_user.username.capitalize(),
        "avg_mastery": float(avg_mastery),
        "recent_activity": recent,
        "gaps": gaps
    }

    response_text = AIEngine.tutor_response(user_input.strip(), context)
    return {"response": response_text}

@app.route('/researcher/dashboard')
@login_required
@role_required('researcher', 'admin')
def researcher_dashboard():
    # Cohort-level metrics
    subjects = Subject.query.all()
    stats = []
    for sub in subjects:
        lo_ids = [lo.id for t in sub.topics for lo in t.learning_outcomes]
        if not lo_ids: continue
        masteries = MasteryRecord.query.filter(MasteryRecord.learning_outcome_id.in_(lo_ids)).all()
        avg_m = sum([m.knowledge_level for m in masteries]) / len(masteries) if masteries else 0.0
        stats.append({'subject': sub.name, 'avg_mastery': avg_m, 'total_records': len(masteries)})

    return render_template('researcher_dashboard.html', stats=stats)
# End of app.py


@app.route('/admin/schools')
@login_required
@role_required('admin')
def admin_schools():
    # Placeholder for school management
    schools = db.session.query(User.school).distinct().all()
    return render_template('admin_schools.html', schools=[s[0] for s in schools if s[0]])

@app.route('/admin/curriculum')
@login_required
@role_required('admin')
def admin_curriculum():
    subjects = Subject.query.all()
    return render_template('admin_curriculum.html', subjects=subjects)

@app.route('/admin/competencies')
@login_required
@role_required('admin')
def admin_competencies():
    # In CBC, competencies are often mapped to Learning Outcomes
    outcomes = LearningOutcome.query.all()
    return render_template('admin_competencies.html', outcomes=outcomes)

@app.route('/admin/settings')
@login_required
@role_required('admin')
def admin_settings():
    return render_template('admin_settings.html')

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true', port=int(os.environ.get('PORT', 5000)))