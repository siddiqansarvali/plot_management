"""Manual review and correction for structured survey features."""

from __future__ import annotations

import json
import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.engine import get_db
from app.database.models import AnalysisResult, SurveyFeature
from app.schemas.analysis import FeatureGeometrySchema, SurveyFeatureSchema, SurveyFeatureUpdate

router = APIRouter()


@router.patch(
    "/features/{feature_id}",
    response_model=SurveyFeatureSchema,
    summary="Review or correct a detected survey feature",
)
async def update_survey_feature(
    feature_id: str,
    update: SurveyFeatureUpdate,
    db: AsyncSession = Depends(get_db),
) -> SurveyFeatureSchema:
    result = await db.execute(
        select(SurveyFeature)
        .where(SurveyFeature.id == feature_id)
        .options(selectinload(SurveyFeature.analysis).selectinload(AnalysisResult.document))
    )
    feature = result.scalar_one_or_none()
    if feature is None:
        raise HTTPException(status_code=404, detail="Survey feature not found.")

    if "geometry" in update.model_fields_set:
        if update.geometry is None:
            feature.geometry_json = None
        else:
            error = _validate_geometry(
                update.geometry,
                feature.analysis.document.image_width_px,
                feature.analysis.document.image_height_px,
            )
            if error:
                raise HTTPException(status_code=422, detail=error)
            feature.geometry_json = update.geometry.model_dump_json()

    if "feature_type" in update.model_fields_set and update.feature_type is not None:
        feature.feature_type = update.feature_type
        feature.possible_types_json = None
        feature.warning = None
        feature.review_required = False
    if "label" in update.model_fields_set:
        feature.label = update.label.strip() if update.label else None
    if update.review_status is not None:
        feature.review_status = update.review_status
        feature.review_required = update.review_status != "confirmed"

    if update.model_fields_set.intersection({"feature_type", "label", "geometry", "review_status"}):
        if feature.original_type is None:
            feature.original_type = feature.feature_type
        feature.source = "manual"

    await db.flush()
    return _to_schema(feature)


def _validate_geometry(
    geometry: FeatureGeometrySchema,
    width: int | None,
    height: int | None,
) -> str | None:
    coordinates = geometry.coordinates
    if geometry.type == "Point":
        points = [coordinates]
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
            return "Point geometry must contain one x,y pair."
    elif geometry.type == "LineString":
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            return "A line must contain at least two x,y pairs."
        points = coordinates
    else:
        if (not isinstance(coordinates, (list, tuple)) or len(coordinates) != 1
                or not isinstance(coordinates[0], (list, tuple)) or len(coordinates[0]) < 3):
            return "A polygon must contain one ring with at least three x,y pairs."
        points = coordinates[0]

    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return "Feature coordinates must be x,y pairs in image pixels."
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return "Feature coordinates must be numeric."
        if not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0:
            return "Feature coordinates must be finite, non-negative image pixels."
        if width and height and (x > width or y > height):
            return "Feature coordinates must stay inside the uploaded image."
    return None


def _to_schema(feature: SurveyFeature) -> SurveyFeatureSchema:
    return SurveyFeatureSchema(
        id=feature.id,
        feature_type=feature.feature_type,
        label=feature.label,
        geometry=json.loads(feature.geometry_json) if feature.geometry_json else None,
        confidence=feature.confidence,
        source=feature.source,
        evidence_text=feature.evidence_text,
        original_type=feature.original_type,
        possible_types=json.loads(feature.possible_types_json) if feature.possible_types_json else [],
        warning=feature.warning,
        review_required=feature.review_required,
        review_status=feature.review_status,
    )
