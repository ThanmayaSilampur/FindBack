import os
import sqlite3
import uuid
from functools import wraps
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, flash
from ai.matcher import compute_similarity

app = Flask(__name__)
app.secret_key = 'lostlink-dev-secret-key-change-me'

BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / 'database'
DATABASE_FILE = DATABASE_DIR / 'lostlink.db'
FOUND_UPLOAD_DIR = BASE_DIR / 'private_uploads' / 'found_items'
LOST_UPLOAD_DIR = BASE_DIR / 'private_uploads' / 'lost_items'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_CONTENT_LENGTH = 4 * 1024 * 1024

for d in [DATABASE_DIR, FOUND_UPLOAD_DIR, LOST_UPLOAD_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app.config['UPLOAD_FOLDER'] = str(FOUND_UPLOAD_DIR)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH


def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS found_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            image_path TEXT,
            status TEXT NOT NULL DEFAULT 'Available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS verification_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            found_item_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY(found_item_id) REFERENCES found_items(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS lost_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lost_item_id INTEGER NOT NULL,
            found_item_id INTEGER NOT NULL,
            similarity_score REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Potential Match',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lost_item_id) REFERENCES lost_items(id),
            FOREIGN KEY(found_item_id) REFERENCES found_items(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            found_item_id INTEGER NOT NULL,
            lost_item_id INTEGER NOT NULL,
            claimant_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(found_item_id) REFERENCES found_items(id),
            FOREIGN KEY(lost_item_id) REFERENCES lost_items(id),
            FOREIGN KEY(claimant_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS verification_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claimant_id INTEGER NOT NULL,
            found_item_id INTEGER NOT NULL,
            lost_item_id INTEGER,
            attempts INTEGER NOT NULL DEFAULT 0,
            verified INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(claimant_id) REFERENCES users(id),
            FOREIGN KEY(found_item_id) REFERENCES found_items(id),
            FOREIGN KEY(lost_item_id) REFERENCES lost_items(id)
        )
    ''')

    conn.commit()
    conn.close()


def seed_demo_data():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO users(name, email, password_hash) VALUES (?, ?, ?)',
                  ('Demo User', 'demo@lostlink.local', generate_password_hash('demo123')))
        user_id = c.lastrowid
    else:
        user_id = 1

    c.execute('SELECT COUNT(*) FROM found_items')
    if c.fetchone()[0] == 0:
        c.execute('''
            INSERT INTO found_items(user_id, item_name, category, location, description, image_path, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Available')
        ''', (user_id, 'Black Backpack', 'Bag', 'BVRIT Campus', 'Private description not shown publicly.', ''))
        found_id = c.lastrowid
        c.execute('''
            INSERT INTO verification_questions(found_item_id, question, answer)
            VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)
        ''', (found_id, 'What is attached to the backpack?', 'Red keychain',
              found_id, 'What sticker is inside the backpack?', 'Superman',
              found_id, 'Where is the scratch?', 'Left side'))

    conn.commit()
    conn.close()


init_db()
seed_demo_data()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_photo(file, folder):
    if file is None or file.filename == '':
        return ''
    if not allowed_file(file.filename):
        return ''
    filename = secure_filename(str(uuid.uuid4()) + '_' + file.filename)
    path = folder / filename
    file.save(path)
    return str(path)


def normalize_answer(value):
    return ' '.join((value or '').strip().lower().split())


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not name or not email or not password or not confirm:
            flash('Please complete all registration fields.', 'error')
            return render_template('register.html')
        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        if len(password) < 4:
            flash('Password must be at least 4 characters.', 'error')
            return render_template('register.html')

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE email = ?', (email,))
        if c.fetchone():
            flash('Email already registered.', 'error')
            conn.close()
            return render_template('register.html')

        password_hash = generate_password_hash(password)
        c.execute('INSERT INTO users(name, email, password_hash) VALUES (?, ?, ?)', (name, email, password_hash))
        conn.commit()
        user_id = c.lastrowid
        conn.close()

        session['user_id'] = user_id
        session['user_name'] = name
        flash('Registration successful. Welcome to LostLink!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Email and password are required.', 'error')
            return render_template('login.html')

        conn = get_db_connection()
        c = conn.cursor()
        user = c.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            flash('Login successful.', 'success')
            return redirect(url_for('dashboard'))

        flash('Invalid email or password.', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    conn = get_db_connection()
    found_items = conn.execute('SELECT * FROM found_items WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
    lost_items = conn.execute('SELECT * FROM lost_items WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()

    my_claims = conn.execute('''
        SELECT c.*, fi.item_name as found_item, li.item_name as lost_item
        FROM claims c
        JOIN found_items fi ON fi.id = c.found_item_id
        JOIN lost_items li ON li.id = c.lost_item_id
        WHERE c.claimant_id = ?
        ORDER BY c.id DESC
    ''', (user_id,)).fetchall()

    potential_matches = []
    for lost_item in lost_items:
        rows = conn.execute('''
            SELECT m.*, fi.item_name, fi.category, fi.location, fi.status
            FROM matches m
            JOIN found_items fi ON fi.id = m.found_item_id
            WHERE m.lost_item_id = ?
        ''', (lost_item['id'],)).fetchall()
        potential_matches.extend(rows)

    conn.close()
    return render_template('dashboard.html', found_items=found_items, lost_items=lost_items, potential_matches=potential_matches, my_claims=my_claims)


@app.route('/found')
def found_items():
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM found_items WHERE status != 'Resolved' ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('found_items.html', found_items=items)


@app.route('/found/report', methods=['GET', 'POST'])
@login_required
def report_found():
    if request.method == 'POST':
        item_name = request.form.get('item_name', '').strip()
        category = request.form.get('category', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        photo = request.files.get('photo')

        questions = [
            request.form.get('question1', '').strip(),
            request.form.get('question2', '').strip(),
            request.form.get('question3', '').strip(),
        ]
        answers = [
            request.form.get('answer1', '').strip(),
            request.form.get('answer2', '').strip(),
            request.form.get('answer3', '').strip(),
        ]

        if not item_name or not category or not location or not description or not all(questions) or not all(answers):
            flash('Please complete all found-item fields and all private verification answers.', 'error')
            return render_template('report_found.html')

        photo_path = ''
        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash('Only image files allowed. PNG, JPG, JPEG, GIF, WEBP.', 'error')
                return render_template('report_found.html')
            photo_path = save_photo(photo, FOUND_UPLOAD_DIR)
            if not photo_path:
                flash('Could not store photo.', 'error')
                return render_template('report_found.html')

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO found_items(user_id, item_name, category, location, description, image_path, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Available')
        ''', (session['user_id'], item_name, category, location, description, photo_path))
        found_id = c.lastrowid

        for q, a in zip(questions, answers):
            c.execute('INSERT INTO verification_questions(found_item_id, question, answer) VALUES (?, ?, ?)', (found_id, q, a))

        conn.commit()
        conn.close()

        flash('Found item reported successfully. Private verification questions saved.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('report_found.html')


@app.route('/lost/report', methods=['GET', 'POST'])
@login_required
def report_lost():
    if request.method == 'POST':
        item_name = request.form.get('item_name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        photo = request.files.get('photo')

        if not item_name or not category or not description:
            flash('Please complete all lost-item fields.', 'error')
            return render_template('report_lost.html')

        photo_path = ''
        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash('Only image files are allowed.', 'error')
                return render_template('report_lost.html')
            photo_path = save_photo(photo, LOST_UPLOAD_DIR)
            if not photo_path:
                flash('Could not store photo.', 'error')
                return render_template('report_lost.html')

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO lost_items(user_id, item_name, category, description, image_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (session['user_id'], item_name, category, description, photo_path))
        lost_id = c.lastrowid
        conn.commit()
        conn.close()

        if photo_path:
            found_images = []
            conn = get_db_connection()
            for row in conn.execute('SELECT id, image_path FROM found_items WHERE image_path IS NOT NULL AND image_path != ? ORDER BY id DESC', ('',)).fetchall():
                found_images.append((row['id'], row['image_path']))
            conn.close()

            best_match_id = None
            best_score = 0.0
            for found_id, img_path in found_images:
                score = compute_similarity(photo_path, img_path)
                if score > best_score:
                    best_score = score
                    best_match_id = found_id

            if best_match_id and best_score >= 0.78:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute('INSERT INTO matches(lost_item_id, found_item_id, similarity_score, status) VALUES (?, ?, ?, ?)', (lost_id, best_match_id, best_score, 'Potential Match'))
                conn.commit()
                conn.close()
                flash('Potential Match Found. Please complete ownership verification.', 'success')
            else:
                flash('Lost item submitted. No strong potential match was found.', 'success')
        else:
            flash('Lost item submitted without photo.', 'success')

        return redirect(url_for('dashboard'))

    return render_template('report_lost.html')


@app.route('/start_verification/<int:found_id>', methods=['GET'])
@login_required
def start_verification(found_id):
    conn = get_db_connection()
    found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (found_id,)).fetchone()
    if not found_item:
        conn.close()
        flash('Found item not found.', 'error')
        return redirect(url_for('found_items'))

    c = conn.cursor()
    c.execute('''
        INSERT INTO lost_items(user_id, item_name, category, description, image_path)
        VALUES (?, ?, ?, ?, ?)
    ''', (session['user_id'], found_item['item_name'], found_item['category'], 'Created during no-photo ownership verification.', ''))
    lost_id = c.lastrowid
    conn.commit()
    conn.close()

    return redirect(url_for('verify', found_id=found_id, lost_id=lost_id))


@app.route('/verify/<int:found_id>/<int:lost_id>', methods=['GET', 'POST'])
@login_required
def verify(found_id=None, lost_id=None):
    conn = get_db_connection()
    found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (found_id,)).fetchone()
    lost_item = conn.execute('SELECT * FROM lost_items WHERE id = ?', (lost_id,)).fetchone() if lost_id else None
    questions = conn.execute('SELECT question, answer FROM verification_questions WHERE found_item_id = ?', (found_id,)).fetchall()
    conn.close()

    if not found_item:
        flash('Found item not found.', 'error')
        return redirect(url_for('found_items'))

    if request.method == 'POST':
        answers = [
            request.form.get('q1', '').strip(),
            request.form.get('q2', '').strip(),
            request.form.get('q3', '').strip(),
        ]

        attempts = 0
        conn = get_db_connection()
        c = conn.cursor()
        attempt_row = c.execute('SELECT * FROM verification_sessions WHERE claimant_id = ? AND found_item_id = ? AND lost_item_id = ?', (session.get('user_id'), found_id, lost_id)).fetchone()
        if attempt_row:
            attempts = attempt_row['attempts']
        attempts += 1

        correct = 0
        for idx, q in enumerate(questions):
            if normalize_answer(q['answer']) == normalize_answer(answers[idx]):
                correct += 1

        if correct >= 2:
            if attempt_row:
                c.execute('UPDATE verification_sessions SET attempts = ?, verified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (attempts, attempt_row['id']))
            else:
                c.execute('INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, ?, 1)', (session.get('user_id'), found_id, lost_id, attempts))
            conn.commit()
            conn.close()
            session['verified_found_item_id'] = found_id
            session['verified_lost_item_id'] = lost_id
            return redirect(url_for('verification_success', found_id=found_id, lost_id=lost_id))

        if attempts >= 3:
            if attempt_row:
                c.execute('UPDATE verification_sessions SET attempts = ?, verified = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (attempts, attempt_row['id']))
            else:
                c.execute('INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, ?, 0)', (session.get('user_id'), found_id, lost_id, attempts))
            conn.commit()
            conn.close()
            flash('Verification attempts exhausted.', 'error')
            return render_template('verify.html', found_item=found_item, questions=questions, attempts=attempts, failed=True, exhausted=True, lost_item=lost_item)

        if attempt_row:
            c.execute('UPDATE verification_sessions SET attempts = ?, verified = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (attempts, attempt_row['id']))
        else:
            c.execute('INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, ?, 0)', (session.get('user_id'), found_id, lost_id, attempts))
        conn.commit()
        conn.close()

        remaining = 3 - attempts
        flash(f'Ownership verification failed. Attempts remaining: {remaining}', 'error')
        return render_template('verify.html', found_item=found_item, questions=questions, attempts=attempts, failed=True, lost_item=lost_item)

    return render_template('verify.html', found_item=found_item, questions=questions, attempts=0, failed=False, lost_item=lost_item)


@app.route('/verify/<int:found_id>/<int:lost_id>/success')
@login_required
def verification_success(found_id=None, lost_id=None):
    conn = get_db_connection()
    found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (found_id,)).fetchone()
    lost_item = conn.execute('SELECT * FROM lost_items WHERE id = ?', (lost_id,)).fetchone()
    conn.close()
    return render_template('verification_success.html', found_item=found_item, lost_item=lost_item)


@app.route('/claim/create/<int:found_id>/<int:lost_id>', methods=['POST'])
@login_required
def create_claim(found_id=None, lost_id=None):
    if session.get('verified_found_item_id') != found_id or session.get('verified_lost_item_id') != lost_id:
        flash('Ownership verification is required before creating a claim.', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id FROM claims WHERE found_item_id = ? AND lost_item_id = ? AND claimant_id = ?', (found_id, lost_id, session['user_id']))
    if c.fetchone():
        flash('A claim already exists for this item.', 'error')
        conn.close()
        return redirect(url_for('dashboard'))

    c.execute('INSERT INTO claims(found_item_id, lost_item_id, claimant_id, status) VALUES (?, ?, ?, ?)', (found_id, lost_id, session['user_id'], 'Pending'))
    conn.commit()
    conn.close()

    session.pop('verified_found_item_id', None)
    session.pop('verified_lost_item_id', None)

    flash('Claim submitted successfully. Status: Pending', 'success')
    return redirect(url_for('claims'))


@app.route('/claims')
@login_required
def claims():
    user_id = session['user_id']
    conn = get_db_connection()
    my_claims = conn.execute('''
        SELECT c.*, fi.item_name as found_item, li.item_name as lost_item, fi.user_id as finder_id
        FROM claims c
        JOIN found_items fi ON fi.id = c.found_item_id
        JOIN lost_items li ON li.id = c.lost_item_id
        WHERE c.claimant_id = ?
        ORDER BY c.id DESC
    ''', (user_id,)).fetchall()

    finder_claims = conn.execute('''
        SELECT c.*, fi.item_name as found_item, li.item_name as lost_item, u.name as claimant_name
        FROM claims c
        JOIN found_items fi ON fi.id = c.found_item_id
        JOIN lost_items li ON li.id = c.lost_item_id
        JOIN users u ON u.id = c.claimant_id
        WHERE fi.user_id = ?
        ORDER BY c.id DESC
    ''', (user_id,)).fetchall()
    conn.close()
    return render_template('claims.html', my_claims=my_claims, finder_claims=finder_claims)


@app.route('/claim/<int:claim_id>/accept', methods=['POST'])
@login_required
def accept_claim(claim_id):
    conn = get_db_connection()
    claim = conn.execute('SELECT * FROM claims WHERE id = ?', (claim_id,)).fetchone()
    if not claim:
        conn.close()
        flash('Claim not found.', 'error')
        return redirect(url_for('claims'))

    found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (claim['found_item_id'],)).fetchone()
    if not found_item or found_item['user_id'] != session['user_id']:
        conn.close()
        flash('You are not authorized to accept this claim.', 'error')
        return redirect(url_for('claims'))

    c = conn.cursor()
    c.execute('UPDATE claims SET status = ? WHERE id = ?', ('Approved', claim_id))
    c.execute('UPDATE found_items SET status = ? WHERE id = ?', ('Resolved', claim['found_item_id']))
    conn.commit()
    conn.close()
    flash('Claim accepted. Claim Status: Approved.', 'success')
    return redirect(url_for('claims'))


@app.route('/claim/<int:claim_id>/reject', methods=['POST'])
@login_required
def reject_claim(claim_id):
    conn = get_db_connection()
    claim = conn.execute('SELECT * FROM claims WHERE id = ?', (claim_id,)).fetchone()
    if not claim:
        conn.close()
        flash('Claim not found.', 'error')
        return redirect(url_for('claims'))

    found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (claim['found_item_id'],)).fetchone()
    if not found_item or found_item['user_id'] != session['user_id']:
        conn.close()
        flash('You are not authorized to reject this claim.', 'error')
        return redirect(url_for('claims'))

    c = conn.cursor()
    c.execute('UPDATE claims SET status = ? WHERE id = ?', ('Rejected', claim_id))
    conn.commit()
    conn.close()
    flash('Claim rejected. Claim Status: Rejected.', 'success')
    return redirect(url_for('claims'))


@app.route('/matches')
@login_required
def matches():
    conn = get_db_connection()
    user_id = session['user_id']
    lost_items = conn.execute('SELECT * FROM lost_items WHERE user_id = ?', (user_id,)).fetchall()
    rows = []
    for lost in lost_items:
        mrows = conn.execute('''
            SELECT m.*, fi.item_name as found_item_name, fi.location, fi.category
            FROM matches m
            JOIN found_items fi ON fi.id = m.found_item_id
            WHERE m.lost_item_id = ?
        ''', (lost['id'],)).fetchall()
        rows.extend(mrows)
    conn.close()
    return render_template('matches.html', matches=rows)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
