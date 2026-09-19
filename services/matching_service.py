from ai.matcher import evaluate_match
from config import MATCH_CANDIDATE_THRESHOLD, MAX_MATCH_CANDIDATES
from services.db_service import get_db_connection


def run_matching(item_type, item_id, db_conn_factory=None, weights=None):
    """Run multi-signal matching for either a newly reported lost item or found item.
    
    Supports multiple candidates, precomputed hashes, bidirectional matching,
    and records human-readable match reasons.
    """
    get_conn = db_conn_factory or get_db_connection
    conn = get_conn()
    c = conn.cursor()

    if item_type == 'lost':
        lost_row = conn.execute('SELECT * FROM lost_items WHERE id = ?', (item_id,)).fetchone()
        if not lost_row:
            conn.close()
            return []
        found_rows = conn.execute("SELECT * FROM found_items WHERE status != 'Resolved' ORDER BY id DESC").fetchall()
        pairs = [(dict(lost_row), dict(f)) for f in found_rows]
    else:
        found_row = conn.execute('SELECT * FROM found_items WHERE id = ?', (item_id,)).fetchone()
        if not found_row:
            conn.close()
            return []
        lost_rows = conn.execute("SELECT * FROM lost_items ORDER BY id DESC").fetchall()
        pairs = [(dict(l), dict(found_row)) for l in lost_rows]

    candidates = []
    for lost_dict, found_dict in pairs:
        match_result = evaluate_match(lost_dict, found_dict, weights=weights)
        score = match_result['score']
        reasons = match_result['reasons']

        if score >= MATCH_CANDIDATE_THRESHOLD and (reasons or score >= 0.55):
            candidates.append({
                'lost_id': lost_dict['id'],
                'found_id': found_dict['id'],
                'score': score,
                'reasons': reasons,
                'reasons_str': ', '.join(reasons) if reasons else 'Similar reported characteristics'
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_candidates = candidates[:MAX_MATCH_CANDIDATES]

    for cand in top_candidates:
        existing = c.execute(
            'SELECT id FROM matches WHERE lost_item_id = ? AND found_item_id = ?',
            (cand['lost_id'], cand['found_id'])
        ).fetchone()

        if existing:
            c.execute(
                'UPDATE matches SET similarity_score = ?, match_reasons = ?, status = ? WHERE id = ?',
                (cand['score'], cand['reasons_str'], 'Potential Match', existing['id'])
            )
        else:
            c.execute(
                'INSERT INTO matches(lost_item_id, found_item_id, similarity_score, match_reasons, status) VALUES (?, ?, ?, ?, ?)',
                (cand['lost_id'], cand['found_id'], cand['score'], cand['reasons_str'], 'Potential Match')
            )

    conn.commit()
    conn.close()
    return top_candidates
