import unittest
import os
import shutil
import tempfile
import sqlite3
from pathlib import Path

os.environ['TESTING'] = 'True'
os.environ['SECRET_KEY'] = 'test-secret-key-phase4'
os.environ['SEED_DEMO'] = '0'

import app as app_module
from app import app, get_db_connection, init_db


class TestPhase4UIUX(unittest.TestCase):
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
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        with app.app_context():
            init_db()
            self._seed_test_data()

    def tearDown(self):
        app_module.DATABASE_FILE = self.orig_db_file
        app_module.FOUND_UPLOAD_DIR = self.orig_found_dir
        app_module.LOST_UPLOAD_DIR = self.orig_lost_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_test_data(self):
        conn = get_db_connection()
        c = conn.cursor()

        # Seed test user
        c.execute(
            "INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Alice Test', 'alice@test.com', 'dummyhash')"
        )
        c.execute(
            "INSERT INTO users (id, name, email, password_hash) VALUES (2, 'Bob Test', 'bob@test.com', 'dummyhash')"
        )

        # Seed found items
        c.execute(
            """INSERT INTO found_items (id, user_id, item_name, category, location, description, image_path, status, created_at)
               VALUES (1, 1, 'Blue Dell Laptop', 'Electronics', 'Library 2nd Floor', 'Found on study desk with charger', 'dell.jpg', 'Available', '2026-09-10 10:00:00')"""
        )
        c.execute(
            """INSERT INTO found_items (id, user_id, item_name, category, location, description, image_path, status, created_at)
               VALUES (2, 1, 'Brown Leather Wallet', 'Wallets & Bags', 'Campus Cafeteria', 'Found near cashier counter', 'wallet.jpg', 'Available', '2026-09-15 14:30:00')"""
        )
        c.execute(
            """INSERT INTO found_items (id, user_id, item_name, category, location, description, image_path, status, created_at)
               VALUES (3, 2, 'Silver Ring with Stone', 'Jewelry', 'Gym Locker Room', 'Silver ring left on bench', 'ring.jpg', 'Available', '2026-09-18 18:00:00')"""
        )

        # Seed verification questions for found item 1 (with private answers)
        c.execute(
            """INSERT INTO verification_questions (found_item_id, question, answer)
               VALUES (1, 'What sticker is on the lid?', 'SECRET_GITHUB_OCTOCAT')"""
        )

        # Seed lost item for user 2 (lost_items does not have status column)
        c.execute(
            """INSERT INTO lost_items (id, user_id, item_name, category, location, description)
               VALUES (1, 2, 'Dell Laptop', 'Electronics', 'Campus Library', 'Lost my laptop while studying')"""
        )

        # Seed a match between lost item 1 and found item 1
        c.execute(
            """INSERT INTO matches (lost_item_id, found_item_id, similarity_score, match_reasons)
               VALUES (1, 1, 0.85, 'Matching category: Electronics, Similar title / description keywords')"""
        )

        conn.commit()
        conn.close()

    def test_findback_branding(self):
        """Verify FindBack branding replaces LostLink across key templates."""
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('FindBack', html)
        self.assertNotIn('LostLink', html)

        resp_login = self.client.get('/login')
        self.assertEqual(resp_login.status_code, 200)
        html_login = resp_login.get_data(as_text=True)
        self.assertIn('FindBack', html_login)
        self.assertNotIn('LostLink', html_login)

    def test_found_items_search_filter_by_keyword(self):
        """Verify search query parameter filters found items by keyword in name or description."""
        resp = self.client.get('/found?q=Laptop')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Blue Dell Laptop', html)
        self.assertNotIn('Brown Leather Wallet', html)
        self.assertNotIn('Silver Ring', html)

    def test_found_items_filter_by_category(self):
        """Verify filtering found items by specific category."""
        resp = self.client.get('/found?category=Wallets+%26+Bags')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Brown Leather Wallet', html)
        self.assertNotIn('Blue Dell Laptop', html)

    def test_found_items_filter_by_location(self):
        """Verify filtering found items by location substring."""
        resp = self.client.get('/found?location=Gym')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Silver Ring with Stone', html)
        self.assertNotIn('Blue Dell Laptop', html)

    def test_found_items_filter_empty_state(self):
        """Verify empty state is shown when search filters return no items."""
        resp = self.client.get('/found?q=NonExistentItemXYZ')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('No items matched your filters', html)
        self.assertIn('Reset All Filters', html)

    def test_item_detail_safe_public_view(self):
        """Verify item detail page displays safe public info and keeps secrets hidden."""
        resp = self.client.get('/found/1')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Blue Dell Laptop', html)
        self.assertIn('Library 2nd Floor', html)
        self.assertIn('Electronics', html)
        self.assertIn('Privacy & Anti-Theft Protection', html)
        # Verify private answer is NOT leaked
        self.assertNotIn('SECRET_GITHUB_OCTOCAT', html)

    def test_item_detail_alias_route(self):
        """Verify /item/<id> works as alias for item detail."""
        resp = self.client.get('/item/1')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Blue Dell Laptop', html)

    def test_item_detail_nonexistent(self):
        """Verify nonexistent item redirects with error flash."""
        resp = self.client.get('/found/99999', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Found item not found.', html)

    def test_dashboard_with_matches_and_stats(self):
        """Verify dashboard shows stats, match alert banner, and sections."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['user_name'] = 'Bob Test'

        resp = self.client.get('/dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Welcome, Bob Test', html)
        self.assertIn('Potential Matches Detected', html)
        self.assertIn('Blue Dell Laptop', html)
        self.assertIn('Matching category: Electronics', html)
        self.assertIn('My Lost Items', html)


if __name__ == '__main__':
    unittest.main()
