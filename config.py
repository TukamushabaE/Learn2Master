import os

from env_loader import load_local_env

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_local_env()


def env_flag(name, default="0"):
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}

class Config:
    SECRET_KEY = os.environ.get("LEARN2MASTER_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-only-change-me"
    DEBUG = env_flag("LEARN2MASTER_DEBUG")
    FORCE_HTTPS = env_flag("LEARN2MASTER_FORCE_HTTPS")

    # Session Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = env_flag(
        "LEARN2MASTER_SESSION_COOKIE_SECURE",
        "1" if FORCE_HTTPS else "0",
    )
    MAX_CONTENT_LENGTH = int(os.environ.get("LEARN2MASTER_MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
    CSRF_ENABLED = os.environ.get("LEARN2MASTER_CSRF_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
    UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt", ".doc", ".docx", ".py", ".zip"}

    # Database - Supports SQLite default or Supabase/PostgreSQL via DATABASE_URL
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    if not SQLALCHEMY_DATABASE_URI:
        sqlite_path = os.environ.get("LEARN2MASTER_SQLITE_PATH") or os.path.join(BASE_DIR, "learn2master.db")
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:" if sqlite_path == ":memory:" else f"sqlite:///{sqlite_path}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # AI Configuration
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    HF_TOKEN = os.environ.get("HF_TOKEN")
    TRAINING_API_URL = os.environ.get("TRAINING_API_URL")

    # Supabase Integration (for additional cloud features if needed)
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
