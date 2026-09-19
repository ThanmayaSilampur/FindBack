import io
import os
import unittest
from PIL import Image
from app import (
    app,
    validate_password,
    hash_answer,
    check_answer,
    normalize_answer,
    LOGIN_ATTEMPTS,
    clear_rate_limit,
)


class Phase1SecurityTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        LOGIN_ATTEMPTS.clear()

    def tearDown(self):
        LOGIN_ATTEMPTS.clear()

    # 1. Password Policy Tests
    def test_password_policy_too_short(self):
        valid, msg = validate_password('short1')
        self.assertFalse(valid)
        self.assertIn('8 characters', msg)

    def test_password_policy_missing_digits(self):
        valid, msg = validate_password('allletterslong')
        self.assertFalse(valid)
        self.assertIn('number', msg)

    def test_password_policy_missing_letters(self):
        valid, msg = validate_password('1234567890')
        self.assertFalse(valid)
        self.assertIn('letter', msg)

    def test_password_policy_valid(self):
        valid, msg = validate_password('SecurePass123')
        self.assertTrue(valid)
        self.assertEqual(msg, '')

    # 2. Answer Hashing & Backward Compatibility Tests
    def test_hash_answer_creates_hash(self):
        raw = "  Red Keychain "
        hashed = hash_answer(raw)
        self.assertTrue(hashed.startswith(('scrypt:', 'pbkdf2:')))
        self.assertNotIn("Red Keychain", hashed)

    def test_check_answer_with_hash(self):
        hashed = hash_answer("Red Keychain")
        # Exact match
        self.assertTrue(check_answer(hashed, "Red Keychain"))
        # Case and whitespace insensitive
        self.assertTrue(check_answer(hashed, "  red keychain  "))
        # Incorrect answer
        self.assertFalse(check_answer(hashed, "Blue Keychain"))

    def test_check_answer_legacy_plaintext_compatibility(self):
        legacy_plaintext = "Red Keychain"
        self.assertTrue(check_answer(legacy_plaintext, "red keychain"))
        self.assertTrue(check_answer(legacy_plaintext, "  RED KEYCHAIN "))
        self.assertFalse(check_answer(legacy_plaintext, "wrong"))

    # 3. CSRF Protection Tests
    def test_post_without_csrf_token_fails(self):
        with self.client as c:
            c.get('/login')
            res = c.post('/login', data={'email': 'test@example.com', 'password': 'Password123'})
            self.assertEqual(res.status_code, 400)

    def test_post_with_valid_csrf_token_succeeds(self):
        with self.client as c:
            get_res = c.get('/login')
            self.assertEqual(get_res.status_code, 200)
            with c.session_transaction() as sess:
                token = sess.get('_csrf_token')
            self.assertIsNotNone(token)
            res = c.post('/login', data={
                'email': 'nonexistent@example.com',
                'password': 'Password123',
                'csrf_token': token
            })
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Invalid email or password', res.data)

    # 4. Image Validation Tests
    def test_valid_image_file(self):
        from app import save_photo, FOUND_UPLOAD_DIR
        from werkzeug.datastructures import FileStorage
        img_bytes = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='blue')
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)

        file = FileStorage(stream=img_bytes, filename='test.png', content_type='image/png')
        saved_name = save_photo(file, FOUND_UPLOAD_DIR)
        full_path = FOUND_UPLOAD_DIR / saved_name
        self.assertTrue(saved_name and full_path.exists())
        if full_path.exists():
            full_path.unlink()

    def test_corrupted_or_disguised_file_rejected(self):
        from app import save_photo, FOUND_UPLOAD_DIR
        from werkzeug.datastructures import FileStorage
        fake_bytes = io.BytesIO(b'#!/bin/bash\necho "exploit"\n')
        file = FileStorage(stream=fake_bytes, filename='exploit.jpg', content_type='image/jpeg')
        saved_path = save_photo(file, FOUND_UPLOAD_DIR)
        self.assertIsNone(saved_path)

    # 5. Rate Limiting Tests
    def test_login_rate_limiting(self):
        with self.client as c:
            c.get('/login')
            with c.session_transaction() as sess:
                token = sess.get('_csrf_token')

            for _ in range(5):
                res = c.post('/login', data={
                    'email': 'bruteforce@example.com',
                    'password': 'WrongPassword1',
                    'csrf_token': token
                })
                self.assertEqual(res.status_code, 200)

            blocked_res = c.post('/login', data={
                'email': 'bruteforce@example.com',
                'password': 'WrongPassword1',
                'csrf_token': token
            })
            self.assertEqual(blocked_res.status_code, 429)
            self.assertIn(b'Too many failed login attempts', blocked_res.data)


if __name__ == '__main__':
    unittest.main()
