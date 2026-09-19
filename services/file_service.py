import os
import uuid
from pathlib import Path
from PIL import Image
from werkzeug.utils import secure_filename
from config import ALLOWED_EXTENSIONS


def allowed_file(filename):
    """Check if file has an allowed image extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def resolve_image_path(raw_path, upload_dir):
    """Safely resolve an image path whether it is an absolute path, relative path, or filename."""
    if not raw_path:
        return None
    p = Path(raw_path)
    if p.is_file():
        return p
    candidate = Path(upload_dir) / p.name
    if candidate.is_file():
        return candidate
    return None


def save_photo(file, folder):
    """Validate image content integrity using Pillow and save securely."""
    if file is None or file.filename == '':
        return ''
    if not allowed_file(file.filename):
        return None

    # Validate image content and integrity using Pillow
    try:
        file.stream.seek(0)
        img = Image.open(file.stream)
        img.verify()
        if not img.format or img.format.lower() not in {'png', 'jpeg', 'gif', 'webp'}:
            return None
        file.stream.seek(0)
    except Exception:
        return None

    filename = secure_filename(str(uuid.uuid4()) + '_' + os.path.basename(file.filename))
    path = Path(folder) / filename
    file.save(path)
    # Store relative filename to guarantee OS portability across Windows and Linux
    return filename
