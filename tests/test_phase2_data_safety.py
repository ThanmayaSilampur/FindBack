import os
import unittest
from pathlib import Path
from app import (
    app,
    get_db_connection,
    resolve_image_path,
    FOUND_UPLOAD_DIR,
    LOST_UPLOAD_DIR,
)


class Phase2DataSafetyTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self._cleanup_test_data()

    def tearDown(self):
        self._cleanup_test_data()

    def _cleanup_test_data(self):
        conn = get_db_connection()
        test_ids = (9991, 9992, 9993)
        for tid in test_ids:
            conn.execute('DELETE FROM claims WHERE found_item_id = ? OR claimant_id = ?', (tid, tid))
            conn.execute('DELETE FROM verification_sessions WHERE claimant_id = ? OR found_item_id = ?', (tid, tid))
            conn.execute('DELETE FROM verification_questions WHERE found_item_id = ?', (tid,))
            conn.execute('DELETE FROM found_items WHERE id = ?', (tid,))
        conn.commit()
        conn.close()

    def get_csrf_token(self, client):
        client.get('/login')
        with client.session_transaction() as sess:
            return sess.get('_csrf_token')

    def test_existing_production_data_preserved(self):
        """Verify that all existing records in lostlink.db remain intact and accessible."""
        conn = get_db_connection()
        user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        found_count = conn.execute('SELECT COUNT(*) FROM found_items').fetchone()[0]
        lost_count = conn.execute('SELECT COUNT(*) FROM lost_items').fetchone()[0]
        conn.close()

        self.assertGreaterEqual(user_count, 7)
        self.assertGreaterEqual(found_count, 9)
        self.assertGreaterEqual(lost_count, 20)

    def test_no_synthetic_lost_item_created_on_start_verification(self):
        """Calling start_verification must NEVER insert a phantom record into lost_items."""
        conn = get_db_connection()
        initial_lost_count = conn.execute('SELECT COUNT(*) FROM lost_items').fetchone()[0]
        # Use user 2 (existing test user)
        found_item = conn.execute('SELECT id FROM found_items LIMIT 1').fetchone()
        conn.close()

        with self.client as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 2
                sess['user_name'] = 'Test User'

            res = c.get(f'/start_verification/{found_item["id"]}', follow_redirects=False)
            self.assertEqual(res.status_code, 302)

            conn = get_db_connection()
            new_lost_count = conn.execute('SELECT COUNT(*) FROM lost_items').fetchone()[0]
            conn.close()

            # Verify lost_items count did not change!
            self.assertEqual(new_lost_count, initial_lost_count)

    def test_verification_attempt_state_persisted_on_get(self):
        """GET /verify must read real attempts from verification_sessions, not reset to 0."""
        conn = get_db_connection()
        c_db = conn.cursor()
        # Setup a test verification session with 2 attempts
        test_user_id = 9991
        test_found_id = 9991
        test_lost_id = 0

        c_db.execute('DELETE FROM verification_sessions WHERE claimant_id = ?', (test_user_id,))
        c_db.execute('DELETE FROM verification_questions WHERE found_item_id = ?', (test_found_id,))
        c_db.execute('DELETE FROM found_items WHERE id = ?', (test_found_id,))

        c_db.execute(
            'INSERT INTO found_items(id, user_id, item_name, category, location, description, status) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (test_found_id, 1, 'Test Watch', 'Other', 'Lab', 'A watch', 'Available')
        )
        c_db.execute(
            'INSERT INTO verification_questions(found_item_id, question, answer) VALUES (?, ?, ?)',
            (test_found_id, 'Color?', 'Blue')
        )
        c_db.execute(
            'INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, 2, 0)',
            (test_user_id, test_found_id, test_lost_id)
        )
        conn.commit()
        conn.close()

        with self.client as c:
            with c.session_transaction() as sess:
                sess['user_id'] = test_user_id
                sess['user_name'] = 'Attempt Tester'

            get_res = c.get(f'/verify/{test_found_id}/{test_lost_id}')
            self.assertEqual(get_res.status_code, 200)
            # Response should display that 2 attempts were made and 1 is remaining
            # In template: 3 - attempts = 1
            self.assertIn(b'Attempts remaining: 1', get_res.data)

        # Cleanup
        conn = get_db_connection()
        conn.execute('DELETE FROM verification_sessions WHERE claimant_id = ?', (test_user_id,))
        conn.execute('DELETE FROM verification_questions WHERE found_item_id = ?', (test_found_id,))
        conn.execute('DELETE FROM found_items WHERE id = ?', (test_found_id,))
        conn.commit()
        conn.close()

    def test_verification_exhausted_lockout_on_get(self):
        """When 3 attempts are exhausted, GET /verify should immediately display lockout."""
        conn = get_db_connection()
        c_db = conn.cursor()
        test_user_id = 9992
        test_found_id = 9992
        test_lost_id = 0

        c_db.execute(
            'INSERT INTO found_items(id, user_id, item_name, category, location, description, status) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (test_found_id, 1, 'Test Phone', 'Phone', 'Desk', 'A phone', 'Available')
        )
        c_db.execute(
            'INSERT INTO verification_questions(found_item_id, question, answer) VALUES (?, ?, ?)',
            (test_found_id, 'Case color?', 'Black')
        )
        c_db.execute(
            'INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, 3, 0)',
            (test_user_id, test_found_id, test_lost_id)
        )
        conn.commit()
        conn.close()

        with self.client as c:
            with c.session_transaction() as sess:
                sess['user_id'] = test_user_id
                sess['user_name'] = 'Locked Tester'

            get_res = c.get(f'/verify/{test_found_id}/{test_lost_id}')
            self.assertEqual(get_res.status_code, 200)
            self.assertIn(b'Verification attempts exhausted', get_res.data)

        # Cleanup
        conn = get_db_connection()
        conn.execute('DELETE FROM verification_sessions WHERE claimant_id = ?', (test_user_id,))
        conn.execute('DELETE FROM verification_questions WHERE found_item_id = ?', (test_found_id,))
        conn.execute('DELETE FROM found_items WHERE id = ?', (test_found_id,))
        conn.commit()
        conn.close()

    def test_resolve_image_path_handling(self):
        """Verify resolve_image_path properly resolves relative filenames, absolute paths, and handles missing files."""
        # 1. Existing file by relative name
        resolved = resolve_image_path('f31550d4-7eb9-49e7-9eee-beb836c4fcff_book.jpg', FOUND_UPLOAD_DIR)
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.is_file())

        # 2. Existing file by absolute path
        abs_path = FOUND_UPLOAD_DIR / 'f31550d4-7eb9-49e7-9eee-beb836c4fcff_book.jpg'
        resolved_abs = resolve_image_path(str(abs_path), FOUND_UPLOAD_DIR)
        self.assertEqual(resolved, resolved_abs)

        # 3. Nonexistent file
        self.assertIsNone(resolve_image_path('does_not_exist.png', FOUND_UPLOAD_DIR))
        self.assertIsNone(resolve_image_path('', FOUND_UPLOAD_DIR))
        self.assertIsNone(resolve_image_path(None, FOUND_UPLOAD_DIR))

    def test_direct_claim_flow_and_dashboard_render(self):
        """Verify direct claim (lost_id=0) works end-to-end and renders in dashboard and claims."""
        test_user_id = 9993
        test_found_id = 9993
        test_lost_id = 0

        conn = get_db_connection()
        c_db = conn.cursor()
        c_db.execute(
            'INSERT INTO found_items(id, user_id, item_name, category, location, description, status) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (test_found_id, 1, 'Direct Claim Item', 'Other', 'Cafeteria', 'Lost item test', 'Available')
        )
        c_db.execute(
            'INSERT INTO verification_sessions(claimant_id, found_item_id, lost_item_id, attempts, verified) VALUES (?, ?, ?, 1, 1)',
            (test_user_id, test_found_id, test_lost_id)
        )
        conn.commit()
        conn.close()

        with self.client as c:
            with c.session_transaction() as sess:
                sess['user_id'] = test_user_id
                sess['user_name'] = 'Direct Claimer'
                sess['verified_found_item_id'] = test_found_id
                sess['verified_lost_item_id'] = test_lost_id

            csrf_token = self.get_csrf_token(c)

            # Submit claim
            claim_res = c.post(f'/claim/create/{test_found_id}/{test_lost_id}', data={'csrf_token': csrf_token}, follow_redirects=True)
            self.assertEqual(claim_res.status_code, 200)
            self.assertIn(b'Claim submitted successfully', claim_res.data)

            # Verify claims page displays Direct Claim without crashing
            claims_page = c.get('/claims')
            self.assertEqual(claims_page.status_code, 200)
            self.assertIn(b'Direct Claim', claims_page.data)

            # Verify dashboard page renders properly
            dash_page = c.get('/dashboard')
            self.assertEqual(dash_page.status_code, 200)
            self.assertIn(b'Direct Claim', dash_page.data)

        # Cleanup
        conn = get_db_connection()
        conn.execute('DELETE FROM claims WHERE found_item_id = ?', (test_found_id,))
        conn.execute('DELETE FROM verification_sessions WHERE claimant_id = ?', (test_user_id,))
        conn.execute('DELETE FROM found_items WHERE id = ?', (test_found_id,))
        conn.commit()
        conn.close()


if __name__ == '__main__':
    unittest.main()
