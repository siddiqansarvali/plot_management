"""
SQLAlchemy ORM models — complete database schema.

Design principles:
- Every field that might be unknown uses nullable=True (no phantom defaults).
- JSON blobs are stored as Text columns; serialization handled in services.
- UUID strings are used as primary keys for portability.
- Relationships are explicit to allow eager/lazy loading as needed.
- audit fields (created_at / updated_at) on long-lived entities.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database.engine import Base


# ── Helpers ────────────────────────────────────────────────────────────────────
def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# Project
# A project groups one or more uploaded survey documents.
# ══════════════════════════════════════════════════════════════════════════════
class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")


# ══════════════════════════════════════════════════════════════════════════════
# Document
# Represents one uploaded survey image file.
# The original file is NEVER modified after upload.
# ══════════════════════════════════════════════════════════════════════════════
class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # File metadata
    original_filename = Column(String(512), nullable=False)
    safe_filename = Column(String(512), nullable=False)      # sanitized, unique
    file_path = Column(String(1024), nullable=False)         # absolute path on disk
    file_type = Column(String(16), nullable=False)           # png, jpg, jpeg, webp
    file_size = Column(Integer, nullable=False)              # bytes
    mime_type = Column(String(64), nullable=True)

    # Image metadata (populated after initial inspection)
    image_width_px = Column(Integer, nullable=True)
    image_height_px = Column(Integer, nullable=True)

    # Lifecycle
    uploaded_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    status = Column(String(32), default="uploaded", nullable=False)
    # Status values: uploaded | processing | completed | failed | partial

    project = relationship("Project", back_populates="documents")
    analysis = relationship(
        "AnalysisResult",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ══════════════════════════════════════════════════════════════════════════════
# AnalysisResult
# One full pipeline run for a document.
# ══════════════════════════════════════════════════════════════════════════════
class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(String, primary_key=True, default=_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)

    pipeline_version = Column(String(32), default="1.0", nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    # Status values: pending | running | completed | failed | partial

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Component-level status flags (track which services ran / failed)
    ocr_status = Column(String(32), nullable=True)          # ok | failed | disabled
    llm_status = Column(String(32), nullable=True)
    yolo_status = Column(String(32), nullable=True)
    opencv_status = Column(String(32), nullable=True)
    fusion_status = Column(String(32), nullable=True)
    # Sanitized per-component diagnostics are persisted so the UI can explain
    # degraded results after reload, not only while the task is in memory.
    component_diagnostics_json = Column(Text, nullable=True)

    # Processed image paths (originals untouched)
    preprocessed_image_path = Column(String(1024), nullable=True)
    annotated_image_path = Column(String(1024), nullable=True)

    # Raw LLM response preserved for debugging / transparency
    llm_raw_response = Column(Text, nullable=True)

    # Overall pipeline confidence (0.0–1.0, null = undetermined)
    overall_confidence = Column(Float, nullable=True)

    document = relationship("Document", back_populates="analysis")
    plots = relationship("Plot", back_populates="analysis", cascade="all, delete-orphan")
    features = relationship("SurveyFeature", back_populates="analysis", cascade="all, delete-orphan")
    ocr_results = relationship("OCRResult", back_populates="analysis", cascade="all, delete-orphan")
    detections = relationship("Detection", back_populates="analysis", cascade="all, delete-orphan")
    cv_candidates = relationship("CVCandidate", back_populates="analysis", cascade="all, delete-orphan")
    corrections = relationship("ManualCorrection", back_populates="analysis", cascade="all, delete-orphan")
    calibration = relationship(
        "Calibration", back_populates="analysis", uselist=False, cascade="all, delete-orphan"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Plot
# Represents one identified plot within a survey document.
# A document may contain multiple plots.
# ══════════════════════════════════════════════════════════════════════════════
class Plot(Base):
    __tablename__ = "plots"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False)

    plot_number = Column(String(64), nullable=True)          # e.g. "12", "24A", null
    survey_number = Column(String(128), nullable=True)       # null if not visible

    # Confidence in the overall plot identification (0.0–1.0)
    confidence_overall = Column(Float, nullable=True)

    # True if this is the main/target plot in the survey
    is_target = Column(Boolean, default=True, nullable=False)

    status = Column(String(32), default="detected", nullable=False)
    # Status values: detected | manual | uncertain | not_found

    # Source of plot identification
    plot_number_source = Column(String(32), nullable=True)   # ocr | llm | user
    plot_number_confidence = Column(Float, nullable=True)

    analysis = relationship("AnalysisResult", back_populates="plots")
    measurements = relationship(
        "Measurement", back_populates="plot", uselist=False, cascade="all, delete-orphan"
    )
    boundaries = relationship(
        "Boundary", back_populates="plot", uselist=False, cascade="all, delete-orphan"
    )
    geometry = relationship(
        "Geometry", back_populates="plot", uselist=False, cascade="all, delete-orphan"
    )
    validation = relationship(
        "Validation", back_populates="plot", uselist=False, cascade="all, delete-orphan"
    )
    corrections = relationship(
        "ManualCorrection", back_populates="plot", cascade="all, delete-orphan",
        order_by="ManualCorrection.corrected_at"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Measurement
# Dimensional data for a plot. All fields nullable (never invent values).
# ══════════════════════════════════════════════════════════════════════════════
class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(String, primary_key=True, default=_uuid)
    plot_id = Column(String, ForeignKey("plots.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Observed length (longest dimension)
    length_m = Column(Float, nullable=True)
    length_confidence = Column(Float, nullable=True)
    length_source = Column(String(32), nullable=True)        # ocr | llm | opencv

    # Observed width (shortest dimension)
    width_m = Column(Float, nullable=True)
    width_confidence = Column(Float, nullable=True)
    width_source = Column(String(32), nullable=True)

    # Area as explicitly stated in the survey document
    stated_area_m2 = Column(Float, nullable=True)
    stated_area_confidence = Column(Float, nullable=True)
    stated_area_source = Column(String(32), nullable=True)

    # Area calculated from length × width (or from polygon geometry)
    calculated_area_m2 = Column(Float, nullable=True)
    area_ha = Column(Float, nullable=True)                   # calculated_area_m2 / 10000

    # Unit system observed in the survey
    units = Column(String(32), nullable=True)                # metres | feet | unknown

    # JSON blob of all conflicting values detected (for transparency)
    # e.g. {"length": [{"value": 30, "source": "ocr"}, {"value": 35, "source": "llm"}]}
    conflicting_values_json = Column(Text, nullable=True)

    plot = relationship("Plot", back_populates="measurements")


# ══════════════════════════════════════════════════════════════════════════════
# Boundary
# Directional neighbors / features of the plot (North, South, East, West).
# ══════════════════════════════════════════════════════════════════════════════
class Boundary(Base):
    __tablename__ = "boundaries"

    id = Column(String, primary_key=True, default=_uuid)
    plot_id = Column(String, ForeignKey("plots.id", ondelete="CASCADE"), nullable=False, unique=True)

    north = Column(String(255), nullable=True)               # e.g. "Forest", "Plot 11"
    north_confidence = Column(Float, nullable=True)
    south = Column(String(255), nullable=True)
    south_confidence = Column(Float, nullable=True)
    east = Column(String(255), nullable=True)
    east_confidence = Column(Float, nullable=True)
    west = Column(String(255), nullable=True)
    west_confidence = Column(Float, nullable=True)

    # Was a north arrow detected?
    north_arrow_detected = Column(Boolean, nullable=True)
    north_arrow_angle_deg = Column(Float, nullable=True)     # degrees from up

    source = Column(String(32), nullable=True)               # llm | ocr | user
    field_sources_json = Column(Text, nullable=True)          # source by direction

    plot = relationship("Plot", back_populates="boundaries")


# ══════════════════════════════════════════════════════════════════════════════
# Geometry
# Coordinate-based geometry for a plot.
# Maintains TWO coordinate systems: pixel (image) and real-world (metres).
# ══════════════════════════════════════════════════════════════════════════════
class Geometry(Base):
    __tablename__ = "geometry"

    id = Column(String, primary_key=True, default=_uuid)
    plot_id = Column(String, ForeignKey("plots.id", ondelete="CASCADE"), nullable=False, unique=True)

    geom_type = Column(String(32), nullable=True)
    # Types: Rectangle | Polygon | IrregularPolygon | null (not detected)

    source = Column(String(32), nullable=True)
    # Sources: image_detected | dimension_derived | hybrid | manual

    confidence = Column(Float, nullable=True)

    # Pixel coordinates on the ORIGINAL image: JSON [[x,y], [x,y], ...]
    pixel_coordinates_json = Column(Text, nullable=True)

    # Real-world coordinates (metres): JSON [[x,y], [x,y], ...]
    real_world_coordinates_json = Column(Text, nullable=True)

    real_world_unit = Column(String(16), nullable=True)      # metres | feet

    # px-per-metre scale factor (null if unknown)
    scale_factor_px_per_m = Column(Float, nullable=True)

    # Bounding box in real-world coords: JSON {"min_x":0,"min_y":0,"max_x":30,"max_y":15}
    bounding_box_json = Column(Text, nullable=True)

    # Area calculated from geometry polygon (independent of stated area)
    calculated_area_m2 = Column(Float, nullable=True)

    is_convex = Column(Boolean, nullable=True)
    is_closed = Column(Boolean, nullable=True)

    plot = relationship("Plot", back_populates="geometry")


# ══════════════════════════════════════════════════════════════════════════════
# CVCandidate
# Candidate geometries detected by OpenCV (before evidence fusion selects one).
# Preserved for transparency.
# ══════════════════════════════════════════════════════════════════════════════
class CVCandidate(Base):
    __tablename__ = "cv_candidates"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False)

    candidate_type = Column(String(64), nullable=True)       # contour | hough_polygon | corner_rect
    pixel_coordinates_json = Column(Text, nullable=True)     # JSON [[x,y], ...]
    area_pixels = Column(Float, nullable=True)
    perimeter_pixels = Column(Float, nullable=True)
    is_convex = Column(Boolean, nullable=True)
    aspect_ratio = Column(Float, nullable=True)

    # Evidence fusion score (0.0–1.0); higher = stronger evidence this is the target plot
    evidence_score = Column(Float, nullable=True)

    # True if this candidate was selected by evidence fusion
    selected = Column(Boolean, default=False, nullable=False)

    analysis = relationship("AnalysisResult", back_populates="cv_candidates")


# ══════════════════════════════════════════════════════════════════════════════
# OCRResult
# Individual text token extracted by PaddleOCR.
# Location (bbox) is essential for spatial reasoning.
# ══════════════════════════════════════════════════════════════════════════════
class OCRResult(Base):
    __tablename__ = "ocr_results"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False)

    text = Column(String(1024), nullable=False)
    confidence = Column(Float, nullable=False)

    # Bounding box: JSON [x1, y1, x2, y2] in pixel coordinates
    bbox_json = Column(Text, nullable=False)

    # Centroid: JSON [cx, cy] in pixel coordinates
    center_json = Column(Text, nullable=False)

    # Semantic category assigned during evidence fusion (nullable)
    category = Column(String(64), nullable=True)
    # Categories: plot_number | survey_number | dimension | area | unit |
    #             boundary_label | road | forest | note | other | unknown

    analysis = relationship("AnalysisResult", back_populates="ocr_results")


# ══════════════════════════════════════════════════════════════════════════════
# SurveyFeature
# Evidence-backed surrounding feature or label in original image coordinates.
# A Point geometry denotes the observed text anchor, never the feature extent.
# ══════════════════════════════════════════════════════════════════════════════
class SurveyFeature(Base):
    __tablename__ = "survey_features"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False)
    feature_type = Column(String(48), nullable=False)
    label = Column(String(1024), nullable=True)
    geometry_json = Column(Text, nullable=True)
    coordinate_space = Column(String(32), default="image_pixels", nullable=False)
    confidence = Column(Float, nullable=True)
    source = Column(String(32), nullable=False)
    evidence_text = Column(String(1024), nullable=True)
    original_type = Column(String(48), nullable=True)
    possible_types_json = Column(Text, nullable=True)
    warning = Column(Text, nullable=True)
    review_required = Column(Boolean, default=False, nullable=False)
    review_status = Column(String(24), default="detected", nullable=False)

    analysis = relationship("AnalysisResult", back_populates="features")


# ══════════════════════════════════════════════════════════════════════════════
# Detection
# Object detection result from YOLO (or any future detector).
# ══════════════════════════════════════════════════════════════════════════════
class Detection(Base):
    __tablename__ = "detections"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False)

    class_name = Column(String(128), nullable=False)
    confidence = Column(Float, nullable=False)
    detector = Column(String(64), nullable=True)             # yolo | custom

    # Bounding box: JSON [x1, y1, x2, y2]
    bbox_json = Column(Text, nullable=False)

    # Centroid: JSON [cx, cy]
    center_json = Column(Text, nullable=False)

    analysis = relationship("AnalysisResult", back_populates="detections")


# ══════════════════════════════════════════════════════════════════════════════
# Validation
# Mathematical validation results for a plot.
# ══════════════════════════════════════════════════════════════════════════════
class Validation(Base):
    __tablename__ = "validation_results"

    id = Column(String, primary_key=True, default=_uuid)
    plot_id = Column(String, ForeignKey("plots.id", ondelete="CASCADE"), nullable=False, unique=True)

    status = Column(String(32), default="unknown", nullable=False)
    # Status values: valid | warning | error | unknown

    # JSON list of warning strings
    # e.g. ["Area discrepancy: stated=500m², calculated=450m² (10.0% diff)"]
    warnings_json = Column(Text, nullable=True)

    # Specific checks
    area_match = Column(Boolean, nullable=True)              # stated vs calculated area
    dimension_match = Column(Boolean, nullable=True)         # l×w vs stated area
    geometry_consistent = Column(Boolean, nullable=True)     # geometry area vs calculated

    area_discrepancy_pct = Column(Float, nullable=True)      # % difference
    dimension_discrepancy_pct = Column(Float, nullable=True)

    # Full details blob for UI display
    details_json = Column(Text, nullable=True)

    plot = relationship("Plot", back_populates="validation")


# ══════════════════════════════════════════════════════════════════════════════
# ManualCorrection
# Full audit trail of user geometry corrections.
# Previous geometry is always preserved.
# ══════════════════════════════════════════════════════════════════════════════
class ManualCorrection(Base):
    __tablename__ = "manual_corrections"

    id = Column(String, primary_key=True, default=_uuid)
    
    # Backwards compatibility: keep plot_id, but allow null for feature corrections
    plot_id = Column(String, ForeignKey("plots.id", ondelete="CASCADE"), nullable=True)
    
    # New fields for Phase 8 revision history
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=True)
    object_id = Column(String, nullable=True)        # The ID of the modified plot or feature
    object_type = Column(String(32), nullable=True)  # "plot" or "feature"
    operation = Column(String(64), nullable=True)    # "geometry_update", "metadata_update"
    revision_number = Column(Integer, nullable=True)
    is_undone = Column(Boolean, default=False, nullable=False)
    correction_source = Column(String(64), nullable=True, default="user")
    affected_objects_json = Column(Text, nullable=True) # JSON list of IDs affected by topology propagation

    corrected_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    # JSON snapshot of state BEFORE this correction
    previous_geometry_json = Column(Text, nullable=True)

    # JSON snapshot of state AFTER this correction (the new state)
    new_geometry_json = Column(Text, nullable=False)

    # Optional note from the user
    note = Column(Text, nullable=True)

    plot = relationship("Plot", back_populates="corrections")
    analysis = relationship("AnalysisResult", back_populates="corrections")

# ══════════════════════════════════════════════════════════════════════════════
# Calibration
# Real-world coordinate system calibration for a survey document.
# ══════════════════════════════════════════════════════════════════════════════
class Calibration(Base):
    __tablename__ = "calibrations"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False, unique=True)

    status = Column(String(32), default="uncalibrated", nullable=False)
    # Status values: uncalibrated | auto_calibrated | manual | conflicted | review_required

    scale_factor_px_per_m = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)

    # List of dimension evidences used for calibration
    supporting_dimensions_json = Column(Text, nullable=True)

    # Error or residual of the calibration
    residual_error = Column(Float, nullable=True)

    # Local coordinate system origin in pixels
    origin_x_px = Column(Float, nullable=True)
    origin_y_px = Column(Float, nullable=True)

    # Rotation if the survey is rotated
    rotation_deg = Column(Float, nullable=True)

    is_manual = Column(Boolean, default=False, nullable=False)

    analysis = relationship("AnalysisResult", back_populates="calibration")

