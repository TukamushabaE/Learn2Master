import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_local_env():
    """Load local .env values for command-line scripts when python-dotenv exists."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False

    load_dotenv(os.path.join(BASE_DIR, ".env"))
    return True
