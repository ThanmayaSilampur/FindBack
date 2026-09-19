from flask import render_template, request, redirect, url_for, session, flash
from services.auth_service import check_answer


def register_claim_routes(app, get_db_connection, login_required):
    """Register dashboard, matching, verification, and claims management routes."""

    @app.route('/dashboard')
    @login_required
    def dashboard():
        user_id = session.get('user_id')
        conn = get_db_connection()
        found_items = conn.execute('SELECT * FROM found_items WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
        lost_items = conn.execute('SELECT * FROM lost_items WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()

        my_claims = conn.execute('''
            SELECT c.*, fi.item_name as found_item, COALESCE(li.item_name, 'Direct Claim') as lost_item
            FROM claims c
            JOIN found_items fi ON fi.id = c.found_item_id
            LEFT JOIN lost_items li ON li.id = c.lost_item_id
            WHERE c.claimant_id = ?
            ORDER BY c.id DESC
        ''', (user_id,)).fetchall()

        potential_matches = conn.execute('''
            SELECT m.*, fi.item_name, fi.category, fi.location, fi.status, m.match_reasons
            FROM matches m
            JOIN found_items fi ON fi.id = m.found_item_id
            JOIN lost_items li ON li.id = m.lost_item_id
            WHERE li.user_id = ?
            ORDER BY m.similarity_score DESC
        ''', (user_id,)).fetchall()

        conn.close()
        return render_template(
            'dashboard.html',
            found_items=found_items,
            lost_items=lost_items,
            potential_matches=potential_matches,
            my_claims=my_claims
        )

    @app.route('/matches')
    @login_required
    def matches():
        conn = get_db_connection()
        user_id = session['user_id']
        rows = conn.execute('''
            SELECT m.*, fi.item_name as found_item_name, fi.location, fi.category, m.match_reasons
            FROM matches m
            JOIN found_items fi ON fi.id = m.found_item_id
            JOIN lost_items li ON li.id = m.lost_item_id
            WHERE li.user_id = ?
            ORDER BY m.similarity_score DESC
        ''', (user_id,)).fetchall()
        conn.close()
        return render_template('matches.html', matches=rows)

    @app.route('/start_verification/<int:found_id>', methods=['GET'])
    @login_required
    def start_verification(found_id):
        conn = get_db_connection()
        found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (found_id,)).fetchone()
        if not found_item:
            conn.close()
            flash('Found item not found.', 'error')
            return redirect(url_for('found_items'))

        # Link to existing reported lost item in the same category if one exists; otherwise direct claim (lost_id=0)
        user_lost = conn.execute(
            'SELECT id FROM lost_items WHERE user_id = ? AND category = ? ORDER BY id DESC LIMIT 1',
            (session['user_id'], found_item['category'])
        ).fetchone()
        if not user_lost:
            user_lost = conn.execute(
                'SELECT id FROM lost_items WHERE user_id = ? ORDER BY id DESC LIMIT 1',
                (session['user_id'],)
            ).fetchone()
        conn.close()

        lost_id = user_lost['id'] if user_lost else 0
        return redirect(url_for('verify', found_id=found_id, lost_id=lost_id))

    @app.route('/verify/<int:found_id>/<int:lost_id>', methods=['GET', 'POST'])
    @login_required
    def verify(found_id=None, lost_id=None):
        conn = get_db_connection()
        found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (found_id,)).fetchone()
        lost_item = conn.execute('SELECT * FROM lost_items WHERE id = ?', (lost_id,)).fetchone() if (lost_id and lost_id > 0) else None
        questions = conn.execute('SELECT question, answer FROM verification_questions WHERE found_item_id = ?', (found_id,)).fetchall()

        if not found_item:
            conn.close()
            flash('Found item not found.', 'error')
            return redirect(url_for('found_items'))

        template_questions = [{'question': q['question']} for q in questions]

        # Check existing session attempt state
        attempt_row = conn.execute(
            'SELECT * FROM verification_sessions WHERE claimant_id = ? AND found_item_id = ? AND lost_item_id = ?',
            (session['user_id'], found_id, lost_id)
        ).fetchone()

        # If already verified, redirect immediately to claim creation
        if attempt_row and attempt_row['verified'] == 1:
            conn.close()
            session['verified_found_item_id'] = found_id
            session['verified_lost_item_id'] = lost_id
            return redirect(url_for('verification_success', found_id=found_id, lost_id=lost_id))

        attempts = attempt_row['attempts'] if attempt_row else 0

        # If already exhausted, block immediately on both GET and POST
        if attempts >= 3:
            conn.close()
            flash('Verification attempts exhausted.', 'error')
            return render_template(
                'verify.html',
                found_item=found_item,
                questions=template_questions,
                attempts=attempts,
                failed=True,
                exhausted=True,
                lost_item=lost_item
            )

        if request.method == 'POST':
            answers = [
                request.form.get('q1', '').strip(),
                request.form.get('q2', '').strip(),
                request.form.get('q3', '').strip(),
            ]

            attempts += 1
            c = conn.cursor()

            correct = 0
            for idx, q in enumerate(questions):
                if idx < len(answers) and check_answer(q['answer'], answers[idx]):
                    correct += 1

            if correct >= 2:
                if attempt_row:
                    c.execute('UPDATE verification_sessions SET attempts = ?, verified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (attempts, attempt_row['id']))
                else:
                    c.execute('INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, ?, 1)', (session['user_id'], found_id, lost_id, attempts))
                conn.commit()
                conn.close()
                session['verified_found_item_id'] = found_id
                session['verified_lost_item_id'] = lost_id
                return redirect(url_for('verification_success', found_id=found_id, lost_id=lost_id))

            # Failed attempt
            is_exhausted = (attempts >= 3)
            if attempt_row:
                c.execute('UPDATE verification_sessions SET attempts = ?, verified = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (attempts, attempt_row['id']))
            else:
                c.execute('INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, ?, 0)', (session['user_id'], found_id, lost_id, attempts))
            conn.commit()
            conn.close()

            if is_exhausted:
                flash('Verification attempts exhausted.', 'error')
                return render_template(
                    'verify.html',
                    found_item=found_item,
                    questions=template_questions,
                    attempts=attempts,
                    failed=True,
                    exhausted=True,
                    lost_item=lost_item
                )

            remaining = 3 - attempts
            flash(f'Ownership verification failed. Attempts remaining: {remaining}', 'error')
            return render_template(
                'verify.html',
                found_item=found_item,
                questions=template_questions,
                attempts=attempts,
                failed=True,
                exhausted=False,
                lost_item=lost_item
            )

        conn.close()
        return render_template(
            'verify.html',
            found_item=found_item,
            questions=template_questions,
            attempts=attempts,
            failed=(attempts > 0),
            exhausted=False,
            lost_item=lost_item
        )

    @app.route('/verify/<int:found_id>/<int:lost_id>/success')
    @login_required
    def verification_success(found_id=None, lost_id=None):
        conn = get_db_connection()
        found_item = conn.execute('SELECT * FROM found_items WHERE id = ?', (found_id,)).fetchone()
        lost_item = conn.execute('SELECT * FROM lost_items WHERE id = ?', (lost_id,)).fetchone() if (lost_id and lost_id > 0) else None
        conn.close()
        return render_template('verification_success.html', found_item=found_item, lost_item=lost_item)

    @app.route('/claim/create/<int:found_id>/<int:lost_id>', methods=['POST'])
    @login_required
    def create_claim(found_id=None, lost_id=None):
        has_verified_session = (
            session.get('verified_found_item_id') == found_id and
            session.get('verified_lost_item_id') == lost_id
        )
        conn = get_db_connection()
        if not has_verified_session:
            verified_db = conn.execute(
                'SELECT id FROM verification_sessions WHERE claimant_id = ? AND found_item_id = ? AND lost_item_id = ? AND verified = 1',
                (session['user_id'], found_id, lost_id)
            ).fetchone()
            if not verified_db:
                conn.close()
                flash('Ownership verification is required before creating a claim.', 'error')
                return redirect(url_for('dashboard'))

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
            SELECT c.*, fi.item_name as found_item, COALESCE(li.item_name, 'Direct Claim') as lost_item, fi.user_id as finder_id
            FROM claims c
            JOIN found_items fi ON fi.id = c.found_item_id
            LEFT JOIN lost_items li ON li.id = c.lost_item_id
            WHERE c.claimant_id = ?
            ORDER BY c.id DESC
        ''', (user_id,)).fetchall()

        finder_claims = conn.execute('''
            SELECT c.*, fi.item_name as found_item, COALESCE(li.item_name, 'Direct Claim') as lost_item, u.name as claimant_name
            FROM claims c
            JOIN found_items fi ON fi.id = c.found_item_id
            LEFT JOIN lost_items li ON li.id = c.lost_item_id
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
