import os
from dotenv import load_dotenv

try:
    from dotenv import load_dotenv
except ImportError:  # Keeps the prototype runnable before dependencies are installed.
    load_dotenv = None

if load_dotenv:
    load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

class Config:
    SECRET_KEY = os.environ.get("LEARN2MASTER_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-only-change-me"
    DEBUG = os.environ.get("LEARN2MASTER_DEBUG", "0").lower() in {"1", "true", "yes", "on"}

    # Session Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = not DEBUG
    MAX_CONTENT_LENGTH = int(os.environ.get("LEARN2MASTER_MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
    CSRF_ENABLED = os.environ.get("LEARN2MASTER_CSRF_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
    UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt", ".doc", ".docx", ".py", ".zip"}

    # Database - Supports SQLite default or Supabase/PostgreSQL via DATABASE_URL
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    if not SQLALCHEMY_DATABASE_URI:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'learn2master.db')}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # AI Configuration
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    HF_TOKEN = os.environ.get("HF_TOKEN")
    TRAINING_API_URL = os.environ.get("TRAINING_API_URL")

    # Supabase Integration (for additional cloud features if needed)
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
