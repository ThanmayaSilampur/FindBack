import os
import secrets
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort

# Import configurations
from config import (
    BASE_DIR,
    DATABASE_DIR,
    DATABASE_FILE,
    FOUND_UPLOAD_DIR,
    LOST_UPLOAD_DIR,
    ALLOWED_EXTENSIONS,
    MAX_CONTENT_LENGTH,
    SECRET_KEY,
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    LOCKOUT_DURATION,
    MAX_LOGIN_ATTEMPTS,
    MATCH_CANDIDATE_THRESHOLD,
    MAX_MATCH_CANDIDATES,
)

# Import service logic
from services.db_service import (
    get_db_connection as _get_db_connection,
    init_db as _init_db,
    seed_demo_data as _seed_demo_data,
)
from services.auth_service import (
    validate_password,
    normalize_answer,
    hash_answer,
    check_answer,
    is_rate_limited,
    record_failed_attempt,
    clear_rate_limit,
    LOGIN_ATTEMPTS,
)
from services.file_service import (
    allowed_file,
    resolve_image_path,
    save_photo,
)
from services.matching_service import (
    run_matching as _run_matching,
)

# Import route registrars
from routes.auth_routes import register_auth_routes
from routes.item_routes import register_item_routes
from routes.claim_routes import register_claim_routes

# Initialize Flask application
app = Flask(__name__)
app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE=SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
    UPLOAD_FOLDER=str(FOUND_UPLOAD_DIR),
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
)


# Re-export dynamic database and upload wrappers for test & runtime backward compatibility
def get_db_connection(db_file=None):
    """Retrieve an active database connection pointing to current DATABASE_FILE."""
    target = db_file or DATABASE_FILE
    return _get_db_connection(target)


def init_db(db_file=None):
    """Initialize database schema, migrations, and indexes on current DATABASE_FILE."""
    target = db_file or DATABASE_FILE
    return _init_db(target)


def seed_demo_data(db_file=None):
    """Seed demo data on current DATABASE_FILE."""
    target = db_file or DATABASE_FILE
    return _seed_demo_data(target)


def get_upload_dirs():
    """Retrieve the current upload directories."""
    return FOUND_UPLOAD_DIR, LOST_UPLOAD_DIR


def run_matching(item_type, item_id, weights=None):
    """Execute multi-signal candidate matching with active connection factory."""
    return _run_matching(item_type, item_id, db_conn_factory=get_db_connection, weights=weights)


# Built-in CSRF Protection
def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf_token)


@app.before_request
def validate_csrf():
    if not app.config.get('CSRF_ENABLED', True):
        return
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return
    if app.config.get('TESTING') and request.headers.get('X-Skip-CSRF'):
        return
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    expected = session.get('_csrf_token')
    if not token or not expected or not secrets.compare_digest(token, expected):
        abort(400, description='CSRF token missing or invalid.')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# Register modular routes
register_auth_routes(app, get_db_connection)
register_item_routes(app, get_db_connection, login_required, get_upload_dirs, run_matching)
register_claim_routes(app, get_db_connection, login_required)


# Application error handlers
@app.errorhandler(400)
def bad_request(e):
    return render_template('404.html'), 400


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


# Initialize database schema at startup
init_db()

# Demo seeding only if explicitly opted-in
if os.environ.get('SEED_DEMO') == '1':
    seed_demo_data()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
