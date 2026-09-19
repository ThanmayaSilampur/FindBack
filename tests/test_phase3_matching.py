import io
import unittest
from datetime import datetime, timedelta
from PIL import Image
from ai.matcher import (
    compute_image_hash,
    compare_hashes,
    compute_similarity,
    compute_text_similarity,
    compute_category_similarity,
    compute_location_similarity,
    compute_date_proximity,
    evaluate_match,
    DEFAULT_MATCH_WEIGHTS,
)
from app import app, get_db_connection, run_matching


class Phase3MatchingTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        conn = get_db_connection()
        test_ids = (8881, 8882, 8883, 8884)
        for tid in test_ids:
            conn.execute('DELETE FROM matches WHERE lost_item_id = ? OR found_item_id = ?', (tid, tid))
            conn.execute('DELETE FROM verification_questions WHERE found_item_id = ?', (tid,))
            conn.execute('DELETE FROM found_items WHERE id = ?', (tid,))
            conn.execute('DELETE FROM lost_items WHERE id = ?', (tid,))
        conn.commit()
        conn.close()

    # 1. Image Hashing Tests
    def test_image_hash_and_comparison(self):
        img_blue = Image.new('RGB', (30, 30), color='blue')
        img_blue_copy = Image.new('RGB', (30, 30), color='blue')
        img_red = Image.new('RGB', (30, 30), color='red')

        hash_blue = compute_image_hash(img_blue)
        hash_copy = compute_image_hash(img_blue_copy)
        hash_red = compute_image_hash(img_red)

        self.assertTrue(len(hash_blue) > 0)
        # Identical images must have similarity 1.0
        self.assertEqual(compare_hashes(hash_blue, hash_copy), 1.0)
        # Empty hashes return 0.0
        self.assertEqual(compare_hashes('', hash_blue), 0.0)

    # 2. Text Similarity Tests
    def test_text_similarity(self):
        desc1 = "Black leather wallet with credit cards and student ID"
        desc2 = "Found a black leather wallet near cafeteria with some cards"
        desc3 = "Blue insulated water bottle stainless steel"

        score_similar = compute_text_similarity(desc1, desc2)
        score_different = compute_text_similarity(desc1, desc3)

        self.assertGreater(score_similar, 0.25)
        self.assertEqual(score_different, 0.0)

    # 3. Category Similarity Tests
    def test_category_similarity(self):
        self.assertEqual(compute_category_similarity("Bag", "bag"), 1.0)
        self.assertEqual(compute_category_similarity("Phone", "Wallet"), 0.0)
        self.assertEqual(compute_category_similarity("", "Bag"), 0.0)

    # 4. Location Similarity Tests
    def test_location_similarity(self):
        self.assertEqual(compute_location_similarity("Library 2nd floor", "library 2nd floor"), 1.0)
        # Substring
        self.assertGreaterEqual(compute_location_similarity("Library", "Main Library Building"), 0.8)
        # Unrelated
        self.assertEqual(compute_location_similarity("Gymnasium", "Parking Lot C"), 0.0)

    # 5. Date Proximity Tests
    def test_date_proximity(self):
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        two_months_ago = now - timedelta(days=60)

        score_close = compute_date_proximity(now, yesterday)
        score_far = compute_date_proximity(now, two_months_ago)

        self.assertEqual(score_close, 1.0)
        self.assertLessEqual(score_far, 0.1)

    # 6. Composite Multi-Signal Scoring & Reasons
    def test_evaluate_match_scoring_and_reasons(self):
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lost = {
            'item_name': 'Black Backpack',
            'category': 'Bag',
            'location': 'Library Hall',
            'description': 'Black nylon bag with red keychain',
            'created_at': now_str,
            'image_hash': 'ffff0000ffff0000',
        }
        found = {
            'item_name': 'Black Backpack',
            'category': 'Bag',
            'location': 'Library Hall',
            'description': 'Found black nylon backpack',
            'created_at': now_str,
            'image_hash': 'ffff0000ffff0000',
        }

        result = evaluate_match(lost, found)
        # All signals should match strongly
        self.assertGreaterEqual(result['score'], 0.85)
        self.assertIn("Matching category (Bag)", result['reasons'])
        self.assertIn("Similar photo", result['reasons'])
        self.assertIn("Nearby reported location", result['reasons'])
        self.assertIn("Reported around the same time", result['reasons'])

    # 7. Configurable Weights Test
    def test_configurable_weights(self):
        lost = {'category': 'Phone', 'item_name': 'iPhone', 'description': ''}
        found = {'category': 'Phone', 'item_name': 'Samsung', 'description': ''}

        # With default category weight 0.20
        res_default = evaluate_match(lost, found)
        # With boosted category weight 0.70
        res_custom = evaluate_match(lost, found, weights={'category': 0.70, 'image': 0.10})

        self.assertGreater(res_custom['score'], res_default['score'])

    # 8. Bidirectional Matching End-to-End
    def test_bidirectional_matching_flow(self):
        conn = get_db_connection()
        c = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 1. Existing found item in DB
        c.execute('''
            INSERT INTO found_items(id, user_id, item_name, category, location, description, image_hash, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Available', ?)
        ''', (8881, 1, 'Blue Dell Laptop', 'Other', 'Computer Lab', 'Dell Inspiron with stickers', '1111222233334444', now_str))

        # 2. Existing lost item in DB
        c.execute('''
            INSERT INTO lost_items(id, user_id, item_name, category, location, description, image_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (8882, 2, 'Silver iPad', 'Other', 'Cafeteria', 'Apple iPad with red case', 'aaaa5555aaaa5555', now_str))
        conn.commit()
        conn.close()

        # Match from newly reported LOST item
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO lost_items(id, user_id, item_name, category, location, description, image_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (8883, 2, 'Dell Laptop', 'Other', 'Computer Lab', 'Missing my blue Dell Inspiron laptop', '1111222233334444', now_str))
        conn.commit()
        conn.close()

        lost_matches = run_matching('lost', 8883)
        self.assertTrue(len(lost_matches) > 0)
        top = lost_matches[0]
        self.assertEqual(top['found_id'], 8881)
        self.assertGreaterEqual(top['score'], 0.60)

        # Match from newly reported FOUND item (opposite direction)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO found_items(id, user_id, item_name, category, location, description, image_hash, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Available', ?)
        ''', (8884, 1, 'iPad Tablet', 'Other', 'Cafeteria', 'Found Apple iPad in red case', 'aaaa5555aaaa5555', now_str))
        conn.commit()
        conn.close()

        found_matches = run_matching('found', 8884)
        self.assertTrue(len(found_matches) > 0)
        top_found = found_matches[0]
        self.assertEqual(top_found['lost_id'], 8882)
        self.assertGreaterEqual(top_found['score'], 0.60)

        # Verify reasons are stored in matches table
        conn = get_db_connection()
        match_row = conn.execute('SELECT * FROM matches WHERE lost_item_id = ? AND found_item_id = ?', (8882, 8884)).fetchone()
        conn.close()
        self.assertIsNotNone(match_row)
        self.assertTrue(len(match_row['match_reasons']) > 0)


if __name__ == '__main__':
    unittest.main()
