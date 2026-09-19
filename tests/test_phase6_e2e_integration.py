import unittest
import os
import shutil
import tempfile
import io
from pathlib import Path
from PIL import Image

os.environ['TESTING'] = 'True'
os.environ['SECRET_KEY'] = 'test-secret-key-phase6'
os.environ['SEED_DEMO'] = '0'

import app as app_module
from app import app, get_db_connection, init_db


class TestPhase6E2EIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test_lostlink.db'
        self.found_dir = Path(self.temp_dir) / 'found_items'
        self.lost_dir = Path(self.temp_dir) / 'lost_items'
        self.found_dir.mkdir(parents=True, exist_ok=True)
        self.lost_dir.mkdir(parents=True, exist_ok=True)

        self.orig_db_file = app_module.DATABASE_FILE
        self.orig_found_dir = app_module.FOUND_UPLOAD_DIR
        self.orig_lost_dir = app_module.LOST_UPLOAD_DIR

        app_module.DATABASE_FILE = self.db_path
        app_module.FOUND_UPLOAD_DIR = self.found_dir
        app_module.LOST_UPLOAD_DIR = self.lost_dir

        app.config['TESTING'] = True
        app.config['CSRF_ENABLED'] = False
        self.client = app.test_client()

        with app.app_context():
            init_db()

    def tearDown(self):
        app_module.DATABASE_FILE = self.orig_db_file
        app_module.FOUND_UPLOAD_DIR = self.orig_found_dir
        app_module.LOST_UPLOAD_DIR = self.orig_lost_dir
        app.config['CSRF_ENABLED'] = True
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_image(self, color='red'):
        stream = io.BytesIO()
        img = Image.new('RGB', (100, 100), color=color)
        img.save(stream, format='PNG')
        stream.seek(0)
        return stream

    def test_complete_lost_and_found_lifecycle(self):
        """Complete end-to-end integration flow:
        1. Register Finder and Claimant
        2. Finder reports found item with photo and 3 verification questions
        3. Claimant reports lost item matching the found item
        4. Matching engine automatically pairs items with similarity reasons
        5. Claimant searches and filters found catalog
        6. Claimant views item detail (verifying privacy safeguards)
        7. Claimant attempts verification with 1 failure then success
        8. Claimant submits claim
        9. Finder accepts claim -> item is resolved and removed from public listings
        """
        # Step 1: Register Finder
        resp = self.client.post('/register', data={
            'name': 'Finder Sam',
            'email': 'finder@example.com',
            'password': 'Password123',
            'confirm_password': 'Password123'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Registration successful', resp.get_data(as_text=True))
        finder_id = 1

        # Step 2: Finder reports found item
        img_bytes = self._create_sample_image(color='blue')
        resp = self.client.post('/found/report', data={
            'item_name': 'Lenovo ThinkPad X1',
            'category': 'Electronics',
            'location': 'Library 3rd Floor Table 12',
            'description': 'Black laptop found near charging station',
            'question1': 'What color is the protective sleeve?',
            'answer1': 'Grey Felt',
            'question2': 'What brand of wireless mouse was in the bag?',
            'answer2': 'Logitech MX',
            'question3': 'What is the lock screen wallpaper?',
            'answer3': 'Mountains',
            'photo': (img_bytes, 'thinkpad.png')
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify found item stored in DB with precomputed hash and hashed answers
        conn = get_db_connection()
        found_item = conn.execute('SELECT * FROM found_items WHERE id = 1').fetchone()
        self.assertIsNotNone(found_item)
        self.assertEqual(found_item['item_name'], 'Lenovo ThinkPad X1')
        self.assertTrue(len(found_item['image_hash']) > 0, "Image hash must be precomputed")

        q_rows = conn.execute('SELECT * FROM verification_questions WHERE found_item_id = 1').fetchall()
        self.assertEqual(len(q_rows), 3)
        self.assertNotEqual(q_rows[0]['answer'], 'Grey Felt', "Verification answer must be hashed")
        conn.close()

        # Logout Finder
        self.client.get('/logout')

        # Step 3: Register Claimant
        resp = self.client.post('/register', data={
            'name': 'Owner Dave',
            'email': 'owner@example.com',
            'password': 'Password123',
            'confirm_password': 'Password123'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        claimant_id = 2

        # Step 4: Claimant reports lost item with matching photo
        lost_img = self._create_sample_image(color='blue')
        resp = self.client.post('/lost/report', data={
            'item_name': 'ThinkPad Laptop',
            'category': 'Electronics',
            'location': 'Campus Library',
            'description': 'Lost my black Lenovo ThinkPad laptop with charger',
            'photo': (lost_img, 'lost_thinkpad.png')
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Check bidirectional matching automatically executed
        conn = get_db_connection()
        match_row = conn.execute('SELECT * FROM matches WHERE lost_item_id = 1 AND found_item_id = 1').fetchone()
        self.assertIsNotNone(match_row, "Bidirectional matching should have created a match record")
        self.assertGreater(match_row['similarity_score'], 0.40)
        self.assertIn('Matching category', match_row['match_reasons'])
        conn.close()

        # Step 5: Search & filter found items catalog
        resp = self.client.get('/found?q=ThinkPad&category=Electronics')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Lenovo ThinkPad X1', html)
        self.assertIn('Library 3rd Floor Table 12', html)

        # Step 6: View Item Detail (Ensure private answers are NOT exposed)
        resp = self.client.get('/found/1')
        self.assertEqual(resp.status_code, 200)
        detail_html = resp.get_data(as_text=True)
        self.assertIn('Lenovo ThinkPad X1', detail_html)
        self.assertIn('Privacy & Anti-Theft Protection', detail_html)
        self.assertNotIn('Grey Felt', detail_html)
        self.assertNotIn('Logitech MX', detail_html)
        self.assertNotIn('Mountains', detail_html)

        # Step 7: Ownership Verification Process
        # Attempt 1: Fail with incorrect answers
        resp = self.client.post('/verify/1/1', data={
            'q1': 'Wrong Answer 1',
            'q2': 'Wrong Answer 2',
            'q3': 'Wrong Answer 3'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Attempts remaining: 2', resp.get_data(as_text=True))

        # Attempt 2: Succeed with correct answers
        resp = self.client.post('/verify/1/1', data={
            'q1': 'grey felt',
            'q2': 'logitech mx',
            'q3': 'mountains'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Ownership Verified', resp.get_data(as_text=True))

        # Step 8: Submit Claim
        resp = self.client.post('/claim/create/1/1', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Claim submitted successfully', resp.get_data(as_text=True))

        conn = get_db_connection()
        claim_row = conn.execute('SELECT * FROM claims WHERE found_item_id = 1 AND claimant_id = ?', (claimant_id,)).fetchone()
        self.assertIsNotNone(claim_row)
        self.assertEqual(claim_row['status'], 'Pending')
        claim_id = claim_row['id']
        conn.close()

        # Step 9: Finder logs back in and accepts claim
        self.client.get('/logout')
        self.client.post('/login', data={'email': 'finder@example.com', 'password': 'Password123'}, follow_redirects=True)

        resp = self.client.post(f'/claim/{claim_id}/accept', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Claim accepted', resp.get_data(as_text=True))

        # Verify DB states after resolution
        conn = get_db_connection()
        resolved_claim = conn.execute('SELECT status FROM claims WHERE id = ?', (claim_id,)).fetchone()
        resolved_item = conn.execute('SELECT status FROM found_items WHERE id = 1').fetchone()
        self.assertEqual(resolved_claim['status'], 'Approved')
        self.assertEqual(resolved_item['status'], 'Resolved')
        conn.close()

        # Public listing should no longer show the resolved item
        resp = self.client.get('/found')
        self.assertNotIn('Lenovo ThinkPad X1', resp.get_data(as_text=True))

    def test_fraudulent_claimant_lockout_enforcement(self):
        """Verify that 3 incorrect attempts permanently locks out the claimant session."""
        # Create found item
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Finder', 'f@test.com', 'hash')")
        c.execute("INSERT INTO users (id, name, email, password_hash) VALUES (2, 'Intruder', 'intruder@test.com', 'hash')")
        c.execute("""INSERT INTO found_items (id, user_id, item_name, category, location, description, status)
                     VALUES (1, 1, 'Gold Watch', 'Jewelry', 'Park', 'Gold wrist watch', 'Available')""")
        c.execute("INSERT INTO verification_questions (found_item_id, question, answer) VALUES (1, 'Brand?', 'Rolex')")
        conn.commit()
        conn.close()

        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['user_name'] = 'Intruder'

        # 3 failed attempts
        for attempt in range(1, 4):
            resp = self.client.post('/verify/1/0', data={'q1': f'Guess {attempt}'}, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)

        # 4th access should be immediately blocked with exhausted notice
        resp = self.client.get('/verify/1/0')
        html = resp.get_data(as_text=True)
        self.assertIn('Verification attempts exhausted', html)


if __name__ == '__main__':
    unittest.main()
