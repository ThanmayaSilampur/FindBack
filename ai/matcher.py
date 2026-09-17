from PIL import Image
import imagehash
import os


def normalize_score(score):
    """Clamp a similarity into a 0-1 range."""
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def compute_similarity(image_a, image_b):
    """Compute a simple privacy-preserving image similarity score using image hashes.
    Returns a value between 0.0 and 1.0; scores are not shown to ordinary users.
    """
    try:
        if not image_a or not image_b or not os.path.exists(image_a) or not os.path.exists(image_b):
            return 0.0

        img1 = Image.open(image_a)
        img2 = Image.open(image_b)

        # Average hash reduces the image into a simple binary vector.
        h1 = imagehash.average_hash(img1)
        h2 = imagehash.average_hash(img2)

        # Hamming distance between two binary hash vectors.
        # imagehash average_hash returns an ImageHash object supporting subtraction.
        distance = h1 - h2
        # Convert to a normalized similarity. At 64-bit hash, max distance is 64.
        # Larger distance = less similar.
        similarity = 1.0 - (distance / 64.0)
        return normalize_score(round(similarity, 4))
    except Exception:
        return 0.0
