import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from whitenoise import WhiteNoise

from models import db, User
from config import Config
from security import get_csrf_token

# Import Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.courses import courses_bp
from routes.mastery import mastery_bp
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
from routes.offline import offline_bp

app = Flask(__name__)
app.config.from_object(Config)

# Static files with WhiteNoise
app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/', prefix='static/')

# Database initialization
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.login_view = "auth.login_view"
login_manager.init_app(app)

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
    return {
        "csrf_token": get_csrf_token,
        "role_label": lambda role=None: role_labels.get(role or "", role or ""),
        "current_user": current_user,
    }

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.root_path, "service-worker.js", mimetype="application/javascript")

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# Register Blueprints
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
app.register_blueprint(offline_bp)

if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", True))
