import json
import io
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from fastapi import HTTPException

from app.database.models import AnalysisResult, Plot, SurveyFeature

def _dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def _proper_intersection(a, b, c, d):
    # Returns true if line segments ab and cd intersect
    def ccw(A, B, C):
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)

def _has_self_intersection(polygon: List[Tuple[float, float]]) -> bool:
    n = len(polygon)
    if n < 4:
        return False
    # Check all non-adjacent edges for intersection
    for i in range(n):
        for j in range(i + 2, n):
            if (i == 0 and j == n - 1):
                continue  # adjacent
            if _proper_intersection(polygon[i], polygon[(i + 1) % n], polygon[j], polygon[(j + 1) % n]):
                return True
    return False

def validate_export(analysis: AnalysisResult) -> Dict[str, Any]:
    errors = []
    warnings = []
    
    plots = analysis.plots
    for plot in plots:
        geom = plot.geometry
        if not geom:
            continue
        
        coords_str = geom.real_world_coordinates_json or geom.pixel_coordinates_json
        if coords_str:
            coords = json.loads(coords_str)
            if len(coords) < 3:
                errors.append(f"Plot {plot.plot_number or plot.id} has invalid geometry (< 3 points).")
            else:
                if _has_self_intersection(coords):
                    warnings.append(f"Plot {plot.plot_number or plot.id} has self-intersecting geometry (micro-loop).")
                    
        if plot.validation and plot.validation.status == "error":
            errors.append(f"Plot {plot.plot_number or plot.id} has unresolved dimension validation errors.")
        elif plot.validation and plot.validation.status == "warning":
            warnings.append(f"Plot {plot.plot_number or plot.id} has dimension validation warnings.")
            
        if plot.status == "uncertain" or plot.status == "rejected":
            warnings.append(f"Plot {plot.plot_number or plot.id} is marked as {plot.status}.")

    for feature in analysis.features:
        if feature.review_status == "rejected":
            continue
        if feature.review_required and feature.review_status != "confirmed" and feature.review_status != "manually_corrected":
            warnings.append(f"Feature {feature.feature_type} ({feature.label or 'unlabeled'}) requires review.")

    if errors:
        return {"status": "blocked", "reasons": errors, "warnings": warnings}
    elif warnings:
        return {"status": "warning", "reasons": warnings, "warnings": warnings}
    return {"status": "ready", "reasons": [], "warnings": []}

async def fetch_authoritative_survey(analysis_id: str, db: AsyncSession) -> AnalysisResult:
    result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.id == analysis_id)
        .options(
            selectinload(AnalysisResult.plots).selectinload(Plot.geometry),
            selectinload(AnalysisResult.plots).selectinload(Plot.measurements),
            selectinload(AnalysisResult.plots).selectinload(Plot.boundaries),
            selectinload(AnalysisResult.plots).selectinload(Plot.validation),
            selectinload(AnalysisResult.plots).selectinload(Plot.corrections),
            selectinload(AnalysisResult.features),
            selectinload(AnalysisResult.calibration),
            selectinload(AnalysisResult.document),
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis
