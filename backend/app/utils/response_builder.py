"""
Response builder utility.

Converts ORM model instances into Pydantic response schemas.
Centralizes the mapping logic so routes stay clean.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AnalysisResult, Document
from app.schemas.analysis import (
    AnalysisResponse,
    BoundarySchema,
    ComponentStatusSchema,
    ConfidenceSchema,
    DetectionSchema,
    EvidencedValue,
    ImagesSchema,
    InfoStatus,
    MeasurementSchema,
    OCRResultSchema,
    PlotSchema,
    SurveyFeatureSchema,
    ValidationSchema,
)
from app.schemas.geometry import BoundingBox, CVCandidateSchema, GeometrySchema


async def build_analysis_response(
    analysis: AnalysisResult,
    document: Document,
    db: AsyncSession,
) -> AnalysisResponse:
    """
    Build the full AnalysisResponse from ORM models.

    Args:
        analysis: The AnalysisResult ORM instance (with relationships loaded).
        document: The parent Document ORM instance.
        db: Database session (for any additional queries needed).

    Returns:
        Complete AnalysisResponse schema.
    """
    # ── Component status ───────────────────────────────────────────────────────
    components = ComponentStatusSchema(
        preprocessing="ok" if analysis.preprocessed_image_path else ("failed" if analysis.status in ("completed", "partial", "failed") else None),
        ocr=analysis.ocr_status,
        llm=analysis.llm_status,
        yolo=analysis.yolo_status,
        opencv=analysis.opencv_status,
        fusion=analysis.fusion_status,
        annotation="ok" if analysis.annotated_image_path else ("failed" if analysis.status in ("completed", "partial", "failed") else None),
    )
    try:
        component_diagnostics = json.loads(analysis.component_diagnostics_json or "{}")
        if not isinstance(component_diagnostics, dict):
            component_diagnostics = {}
    except (TypeError, ValueError):
        component_diagnostics = {}

    # ── Image URLs ─────────────────────────────────────────────────────────────
    images = ImagesSchema(
        original_url=f"/api/image/{document.id}/original" if document.safe_filename else None,
        annotated_url=f"/api/image/{document.id}/annotated" if analysis.annotated_image_path else None,
        preprocessed_url=f"/api/image/{document.id}/preprocessed" if analysis.preprocessed_image_path else None,
    )

    # ── OCR results ────────────────────────────────────────────────────────────
    ocr_schemas = []
    for o in (analysis.ocr_results or []):
        try:
            ocr_schemas.append(OCRResultSchema(
                id=o.id,
                text=o.text,
                confidence=o.confidence,
                bbox=json.loads(o.bbox_json),
                center=json.loads(o.center_json),
                category=o.category,
            ))
        except Exception:
            pass

    # ── Detections ─────────────────────────────────────────────────────────────
    detection_schemas = []
    for d in (analysis.detections or []):
        try:
            detection_schemas.append(DetectionSchema(
                id=d.id,
                class_name=d.class_name,
                confidence=d.confidence,
                bbox=json.loads(d.bbox_json),
                center=json.loads(d.center_json),
                detector=d.detector,
            ))
        except Exception:
            pass

    # ── CV candidates ──────────────────────────────────────────────────────────
    cv_schemas = []
    for c in (analysis.cv_candidates or []):
        try:
            cv_schemas.append(CVCandidateSchema(
                id=c.id,
                candidate_type=c.candidate_type,
                pixel_coordinates=json.loads(c.pixel_coordinates_json) if c.pixel_coordinates_json else None,
                area_pixels=c.area_pixels,
                perimeter_pixels=c.perimeter_pixels,
                is_convex=c.is_convex,
                aspect_ratio=c.aspect_ratio,
                evidence_score=c.evidence_score,
                selected=c.selected,
            ))
        except Exception:
            pass

    feature_schemas = []
    for feature in (analysis.features or []):
        try:
            feature_schemas.append(SurveyFeatureSchema(
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
            ))
        except Exception:
            continue

    # ── Plots ──────────────────────────────────────────────────────────────────
    plot_schemas = []
    for plot in (analysis.plots or []):
        plot_schemas.append(_build_plot_schema(plot))

    # ── Confidence ─────────────────────────────────────────────────────────────
    mean_ocr = (
        sum(item.confidence for item in analysis.ocr_results) / len(analysis.ocr_results)
        if analysis.ocr_results else None
    )
    target_geometry = next((p.geometry for p in analysis.plots if p.is_target and p.geometry), None)
    selected_candidate = next((c for c in analysis.cv_candidates if c.selected), None)
    opencv_support = (
        selected_candidate.evidence_score if selected_candidate else
        max((c.evidence_score for c in analysis.cv_candidates if c.evidence_score is not None), default=None)
    )
    confidence = ConfidenceSchema(
        overall=analysis.overall_confidence,
        ocr=mean_ocr,
        geometry=target_geometry.confidence if target_geometry else None,
        opencv=opencv_support,
        explanation="Evidence support is heuristic, not a calibrated probability or surveying accuracy.",
    )

    # ── Calibration ────────────────────────────────────────────────────────────
    calibration = None
    if getattr(analysis, 'calibration', None):
        c = analysis.calibration
        calibration = {
            "id": c.id,
            "status": c.status,
            "scale_factor_px_per_m": c.scale_factor_px_per_m,
            "confidence": c.confidence,
            "supporting_dimensions": json.loads(c.supporting_dimensions_json or "[]"),
            "residual_error": c.residual_error,
            "is_manual": c.is_manual
        }

    return AnalysisResponse(
        status=analysis.status,
        document_id=document.id,
        document_name=document.original_filename,
        analysis_id=analysis.id,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        error_message=analysis.error_message,
        component_diagnostics=component_diagnostics,
        components=components,
        plots=plot_schemas,
        ocr_results=ocr_schemas,
        detections=detection_schemas,
        cv_candidates=cv_schemas,
        features=feature_schemas,
        confidence=confidence,
        images=images,
        calibration=calibration,
        llm_raw_response=analysis.llm_raw_response,
    )


def _build_plot_schema(plot) -> PlotSchema:
    """Build a PlotSchema from a Plot ORM instance."""
    measurements = None
    if plot.measurements:
        m = plot.measurements
        measurements = MeasurementSchema(
            length_m=EvidencedValue(
                value=m.length_m,
                unit=m.units,
                status=InfoStatus.OBSERVED if m.length_m is not None else InfoStatus.UNKNOWN,
                source=m.length_source,
                confidence=m.length_confidence,
            ) if m.length_m is not None else None,
            width_m=EvidencedValue(
                value=m.width_m,
                unit=m.units,
                status=InfoStatus.OBSERVED if m.width_m is not None else InfoStatus.UNKNOWN,
                source=m.width_source,
                confidence=m.width_confidence,
            ) if m.width_m is not None else None,
            stated_area_m2=EvidencedValue(
                value=m.stated_area_m2,
                unit="m²",
                status=InfoStatus.OBSERVED if m.stated_area_m2 is not None else InfoStatus.UNKNOWN,
                source=m.stated_area_source,
                confidence=m.stated_area_confidence,
            ) if m.stated_area_m2 is not None else None,
            calculated_area_m2=m.calculated_area_m2,
            area_ha=m.area_ha,
            units=m.units,
            conflicting_values=json.loads(m.conflicting_values_json) if m.conflicting_values_json else None,
        )

    boundaries = None
    if plot.boundaries:
        b = plot.boundaries
        field_sources = json.loads(b.field_sources_json) if b.field_sources_json else {}
        def boundary_value(direction, value, confidence):
            source = field_sources.get(direction, b.source)
            status = InfoStatus.INFERRED if source and "llm" in source else InfoStatus.OBSERVED
            return EvidencedValue(value=value, status=status, source=source, confidence=confidence)
        boundaries = BoundarySchema(
            north=boundary_value("north", b.north, b.north_confidence) if b.north else None,
            south=boundary_value("south", b.south, b.south_confidence) if b.south else None,
            east=boundary_value("east", b.east, b.east_confidence) if b.east else None,
            west=boundary_value("west", b.west, b.west_confidence) if b.west else None,
            north_arrow_detected=b.north_arrow_detected,
            north_arrow_angle_deg=b.north_arrow_angle_deg,
            source=b.source,
        )

    geometry = None
    if plot.geometry:
        g = plot.geometry
        geometry = GeometrySchema(
            geom_type=g.geom_type,
            source=g.source,
            confidence=g.confidence,
            pixel_coordinates=json.loads(g.pixel_coordinates_json) if g.pixel_coordinates_json else None,
            real_world_coordinates=json.loads(g.real_world_coordinates_json) if g.real_world_coordinates_json else None,
            real_world_unit=g.real_world_unit,
            scale_factor_px_per_m=g.scale_factor_px_per_m,
            bounding_box=BoundingBox(**json.loads(g.bounding_box_json)) if g.bounding_box_json else None,
            calculated_area_m2=g.calculated_area_m2,
            is_convex=g.is_convex,
            is_closed=g.is_closed,
        )

    validation = None
    if plot.validation:
        v = plot.validation
        validation = ValidationSchema(
            status=v.status,
            warnings=json.loads(v.warnings_json) if v.warnings_json else [],
            area_match=v.area_match,
            dimension_match=v.dimension_match,
            geometry_consistent=v.geometry_consistent,
            area_discrepancy_pct=v.area_discrepancy_pct,
            details=json.loads(v.details_json) if v.details_json else None,
        )

    return PlotSchema(
        id=plot.id,
        plot_number=plot.plot_number,
        survey_number=plot.survey_number,
        is_target=plot.is_target,
        status=plot.status,
        confidence_overall=plot.confidence_overall,
        plot_number_source=plot.plot_number_source,
        plot_number_confidence=plot.plot_number_confidence,
        measurements=measurements,
        boundaries=boundaries,
        geometry=geometry,
        validation=validation,
    )
