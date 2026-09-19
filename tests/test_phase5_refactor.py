import unittest
import os
import tempfile
import sqlite3
from pathlib import Path
from flask import Flask

os.environ['TESTING'] = 'True'
os.environ['SECRET_KEY'] = 'test-secret-key-phase5'
os.environ['SEED_DEMO'] = '0'

import config
import services.auth_service as auth_service
import services.file_service as file_service
import services.db_service as db_service
import services.matching_service as matching_service
import app as app_module
from app import app


class TestPhase5Refactor(unittest.TestCase):
    def test_config_module_attributes(self):
        """Verify config.py contains essential configuration constants."""
        self.assertTrue(hasattr(config, 'BASE_DIR'))
        self.assertTrue(hasattr(config, 'DATABASE_FILE'))
        self.assertTrue(hasattr(config, 'FOUND_UPLOAD_DIR'))
        self.assertTrue(hasattr(config, 'LOST_UPLOAD_DIR'))
        self.assertTrue(hasattr(config, 'ALLOWED_EXTENSIONS'))
        self.assertTrue(hasattr(config, 'MAX_CONTENT_LENGTH'))
        self.assertIn('png', config.ALLOWED_EXTENSIONS)
        self.assertEqual(config.MAX_CONTENT_LENGTH, 4 * 1024 * 1024)

    def test_auth_service_isolated(self):
        """Verify auth_service functions work independently."""
        # Password validation
        valid, msg = auth_service.validate_password('ValidPass123')
        self.assertTrue(valid)
        invalid, msg = auth_service.validate_password('short1')
        self.assertFalse(invalid)

        # Answer hashing & checking
        raw_ans = "  Blue KeyChain  "
        hashed = auth_service.hash_answer(raw_ans)
        self.assertTrue(auth_service.check_answer(hashed, "blue keychain"))
        self.assertFalse(auth_service.check_answer(hashed, "red keychain"))

        # Rate limiting
        ip = "192.168.1.100"
        auth_service.clear_rate_limit(ip)
        self.assertFalse(auth_service.is_rate_limited(ip))
        for _ in range(config.MAX_LOGIN_ATTEMPTS):
            auth_service.record_failed_attempt(ip)
        self.assertTrue(auth_service.is_rate_limited(ip))
        auth_service.clear_rate_limit(ip)
        self.assertFalse(auth_service.is_rate_limited(ip))

    def test_file_service_isolated(self):
        """Verify file_service functions work independently."""
        self.assertTrue(file_service.allowed_file("test.png"))
        self.assertTrue(file_service.allowed_file("image.JPEG"))
        self.assertFalse(file_service.allowed_file("script.py"))
        self.assertFalse(file_service.allowed_file("document.pdf"))

        with tempfile.TemporaryDirectory() as tmpdir:
            sample_file = Path(tmpdir) / "test.jpg"
            sample_file.write_text("dummy")
            # resolve_image_path
            resolved = file_service.resolve_image_path(str(sample_file), Path(tmpdir))
            self.assertEqual(resolved, sample_file)

    def test_db_service_isolated(self):
        """Verify db_service initializes schema on a target sqlite database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = Path(tmpdir) / "test_isolated.db"
            db_service.init_db(test_db)

            conn = db_service.get_db_connection(test_db)
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            conn.close()

            self.assertIn('users', tables)
            self.assertIn('found_items', tables)
            self.assertIn('lost_items', tables)
            self.assertIn('matches', tables)
            self.assertIn('claims', tables)
            self.assertIn('verification_questions', tables)
            self.assertIn('verification_sessions', tables)

    def test_matching_service_isolated(self):
        """Verify matching_service module exports."""
        self.assertTrue(hasattr(matching_service, 'run_matching'))
        self.assertTrue(hasattr(matching_service, 'MATCH_CANDIDATE_THRESHOLD'))
        self.assertTrue(hasattr(matching_service, 'MAX_MATCH_CANDIDATES'))

    def test_gunicorn_entrypoint_compatibility(self):
        """Verify app:app entrypoint works cleanly for Gunicorn/systemd production."""
        self.assertIsInstance(app, Flask)
        self.assertEqual(app.name, 'app')

    def test_app_backward_compatible_reexports(self):
        """Verify app module re-exports all legacy helper functions and variables."""
        required_symbols = [
            'get_db_connection',
            'init_db',
            'seed_demo_data',
            'validate_password',
            'normalize_answer',
            'hash_answer',
            'check_answer',
            'is_rate_limited',
            'record_failed_attempt',
            'clear_rate_limit',
            'LOGIN_ATTEMPTS',
            'allowed_file',
            'resolve_image_path',
            'save_photo',
            'run_matching',
            'DATABASE_FILE',
            'FOUND_UPLOAD_DIR',
            'LOST_UPLOAD_DIR',
        ]
        for sym in required_symbols:
            self.assertTrue(hasattr(app_module, sym), f"Missing re-exported symbol on app: {sym}")


if __name__ == '__main__':
    unittest.main()
