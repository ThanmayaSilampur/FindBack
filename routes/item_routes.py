from pathlib import Path
from flask import render_template, request, redirect, url_for, session, flash, abort, send_from_directory
from ai.matcher import compute_image_hash
from services.auth_service import hash_answer
from services.file_service import save_photo, resolve_image_path


def register_item_routes(app, get_db_connection, login_required, get_upload_dirs, run_matching):
    """Register item catalog, reporting, and image access routes."""

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/found')
    def found_items():
        query = request.args.get('q', '').strip()
        category = request.args.get('category', '').strip()
        location = request.args.get('location', '').strip()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()

        conn = get_db_connection()

        # Retrieve distinct non-empty categories
        cat_rows = conn.execute(
            "SELECT DISTINCT category FROM found_items WHERE category IS NOT NULL AND TRIM(category) != '' ORDER BY category ASC"
        ).fetchall()
        default_cats = ['Electronics', 'Keys', 'Wallets & Bags', 'Documents & IDs', 'Jewelry', 'Clothing', 'Accessories', 'Other']
        db_cats = [r['category'] for r in cat_rows if r['category']]
        all_categories = sorted(list(set(default_cats + db_cats)))

        # Dynamically build filter query
        sql = "SELECT * FROM found_items WHERE status != 'Resolved'"
        params = []

        if query:
            sql += " AND (item_name LIKE ? OR description LIKE ?)"
            term = f"%{query}%"
            params.extend([term, term])
        if category:
            sql += " AND category = ?"
            params.append(category)
        if location:
            sql += " AND location LIKE ?"
            params.append(f"%{location}%")
        if date_from:
            sql += " AND DATE(created_at) >= DATE(?)"
            params.append(date_from)
        if date_to:
            sql += " AND DATE(created_at) <= DATE(?)"
            params.append(date_to)

        sql += " ORDER BY id DESC"
        items = conn.execute(sql, params).fetchall()
        conn.close()

        filters_active = bool(query or category or location or date_from or date_to)

        return render_template(
            'found_items.html',
            found_items=items,
            categories=all_categories,
            query=query,
            selected_category=category,
            selected_location=location,
            date_from=date_from,
            date_to=date_to,
            filters_active=filters_active,
            total_count=len(items)
        )

    @app.route('/found/<int:item_id>')
    @app.route('/item/<int:item_id>')
    def item_detail(item_id):
        conn = get_db_connection()
        item = conn.execute('SELECT * FROM found_items WHERE id = ?', (item_id,)).fetchone()
        if not item:
            conn.close()
            flash('Found item not found.', 'error')
            return redirect(url_for('found_items'))

        q_count_row = conn.execute(
            'SELECT COUNT(*) as cnt FROM verification_questions WHERE found_item_id = ?',
            (item_id,)
        ).fetchone()
        question_count = q_count_row['cnt'] if q_count_row else 0

        current_user_id = session.get('user_id')
        is_finder = (current_user_id is not None and current_user_id == item['user_id'])

        user_claim = None
        if current_user_id:
            user_claim = conn.execute(
                'SELECT * FROM claims WHERE found_item_id = ? AND claimant_id = ? ORDER BY id DESC LIMIT 1',
                (item_id, current_user_id)
            ).fetchone()

        conn.close()
        return render_template(
            'item_detail.html',
            item=item,
            question_count=question_count,
            is_finder=is_finder,
            user_claim=user_claim
        )

    @app.route('/found/report', methods=['GET', 'POST'])
    @login_required
    def report_found():
        found_dir, _ = get_upload_dirs()
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
            photo_hash = ''
            if photo and photo.filename:
                photo_path = save_photo(photo, found_dir)
                if photo_path is None:
                    flash('Only valid image files (PNG, JPG, JPEG, GIF, WEBP) under 4MB are allowed.', 'error')
                    return render_template('report_found.html')
                full_photo_path = resolve_image_path(photo_path, found_dir)
                if full_photo_path:
                    photo_hash = compute_image_hash(full_photo_path)

            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''
                INSERT INTO found_items(user_id, item_name, category, location, description, image_path, image_hash, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Available')
            ''', (session['user_id'], item_name, category, location, description, photo_path, photo_hash))
            found_id = c.lastrowid

            for q, a in zip(questions, answers):
                c.execute('INSERT INTO verification_questions(found_item_id, question, answer) VALUES (?, ?, ?)', (found_id, q, hash_answer(a)))

            conn.commit()
            conn.close()

            # Bidirectional matching
            detected_matches = run_matching('found', found_id)
            if detected_matches:
                flash(f'Found item reported successfully. Detected {len(detected_matches)} potential matching lost item(s)!', 'success')
            else:
                flash('Found item reported successfully. Private verification questions saved.', 'success')

            return redirect(url_for('dashboard'))

        return render_template('report_found.html')

    @app.route('/lost/report', methods=['GET', 'POST'])
    @login_required
    def report_lost():
        _, lost_dir = get_upload_dirs()
        if request.method == 'POST':
            item_name = request.form.get('item_name', '').strip()
            category = request.form.get('category', '').strip()
            location = request.form.get('location', '').strip()
            description = request.form.get('description', '').strip()
            photo = request.files.get('photo')

            if not item_name or not category or not description:
                flash('Please complete all lost-item fields.', 'error')
                return render_template('report_lost.html')

            photo_path = ''
            photo_hash = ''
            if photo and photo.filename:
                photo_path = save_photo(photo, lost_dir)
                if photo_path is None:
                    flash('Only valid image files (PNG, JPG, JPEG, GIF, WEBP) under 4MB are allowed.', 'error')
                    return render_template('report_lost.html')
                full_photo_path = resolve_image_path(photo_path, lost_dir)
                if full_photo_path:
                    photo_hash = compute_image_hash(full_photo_path)

            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''
                INSERT INTO lost_items(user_id, item_name, category, description, image_path, location, image_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], item_name, category, description, photo_path, location, photo_hash))
            lost_id = c.lastrowid
            conn.commit()
            conn.close()

            # Bidirectional matching
            detected_matches = run_matching('lost', lost_id)
            if detected_matches:
                flash(f'Lost item submitted. Detected {len(detected_matches)} potential match candidate(s)! Please verify ownership on your dashboard.', 'success')
            else:
                flash('Lost item submitted successfully.', 'success')

            return redirect(url_for('dashboard'))

        return render_template('report_lost.html')

    @app.route('/image/<item_type>/<int:item_id>')
    @login_required
    def serve_item_image(item_type, item_id):
        """Safely serve item images with authorization and path traversal prevention."""
        if item_type not in ('found', 'lost'):
            abort(404)

        conn = get_db_connection()
        table = 'found_items' if item_type == 'found' else 'lost_items'
        item = conn.execute(f'SELECT * FROM {table} WHERE id = ?', (item_id,)).fetchone()
        conn.close()

        if not item or not item['image_path']:
            abort(404)

        found_dir, lost_dir = get_upload_dirs()
        upload_dir = found_dir if item_type == 'found' else lost_dir
        raw_path = Path(item['image_path'])

        # Determine candidate file
        if raw_path.is_file():
            target_file = raw_path
        else:
            target_file = upload_dir / raw_path.name

        if not target_file.is_file():
            abort(404)

        # Path traversal protection: ensure file resides inside designated upload folder
        try:
            target_file.resolve().relative_to(upload_dir.resolve())
        except ValueError:
            abort(403)

        return send_from_directory(upload_dir, target_file.name)
