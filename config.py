import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / 'database'
DATABASE_FILE = DATABASE_DIR / 'lostlink.db'
FOUND_UPLOAD_DIR = BASE_DIR / 'private_uploads' / 'found_items'
LOST_UPLOAD_DIR = BASE_DIR / 'private_uploads' / 'lost_items'

# File upload security
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB

# Application secrets and session cookies
SECRET_KEY = os.environ.get('SECRET_KEY') or 'findback-local-dev-secret-key-change-in-production'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = bool(os.environ.get('SESSION_COOKIE_SECURE', False))

# Rate limiting
LOCKOUT_DURATION = 15 * 60  # 15 minutes
MAX_LOGIN_ATTEMPTS = 5

# Matching thresholds
MATCH_CANDIDATE_THRESHOLD = 0.35
MAX_MATCH_CANDIDATES = 5

# Ensure required storage directories exist
for directory in [DATABASE_DIR, FOUND_UPLOAD_DIR, LOST_UPLOAD_DIR]:
    directory.mkdir(parents=True, exist_ok=True)
