from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from services.auth_service import (
    validate_password,
    is_rate_limited,
    record_failed_attempt,
    clear_rate_limit,
)


def register_auth_routes(app, get_db_connection):
    """Register authentication routes on the Flask app."""

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

            valid, error_msg = validate_password(password)
            if not valid:
                flash(error_msg, 'error')
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
            flash('Registration successful. Welcome to FindBack!', 'success')
            return redirect(url_for('dashboard'))

        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            client_ip = request.remote_addr or 'unknown'

            if is_rate_limited(client_ip) or (email and is_rate_limited(email)):
                flash('Too many failed login attempts. Please wait 15 minutes before trying again.', 'error')
                return render_template('login.html'), 429

            if not email or not password:
                flash('Email and password are required.', 'error')
                return render_template('login.html')

            conn = get_db_connection()
            c = conn.cursor()
            user = c.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            conn.close()

            if user and check_password_hash(user['password_hash'], password):
                clear_rate_limit(client_ip)
                clear_rate_limit(email)
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                flash('Login successful.', 'success')
                return redirect(url_for('dashboard'))

            record_failed_attempt(client_ip)
            if email:
                record_failed_attempt(email)
            flash('Invalid email or password.', 'error')

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        flash('You have been logged out.', 'success')
        return redirect(url_for('login'))
