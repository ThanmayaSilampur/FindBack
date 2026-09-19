import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash
from config import DATABASE_FILE
from services.auth_service import hash_answer


def get_db_connection(db_file=None):
    """Get an open SQLite database connection with row factory configured."""
    target = db_file or DATABASE_FILE
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_file=None):
    """Initialize database tables, performance indexes, and schema migrations safely."""
    conn = get_db_connection(db_file)
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

    # Performance indexes (non-destructive)
    c.execute('CREATE INDEX IF NOT EXISTS idx_found_items_user_id ON found_items(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_lost_items_user_id ON lost_items(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_matches_lost_id ON matches(lost_item_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_matches_found_id ON matches(found_item_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_claims_claimant_id ON claims(claimant_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_claims_found_id ON claims(found_item_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_v_sessions_lookup ON verification_sessions(claimant_id, found_item_id, lost_item_id)')

    # Non-destructive schema migrations
    def add_col(table, col, col_def):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")

    add_col('found_items', 'image_hash', "TEXT DEFAULT ''")
    add_col('lost_items', 'image_hash', "TEXT DEFAULT ''")
    add_col('lost_items', 'location', "TEXT DEFAULT ''")
    add_col('matches', 'match_reasons', "TEXT DEFAULT ''")

    conn.commit()
    conn.close()


def seed_demo_data(db_file=None):
    """Seed sample data for local testing only (never run automatically in production)."""
    conn = get_db_connection(db_file)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO users(name, email, password_hash) VALUES (?, ?, ?)',
                  ('Demo User', 'demo@findback.local', generate_password_hash('DemoUser123')))
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
        ''', (found_id, 'What is attached to the backpack?', hash_answer('Red keychain'),
              found_id, 'What sticker is inside the backpack?', hash_answer('Superman'),
              found_id, 'Where is the scratch?', hash_answer('Left side')))

    conn.commit()
    conn.close()
