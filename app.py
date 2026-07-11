import os
import logging
from logging.handlers import RotatingFileHandler
from whitenoise import WhiteNoise
from flask import Flask, redirect, request, render_template, send_from_directory, session, url_for
from flask_login import LoginManager, current_user
from models import db, User, Role, School
from extensions import talisman, limiter

try:
    from flask_migrate import Migrate
except ImportError:
    class Migrate:
        def __init__(self, *args, **kwargs):
            pass

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
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.courses import courses_bp
from routes.mastery import mastery_bp
from config import Config
from security import get_csrf_token
from database import is_postgres_url, normalize_database_url, sqlite_path_from_url

app = Flask(__name__)
app.config.from_object(Config)

# Static files with WhiteNoise
app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/', prefix='static/')

# Security Extensions
csp = {
    'default-src': '\'self\'',
    'style-src': [
        '\'self\'',
        'fonts.googleapis.com',
        '\'unsafe-inline\''
    ],
    'font-src': [
        '\'self\'',
        'fonts.gstatic.com'
    ],
    'script-src': [
        '\'self\'',
        '\'unsafe-inline\''  # Required for some inline scripts in templates
    ],
    'img-src': ['\'self\'', 'data:']
}
talisman.init_app(
    app,
    force_https=(app.config.get("FORCE_HTTPS", False) and not os.environ.get("TESTING")),
    content_security_policy=csp
)
limiter.init_app(app)
if os.environ.get('TESTING'):
    limiter.enabled = False
else:
    app.config.setdefault("RATELIMIT_DEFAULT", "200 per day; 50 per hour")

# Production configuration
db_url = normalize_database_url(os.environ.get('DATABASE_URL'))
if db_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
elif not app.config.get('SQLALCHEMY_DATABASE_URI'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.root_path, 'learn2master.db')

# Note: SECRET_KEY is now managed via Config class in config.py
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

# Automatic database initialization check
with app.app_context():
    from database import get_db
    import init_db
    try:
        conn = get_db()
        # Attempt a simple query to see if the database is initialized
        conn.execute("SELECT 1 FROM users LIMIT 1")
        conn.close()
    except Exception:
        app.logger.info("Database tables appear to be missing. Initializing...")
        db_url = normalize_database_url(os.environ.get("DATABASE_URL"))
        if is_postgres_url(db_url):
            init_db.run_postgres(db_url)
        else:
            init_db.run_sqlite(db_path=sqlite_path_from_url(db_url))
        app.logger.info("Database initialization complete.")

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


@app.errorhandler(404)
def not_found(error):
    return ("404 - Page not found", 404) if app.config.get("TESTING") else (render_template("errors/404.html"), 404)


@app.errorhandler(500)
def server_error(error):
    return ("500 - Server error", 500) if app.config.get("TESTING") else (render_template("errors/500.html"), 500)


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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=app.config["DEBUG"])
