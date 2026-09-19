import re
import time
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash
from config import LOCKOUT_DURATION, MAX_LOGIN_ATTEMPTS

# In-memory login rate limiter
LOGIN_ATTEMPTS = defaultdict(list)


def is_rate_limited(identifier, lockout_duration=LOCKOUT_DURATION, max_attempts=MAX_LOGIN_ATTEMPTS):
    """Check whether an IP or email identifier is currently locked out from logging in."""
    now = time.time()
    valid_attempts = [t for t in LOGIN_ATTEMPTS[identifier] if now - t < lockout_duration]
    LOGIN_ATTEMPTS[identifier] = valid_attempts
    return len(valid_attempts) >= max_attempts


def record_failed_attempt(identifier):
    """Record a timestamped failed login attempt for an identifier."""
    LOGIN_ATTEMPTS[identifier].append(time.time())


def clear_rate_limit(identifier):
    """Reset failed attempts for an identifier upon successful authentication."""
    LOGIN_ATTEMPTS.pop(identifier, None)


def normalize_answer(value):
    """Normalize verification answer for consistent comparison (lowercase, trimmed whitespace)."""
    return ' '.join((value or '').strip().lower().split())


def hash_answer(value):
    """Securely hash normalized verification answer."""
    return generate_password_hash(normalize_answer(value))


def check_answer(stored_answer, user_input):
    """Verify an answer against stored answer (supports hashed answers and legacy plaintext)."""
    if not stored_answer or user_input is None:
        return False
    norm_user = normalize_answer(user_input)
    if stored_answer.startswith(('scrypt:', 'pbkdf2:')):
        return check_password_hash(stored_answer, norm_user)
    # Legacy plaintext backward compatibility
    return normalize_answer(stored_answer) == norm_user


def validate_password(password):
    """Enforce minimum 8 characters with at least one letter and one number."""
    if len(password) < 8:
        return False, 'Password must be at least 8 characters long.'
    if not re.search(r'[A-Za-z]', password):
        return False, 'Password must contain at least one letter.'
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number.'
    return True, ''
