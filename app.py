import os
import logging
from logging.handlers import RotatingFileHandler
from whitenoise import WhiteNoise
from flask import Flask, redirect, request, render_template, send_from_directory, session, url_for
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from models import db, User, Role, School
from extensions import talisman, limiter

from routes.subjects import subjects_bp
from routes.learning import learning_bp
from routes.student import student_bp
from routes.teacher import teacher_bp
from routes.admin import admin_bp
from routes.framework import framework_bp
from routes.profile import profile_bp
from routes.analytics import analytics_bp
from routes.research import research_bp
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.courses import courses_bp
from routes.mastery import mastery_bp
from config import Config
from security import get_csrf_token

app = Flask(__name__)
app.config.from_object(Config)

# Static files with WhiteNoise
app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/', prefix='static/')

# Security Extensions
talisman.init_app(app, force_https=(not app.debug and not os.environ.get('TESTING')))
limiter.init_app(app)
if os.environ.get('TESTING'):
    limiter.enabled = False
else:
    app.config.setdefault("RATELIMIT_DEFAULT", "200 per day; 50 per hour")

# Production configuration
db_url = os.environ.get('DATABASE_URL')
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
elif not app.config.get('SQLALCHEMY_DATABASE_URI'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.root_path, 'learn2master.db')

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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

# Database initialization
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.login_view = "auth.login_view"
login_manager.init_app(app)

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_security_helpers():
    role_labels = {
        "super_admin": "Super Administrator",
        "school_admin": "School Administrator",
        "teacher": "Teacher",
        "learner": "Learner",
    }
    class MockUser:
        def __init__(self):
            self.is_authenticated = "user_id" in session
            self.username = session.get("username", "")
            self.role = session.get("role", "")
    return {
        "csrf_token": get_csrf_token,
        "role_label": lambda role=None: role_labels.get(role or "", role or ""),
        "current_user": MockUser(),
    }

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.root_path, "service-worker.js", mimetype="application/javascript")

@app.before_request
def enforce_password_change():
    allowed_endpoints = {"auth.change_password", "auth.logout", "static", "service_worker"}
    if (
        session.get("user_id")
        and session.get("must_change_password")
        and request.endpoint not in allowed_endpoints
    ):
        return redirect(url_for("auth.change_password"))

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(courses_bp)
app.register_blueprint(mastery_bp)
app.register_blueprint(teacher_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(student_bp)
app.register_blueprint(subjects_bp)
app.register_blueprint(learning_bp)
app.register_blueprint(framework_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(research_bp)
app.register_blueprint(ai_bp)

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
