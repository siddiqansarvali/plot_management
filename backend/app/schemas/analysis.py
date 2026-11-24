"""
Analysis response schemas — the central API contract.

Design principles:
- Every field that might be unknown defaults to None.
- Status fields use explicit string literals (not silent defaults).
- Confidence values are always Optional[float] — never fabricated.
- Conflicts are surfaced, never silently resolved.
- The frontend must handle None gracefully and show "not detected".
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.schemas.geometry import GeometrySchema, CVCandidateSchema


# ── Information status enum ────────────────────────────────────────────────────
class InfoStatus:
    OBSERVED = "OBSERVED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


# ── Evidenced value ────────────────────────────────────────────────────────────
class EvidencedValue(BaseModel):
    """
    A value with its evidence metadata.
    Every piece of important information carries this context.
    """
    value: Optional[Any] = None
    unit: Optional[str] = None
    status: str = InfoStatus.UNKNOWN        # OBSERVED | CALCULATED | INFERRED | UNKNOWN
    source: Optional[str] = None           # ocr | llm | opencv | calculated | user
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    conflict: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Conflicting values from other sources, if any"
    )


# ── OCR result ─────────────────────────────────────────────────────────────────
class OCRResultSchema(BaseModel):
    id: str
    text: str
    confidence: float
    bbox: List[float]                       # [x1, y1, x2, y2]
    center: List[float]                     # [cx, cy]
    category: Optional[str] = None

    model_config = {"from_attributes": True}


# ── YOLO detection ─────────────────────────────────────────────────────────────
class DetectionSchema(BaseModel):
    id: str
    class_name: str
    confidence: float
    bbox: List[float]
    center: List[float]
    detector: Optional[str] = None

    model_config = {"from_attributes": True}


FeatureType = Literal[
    "plot", "road", "canal", "river_stream", "railway", "forest",
    "agricultural_land", "open_land", "park_green_area", "building",
    "boundary_wall", "drainage", "water_body", "utility_corridor",
    "pathway", "layout_boundary", "north_arrow", "dimension_line",
    "survey_reference", "unknown_feature",
]


class FeatureGeometrySchema(BaseModel):
    type: Literal["Point", "LineString", "Polygon"]
    coordinates: Any
    coordinate_space: Literal["image_pixels"] = "image_pixels"


class SurveyFeatureSchema(BaseModel):
    id: str
    feature_type: FeatureType
    label: Optional[str] = None
    geometry: Optional[FeatureGeometrySchema] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    source: str
    evidence_text: Optional[str] = None
    original_type: Optional[str] = None
    possible_types: List[str] = Field(default_factory=list)
    warning: Optional[str] = None
    review_required: bool = False
    review_status: Literal["detected", "confirmed", "rejected"] = "detected"


class SurveyFeatureUpdate(BaseModel):
    feature_type: Optional[FeatureType] = None
    label: Optional[str] = Field(None, max_length=1024)
    geometry: Optional[FeatureGeometrySchema] = None
    review_status: Optional[Literal["confirmed", "rejected", "detected"]] = None


# ── Measurements ───────────────────────────────────────────────────────────────
class MeasurementSchema(BaseModel):
    length_m: Optional[EvidencedValue] = None
    width_m: Optional[EvidencedValue] = None
    stated_area_m2: Optional[EvidencedValue] = None
    calculated_area_m2: Optional[float] = None
    area_ha: Optional[float] = None
    units: Optional[str] = None
    conflicting_values: Optional[Dict[str, List[Dict[str, Any]]]] = None

    model_config = {"from_attributes": True}


# ── Boundaries ─────────────────────────────────────────────────────────────────
class BoundarySchema(BaseModel):
    north: Optional[EvidencedValue] = None
    south: Optional[EvidencedValue] = None
    east: Optional[EvidencedValue] = None
    west: Optional[EvidencedValue] = None
    north_arrow_detected: Optional[bool] = None
    north_arrow_angle_deg: Optional[float] = None
    source: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Validation ─────────────────────────────────────────────────────────────────
class ValidationSchema(BaseModel):
    status: str = "unknown"                 # valid | warning | error | unknown
    warnings: List[str] = Field(default_factory=list)
    area_match: Optional[bool] = None
    dimension_match: Optional[bool] = None
    geometry_consistent: Optional[bool] = None
    area_discrepancy_pct: Optional[float] = None
    details: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


# ── Confidence ─────────────────────────────────────────────────────────────────
class ConfidenceSchema(BaseModel):
    overall: Optional[float] = Field(None, ge=0.0, le=1.0)
    ocr: Optional[float] = None
    llm: Optional[float] = None
    opencv: Optional[float] = None
    geometry: Optional[float] = None
    validation: Optional[float] = None
    explanation: Optional[str] = None      # Human-readable summary


# ── Pipeline component status ──────────────────────────────────────────────────
class ComponentStatusSchema(BaseModel):
    preprocessing: Optional[str] = None
    ocr: Optional[str] = None              # ok | failed | disabled
    llm: Optional[str] = None
    yolo: Optional[str] = None
    opencv: Optional[str] = None
    fusion: Optional[str] = None
    annotation: Optional[str] = None


# ── Plot ───────────────────────────────────────────────────────────────────────
class PlotSchema(BaseModel):
    id: str
    plot_number: Optional[str] = None      # Never invent. null if not detected.
    survey_number: Optional[str] = None
    is_target: bool = True
    status: str = "detected"               # detected | manual | uncertain | not_found
    confidence_overall: Optional[float] = None
    plot_number_source: Optional[str] = None
    plot_number_confidence: Optional[float] = None

    measurements: Optional[MeasurementSchema] = None
    boundaries: Optional[BoundarySchema] = None
    geometry: Optional[GeometrySchema] = None
    validation: Optional[ValidationSchema] = None

    model_config = {"from_attributes": True}


# ── Images ─────────────────────────────────────────────────────────────────────
class ImagesSchema(BaseModel):
    original_url: Optional[str] = None
    annotated_url: Optional[str] = None
    preprocessed_url: Optional[str] = None


# ── Full analysis response ─────────────────────────────────────────────────────
class AnalysisResponse(BaseModel):
    """
    The complete analysis result for a document.
    Returned by GET /api/analysis/{document_id}
    """

    status: str                             # pending | running | completed | failed | partial
    document_id: str
    document_name: Optional[str] = None
    analysis_id: Optional[str] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    message: Optional[str] = None

    # Component status
    components: Optional[ComponentStatusSchema] = None
    component_diagnostics: Dict[str, str] = Field(default_factory=dict)

    # All detected plots (usually 1 target + neighbours)
    plots: List[PlotSchema] = Field(default_factory=list)

    # All OCR tokens (preserved for transparency)
    ocr_results: List[OCRResultSchema] = Field(default_factory=list)

    # YOLO detections
    detections: List[DetectionSchema] = Field(default_factory=list)

    # OpenCV candidates (before fusion)
    cv_candidates: List[CVCandidateSchema] = Field(default_factory=list)

    # Additive, evidence-backed features for the separate digital redraw.
    features: List[SurveyFeatureSchema] = Field(default_factory=list)

    # Overall confidence
    confidence: ConfidenceSchema = Field(default_factory=ConfidenceSchema)

    # Image URLs
    images: ImagesSchema = Field(default_factory=ImagesSchema)

    # Calibration
    calibration: Optional[dict] = None

    # LLM raw response (for debugging / transparency)
    llm_raw_response: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Pipeline trigger ───────────────────────────────────────────────────────────
class AnalysisTriggerRequest(BaseModel):
    target_plot_number: Optional[str] = Field(
        None,
        description="If set, search for this specific plot number. If null, find the main plot."
    )
    force_reanalyze: bool = Field(
        default=False,
        description="If true, re-run the pipeline even if results already exist."
    )


class AnalysisTriggerResponse(BaseModel):
    document_id: str
    analysis_id: str
    status: str
    message: str
