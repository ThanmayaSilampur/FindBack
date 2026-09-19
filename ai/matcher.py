import os
import re
from datetime import datetime
from PIL import Image
import imagehash

DEFAULT_MATCH_WEIGHTS = {
    'image': 0.40,
    'category': 0.20,
    'text': 0.20,
    'location': 0.10,
    'date': 0.10,
}

STOPWORDS = {
    'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'with', 'and', 'or',
    'is', 'it', 'of', 'my', 'i', 'this', 'that', 'was', 'were', 'by', 'from',
    'have', 'had', 'has', 'item', 'lost', 'found'
}


def normalize_score(score):
    """Clamp a similarity into a 0.0 to 1.0 range."""
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(float(score), 4)


def compute_image_hash(image_source):
    """Compute and return the average hash hex string for an image file path or PIL Image."""
    try:
        if isinstance(image_source, Image.Image):
            return str(imagehash.average_hash(image_source))
        if isinstance(image_source, (str, bytes, os.PathLike)) and os.path.exists(image_source):
            with Image.open(image_source) as img:
                return str(imagehash.average_hash(img))
    except Exception:
        pass
    return ''


def compare_hashes(hash_a, hash_b):
    """Compute similarity between two precomputed 64-bit image hash strings."""
    if not hash_a or not hash_b:
        return 0.0
    try:
        h1 = imagehash.hex_to_hash(hash_a.strip())
        h2 = imagehash.hex_to_hash(hash_b.strip())
        distance = h1 - h2
        similarity = 1.0 - (distance / 64.0)
        return normalize_score(similarity)
    except Exception:
        return 0.0


def compute_similarity(image_a, image_b):
    """Legacy backward-compatible image comparison function."""
    h1 = compute_image_hash(image_a)
    h2 = compute_image_hash(image_b)
    return compare_hashes(h1, h2)


def tokenize_text(text):
    """Extract lowercase alpha tokens with stopwords removed."""
    if not text:
        return set()
    words = re.findall(r'[a-zA-Z0-9]+', str(text).lower())
    return {w for w in words if len(w) > 1 and w not in STOPWORDS}


def compute_text_similarity(text_a, text_b):
    """Compute word-level Jaccard similarity between two text strings."""
    tokens_a = tokenize_text(text_a)
    tokens_b = tokenize_text(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    if union == 0:
        return 0.0
    return normalize_score(intersection / union)


def compute_category_similarity(cat_a, cat_b):
    """Compare categories with case-insensitive exact matching."""
    if not cat_a or not cat_b:
        return 0.0
    if str(cat_a).strip().lower() == str(cat_b).strip().lower():
        return 1.0
    return 0.0


def compute_location_similarity(loc_a, loc_b):
    """Compare locations by exact match, substring, and token overlap."""
    if not loc_a or not loc_b:
        return 0.0
    a = str(loc_a).strip().lower()
    b = str(loc_b).strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    tokens_a = {t for t in re.findall(r'[a-zA-Z0-9]+', a) if len(t) > 2}
    tokens_b = {t for t in re.findall(r'[a-zA-Z0-9]+', b) if len(t) > 2}
    if tokens_a and tokens_b:
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        if union > 0 and intersection > 0:
            return normalize_score(intersection / union)
    return 0.0


def parse_timestamp(ts):
    """Attempt to parse date strings into datetime objects."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    formats = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d')
    for fmt in formats:
        try:
            return datetime.strptime(str(ts).split('.')[0], fmt)
        except (ValueError, TypeError):
            continue
    return None


def compute_date_proximity(date_a, date_b):
    """Calculate proximity score based on time difference between reports."""
    dt_a = parse_timestamp(date_a)
    dt_b = parse_timestamp(date_b)
    if not dt_a or not dt_b:
        return 0.5  # Neutral default when dates are unavailable

    days_diff = abs((dt_a - dt_b).total_seconds()) / (24 * 3600)
    if days_diff <= 3:
        return 1.0
    if days_diff <= 7:
        return 0.8
    if days_diff <= 14:
        return 0.5
    if days_diff <= 30:
        return 0.2
    return 0.05


def evaluate_match(lost_item, found_item, weights=None):
    """Evaluate a potential match across multiple signals.
    
    Returns a dictionary with the composite score, human-readable reasons,
    and individual signal breakdowns.
    """
    w = dict(DEFAULT_MATCH_WEIGHTS)
    if weights:
        w.update(weights)

    # 1. Image similarity (uses precomputed image_hash if available)
    hash_lost = lost_item.get('image_hash') or ''
    hash_found = found_item.get('image_hash') or ''
    if hash_lost and hash_found:
        image_score = compare_hashes(hash_lost, hash_found)
    else:
        # Fallback to computing from paths if hashes not precomputed
        p_lost = lost_item.get('image_path') or ''
        p_found = found_item.get('image_path') or ''
        image_score = compute_similarity(p_lost, p_found)

    # 2. Category match
    cat_score = compute_category_similarity(lost_item.get('category'), found_item.get('category'))

    # 3. Text similarity (combine name + description)
    text_lost = f"{lost_item.get('item_name', '')} {lost_item.get('description', '')}"
    text_found = f"{found_item.get('item_name', '')} {found_item.get('description', '')}"
    text_score = compute_text_similarity(text_lost, text_found)

    # 4. Location similarity
    loc_score = compute_location_similarity(lost_item.get('location'), found_item.get('location'))

    # 5. Date proximity
    date_score = compute_date_proximity(lost_item.get('created_at'), found_item.get('created_at'))

    # Weighted composite score
    total_score = (
        (w['image'] * image_score) +
        (w['category'] * cat_score) +
        (w['text'] * text_score) +
        (w['location'] * loc_score) +
        (w['date'] * date_score)
    )
    total_score = normalize_score(total_score)

    # Build human-readable match reasons
    reasons = []
    if cat_score >= 1.0:
        category_name = lost_item.get('category') or found_item.get('category')
        reasons.append(f"Matching category ({category_name})")
    if image_score >= 0.70:
        reasons.append("Similar photo")
    if text_score >= 0.25:
        reasons.append("Similar title or description")
    if loc_score >= 0.50:
        reasons.append("Nearby reported location")
    if date_score >= 0.80:
        reasons.append("Reported around the same time")

    return {
        'score': total_score,
        'reasons': reasons,
        'signals': {
            'image': image_score,
            'category': cat_score,
            'text': text_score,
            'location': loc_score,
            'date': date_score,
        }
    }
