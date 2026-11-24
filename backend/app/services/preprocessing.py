"""Non-destructive, conservative preprocessing for survey images."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import cv2

from app.config import settings

log = logging.getLogger(__name__)


async def preprocess_image(input_path: str, analysis_id: str) -> str:
    """Write a contrast-normalized grayscale copy without changing its geometry."""

    def process() -> str:
        image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("The uploaded image could not be decoded.")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Local contrast enhancement is gentle and preserves pixel dimensions,
        # so all OCR/CV coordinates still refer to the original image frame.
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        output_dir = settings.resolved_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"preprocessed_{analysis_id}.png"
        if not cv2.imwrite(str(path), enhanced):
            raise OSError("Could not save the preprocessed image.")
        return str(path.resolve())

    return await asyncio.to_thread(process)
