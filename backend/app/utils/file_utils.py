"""
File utility functions.

Safe file handling, name sanitization, validation.
"""

import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from app.config import settings


def safe_filename(original_name: str, unique_id: str) -> str:
    """
    Generate a safe, unique filename from an original filename.

    - Strips dangerous characters.
    - Appends a UUID to guarantee uniqueness.
    - Preserves the original extension.
    - Limits total length.

    Args:
        original_name: The original filename from the upload.
        unique_id: A UUID string to ensure uniqueness.

    Returns:
        A sanitized filename safe for filesystem storage.
    """
    # Get extension
    suffix = Path(original_name).suffix.lower()
    if not suffix or suffix.lstrip(".") not in settings.allowed_extensions:
        suffix = ".bin"

    # Sanitize the stem
    stem = Path(original_name).stem
    stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)
    stem = stem[:64]  # Limit stem length

    # Build safe name: stem_uuid.ext
    return f"{stem}_{unique_id}{suffix}"


async def validate_upload_file(file: UploadFile) -> Optional[str]:
    """
    Validate an uploaded file.

    Returns None if valid, or an error message string if invalid.
    Does NOT consume the file content — only inspects metadata.

    Args:
        file: The FastAPI UploadFile object.

    Returns:
        None if valid, error message if invalid.
    """
    if not file or not file.filename:
        return "No file provided."

    # Check extension
    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_extensions:
        return (
            f"Unsupported file type '{ext}'. "
            f"Allowed types: {', '.join(settings.allowed_extensions)}"
        )

    # Check content type if available
    if file.content_type:
        allowed_mime_types = {"image/png", "image/jpeg", "image/webp"}
        if file.content_type not in allowed_mime_types and file.content_type != "application/octet-stream":
            return (
                f"Unsupported content type '{file.content_type}'. "
                "Only PNG, JPG, JPEG, or WEBP images are accepted."
            )

    return None


def get_safe_url_path(filename: str, category: str = "uploads") -> str:
    """
    Return a safe URL path for serving a file.

    Args:
        filename: The safe filename (not a full path).
        category: The storage category ('uploads' or 'outputs').

    Returns:
        URL path string, e.g. '/uploads/scan_abc123.png'
    """
    safe_name = Path(filename).name  # Strip any directory components
    return f"/{category}/{safe_name}"


def filename_to_url(file_path: str, base_url: str = "") -> Optional[str]:
    """
    Convert an absolute file path to a URL for API responses.

    Args:
        file_path: Absolute path to the file.
        base_url: Optional base URL prefix.

    Returns:
        URL string or None if path is invalid.
    """
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        return None

    # Determine category from path
    if "uploads" in path.parts:
        return f"{base_url}/uploads/{path.name}"
    elif "outputs" in path.parts:
        return f"{base_url}/outputs/{path.name}"

    return None
