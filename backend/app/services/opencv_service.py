"""Generate bounded OpenCV polygon candidates; never choose a target here."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from typing import Any

import cv2
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CVCandidate

log = logging.getLogger(__name__)


def _box_iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1.0)


def _detect(image_path: str) -> tuple[int, int, list[dict[str, Any]]]:
    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("OpenCV could not decode the analysis image.")
    height, width = image.shape[:2]
    page_area = float(width * height)
    softened = cv2.GaussianBlur(image, (3, 3), 0)
    edge = cv2.Canny(softened, 45, 140)
    candidates: list[dict[str, Any]] = []

    for source_name, mask in (("edges", edge),):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = abs(float(cv2.contourArea(contour)))
            if area < page_area * 0.001 or area > page_area * 0.92:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0:
                continue
            epsilon = max(1.0, 0.012 * perimeter)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            if len(approx) < 3 or len(approx) > 18:
                continue
            points = [[float(point[0][0]), float(point[0][1])] for point in approx]
            if len(points) >= 3:
                try:
                    from shapely.geometry import Polygon
                    from shapely.validation import make_valid
                    poly = Polygon(points)
                    if not poly.is_valid:
                        fixed = make_valid(poly)
                        if fixed.geom_type == "Polygon":
                            points = [[float(c[0]), float(c[1])] for c in fixed.exterior.coords[:-1]]
                        elif fixed.geom_type == "MultiPolygon":
                            largest = max(fixed.geoms, key=lambda g: g.area)
                            points = [[float(c[0]), float(c[1])] for c in largest.exterior.coords[:-1]]
                except Exception:
                    pass
            if len(points) < 3:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            # Exclude only page-frame contours, not merely large candidates.
            if bbox[0] < 2 and bbox[1] < 2 and bbox[2] > width - 3 and bbox[3] > height - 3:
                continue
            rect = cv2.minAreaRect(approx)
            rw, rh = rect[1]
            aspect = max(rw, rh) / max(min(rw, rh), 1.0)
            candidates.append({
                "id": str(uuid.uuid4()),
                "candidate_type": "contour",
                "pixel_coordinates": points,
                "area_pixels": area,
                "perimeter_pixels": perimeter,
                "is_convex": bool(cv2.isContourConvex(approx)),
                "aspect_ratio": float(aspect),
                "evidence_score": None,
                "selected": False,
                "bbox": bbox,
            })

    # Remove near-identical contours while retaining distinct candidates.
    candidates.sort(key=lambda c: c["area_pixels"], reverse=True)
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        if any(_box_iou(candidate["bbox"], prior["bbox"]) > 0.94 for prior in unique):
            continue
        unique.append(candidate)
        if len(unique) >= 120:
            break
    return width, height, unique


async def detect_geometry_candidates(
    image_path: str,
    analysis_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Find multiple page-space polygon candidates and persist each candidate."""
    width, height, candidates = await asyncio.to_thread(_detect, image_path)
    for item in candidates:
        db.add(CVCandidate(
            id=item["id"], analysis_id=analysis_id,
            candidate_type=item["candidate_type"],
            pixel_coordinates_json=json.dumps(item["pixel_coordinates"]),
            area_pixels=item["area_pixels"], perimeter_pixels=item["perimeter_pixels"],
            is_convex=item["is_convex"], aspect_ratio=item["aspect_ratio"],
            evidence_score=None, selected=False,
        ))
        item["image_size"] = [width, height]
    await db.flush()
    log.info("OpenCV produced %d geometry candidates", len(candidates))
    return candidates
