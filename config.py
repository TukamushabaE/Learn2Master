import os


class Config:
    SECRET_KEY = os.environ.get("LEARN2MASTER_SECRET_KEY", "dev-only-change-me")
    DEBUG = os.environ.get("LEARN2MASTER_DEBUG", "0").lower() in {"1", "true", "yes", "on"}
    MAX_CONTENT_LENGTH = int(os.environ.get("LEARN2MASTER_MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
    CSRF_ENABLED = os.environ.get("LEARN2MASTER_CSRF_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
    UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt", ".doc", ".docx", ".py", ".zip"}
