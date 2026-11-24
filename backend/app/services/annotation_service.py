"""Computational image annotation; source images remain untouched."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import CVCandidate, OCRResult, Plot, SurveyFeature

log = logging.getLogger(__name__)


async def create_annotated_image(
    original_path: str,
    analysis_id: str,
    db: AsyncSession,
) -> Optional[str]:
    """Draw candidate outlines and OCR boxes over a new copy of the original."""
    image = await asyncio.to_thread(cv2.imread, original_path, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not read original image for annotation.")
    candidate_rows = (await db.execute(
        select(CVCandidate).where(CVCandidate.analysis_id == analysis_id)
    )).scalars().all()
    ocr_rows = (await db.execute(
        select(OCRResult).where(OCRResult.analysis_id == analysis_id)
    )).scalars().all()
    plot_rows = (await db.execute(
        select(Plot)
        .where(Plot.analysis_id == analysis_id)
        .options(selectinload(Plot.geometry))
    )).scalars().all()
    feature_rows = (await db.execute(
        select(SurveyFeature).where(SurveyFeature.analysis_id == analysis_id)
    )).scalars().all()
    canvas = image.copy()
    for candidate in candidate_rows:
        if not candidate.pixel_coordinates_json:
            continue
        try:
            polygon = np.asarray(json.loads(candidate.pixel_coordinates_json), dtype=np.int32).reshape((-1, 1, 2))
        except (ValueError, TypeError):
            continue
        color = (34, 197, 94) if candidate.selected else (245, 158, 11)
        thickness = 4 if candidate.selected else 1
        cv2.polylines(canvas, [polygon], True, color, thickness, cv2.LINE_AA)

    # Highlight structured plot boundaries separately from raw CV candidates.
    for plot in plot_rows:
        geometry = plot.geometry
        if not geometry or not geometry.pixel_coordinates_json:
            continue
        try:
            points = json.loads(geometry.pixel_coordinates_json)
            if not isinstance(points, list) or len(points) < 3:
                continue
            polygon = np.asarray(points, dtype=np.float64)
            if polygon.ndim != 2 or polygon.shape[1] != 2 or not np.isfinite(polygon).all():
                continue
            polygon = np.rint(polygon).astype(np.int32).reshape((-1, 1, 2))
        except (ValueError, TypeError, OverflowError):
            continue
        color = (40, 190, 110) if geometry.source == "manual" else (220, 110, 20)
        cv2.polylines(canvas, [polygon], True, color, 3, cv2.LINE_AA)

    # OCR anchors are points; never turn a recognized label into an invented extent.
    for feature in feature_rows:
        if not feature.geometry_json or feature.review_status == "rejected":
            continue
        try:
            geometry = json.loads(feature.geometry_json)
            if geometry.get("coordinate_space") != "image_pixels" or geometry.get("type") != "Point":
                continue
            x, y = (float(value) for value in geometry["coordinates"])
            if not np.isfinite([x, y]).all():
                continue
            point = (int(round(x)), int(round(y)))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
        cv2.circle(canvas, point, 6, (180, 80, 220), 2, cv2.LINE_AA)

    for item in ocr_rows:
        try:
            x1, y1, x2, y2 = [int(round(v)) for v in json.loads(item.bbox_json)]
        except (ValueError, TypeError):
            continue
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (14, 165, 233), 1, cv2.LINE_AA)
        label = item.text.encode("ascii", "replace").decode("ascii")[:64]
        cv2.putText(canvas, label, (max(0, x1), max(16, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (14, 165, 233), 1, cv2.LINE_AA)
    output_dir = settings.resolved_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"annotated_{analysis_id}.png"
    ok = await asyncio.to_thread(cv2.imwrite, str(output), canvas)
    if not ok:
        raise OSError("Could not save annotated preview.")
    return str(Path(output).resolve())
