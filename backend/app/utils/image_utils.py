"""
Image utility functions.

Helpers for converting between image formats, coordinate systems,
and preparing images for analysis.
"""

import io
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image


def load_image_pil(file_path: str) -> Optional[Image.Image]:
    """
    Load an image from disk using PIL.

    Args:
        file_path: Absolute path to the image file.

    Returns:
        PIL Image or None if loading fails.
    """
    try:
        return Image.open(file_path).copy()  # .copy() to release file handle
    except Exception:
        return None


def image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    """
    Convert a PIL Image to bytes.

    Args:
        image: PIL Image.
        format: Output format (PNG, JPEG, etc.).

    Returns:
        Image bytes.
    """
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


def get_image_dimensions(file_path: str) -> Optional[Tuple[int, int]]:
    """
    Get the width and height of an image without loading the full pixel data.

    Args:
        file_path: Absolute path to the image.

    Returns:
        (width, height) in pixels, or None on failure.
    """
    try:
        with Image.open(file_path) as img:
            return img.size  # (width, height)
    except Exception:
        return None


def save_image_pil(
    image: Image.Image,
    output_path: str,
    quality: int = 95,
) -> bool:
    """
    Save a PIL Image to disk.

    Args:
        image: PIL Image to save.
        output_path: Full path where the image should be saved.
        quality: JPEG quality (ignored for PNG).

    Returns:
        True if saved successfully, False on error.
    """
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fmt = Path(output_path).suffix.upper().lstrip(".")
        if fmt in ("JPG",):
            fmt = "JPEG"
        if fmt == "JPEG":
            image.save(output_path, format=fmt, quality=quality)
        else:
            image.save(output_path, format=fmt)
        return True
    except Exception:
        return False


def resize_for_analysis(
    image: Image.Image,
    max_dimension: int = 2048,
) -> Image.Image:
    """
    Resize an image so its largest dimension is at most max_dimension pixels.
    Preserves aspect ratio. Does not upscale.

    Args:
        image: Input PIL Image.
        max_dimension: Maximum side length in pixels.

    Returns:
        Resized image (or original if already within bounds).
    """
    w, h = image.size
    if w <= max_dimension and h <= max_dimension:
        return image

    scale = max_dimension / max(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return image.resize((new_w, new_h), Image.LANCZOS)


def pil_to_opencv(image: Image.Image):
    """
    Convert a PIL Image to an OpenCV BGR numpy array.

    Args:
        image: PIL Image (RGB or RGBA).

    Returns:
        OpenCV BGR numpy array.
    """
    import numpy as np
    import cv2

    if image.mode == "RGBA":
        image = image.convert("RGB")
    rgb = np.array(image)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr


def opencv_to_pil(cv_image) -> Image.Image:
    """
    Convert an OpenCV BGR numpy array to a PIL Image.

    Args:
        cv_image: OpenCV BGR numpy array.

    Returns:
        PIL RGB Image.
    """
    import numpy as np
    import cv2

    rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """
    Encode a PIL Image as a base64 string for embedding in JSON.

    Args:
        image: PIL Image.
        format: Output format.

    Returns:
        Base64-encoded string (with data URI prefix).
    """
    import base64
    img_bytes = image_to_bytes(image, format=format)
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    mime = "image/png" if format.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"
