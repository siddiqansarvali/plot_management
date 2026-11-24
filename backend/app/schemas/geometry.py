"""
Geometry-related Pydantic schemas.

Maintains strict nullability — every geometric field defaults to None.
The frontend must handle None for all fields and show
"not detected" rather than fabricating values.
"""

from __future__ import annotations
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


# ── Coordinate types ───────────────────────────────────────────────────────────
Coordinate = Tuple[float, float]          # (x, y)
CoordinateList = List[Coordinate]


# ── Bounding box ───────────────────────────────────────────────────────────────
class BoundingBox(BaseModel):
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


# ── Geometry source / type enums ───────────────────────────────────────────────
class GeometrySource:
    IMAGE_DETECTED = "image_detected"
    DIMENSION_DERIVED = "dimension_derived"
    HYBRID = "hybrid"
    MANUAL = "manual"


class GeometryType:
    RECTANGLE = "Rectangle"
    POLYGON = "Polygon"
    IRREGULAR_POLYGON = "IrregularPolygon"


# ── Core geometry schema ───────────────────────────────────────────────────────
class GeometrySchema(BaseModel):
    """
    Complete geometry for one plot.
    All fields are optional because any field can be genuinely unknown.
    """

    geom_type: Optional[str] = Field(
        None,
        description="Rectangle | Polygon | IrregularPolygon | null"
    )
    source: Optional[str] = Field(
        None,
        description="image_detected | dimension_derived | hybrid | manual"
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0, le=1.0,
        description="Confidence in this geometry (0.0–1.0), null = undetermined"
    )

    # Pixel coordinates on the original image
    pixel_coordinates: Optional[CoordinateList] = Field(
        None,
        description="Polygon vertices in image pixel coordinates [[x,y], ...]"
    )

    # Real-world coordinates (metres or stated unit)
    real_world_coordinates: Optional[CoordinateList] = Field(
        None,
        description="Polygon vertices in real-world coordinates [[x,y], ...]"
    )
    real_world_unit: Optional[str] = Field(
        None,
        description="Unit system: metres | feet | unknown"
    )

    # Scale factor used to convert pixels to real-world (null if unknown)
    scale_factor_px_per_m: Optional[float] = Field(
        None,
        description="Pixels per metre used for coordinate conversion"
    )

    bounding_box: Optional[BoundingBox] = Field(
        None,
        description="Bounding box in real-world coordinates"
    )

    calculated_area_m2: Optional[float] = Field(
        None,
        description="Area calculated from polygon geometry (NOT the stated area)"
    )
    is_convex: Optional[bool] = None
    is_closed: Optional[bool] = None

    model_config = {"from_attributes": True}


# ── CV Candidate schema ────────────────────────────────────────────────────────
class CVCandidateSchema(BaseModel):
    """One candidate geometry detected by OpenCV."""

    id: str
    candidate_type: Optional[str] = None
    pixel_coordinates: Optional[CoordinateList] = None
    area_pixels: Optional[float] = None
    perimeter_pixels: Optional[float] = None
    is_convex: Optional[bool] = None
    aspect_ratio: Optional[float] = None
    evidence_score: Optional[float] = None
    selected: bool = False

    model_config = {"from_attributes": True}


# ── Geometry correction request ────────────────────────────────────────────────
class GeometryCorrectionRequest(BaseModel):
    """
    Payload sent by the user when manually correcting plot geometry.
    Coordinates are in real-world units.
    """
    real_world_coordinates: CoordinateList = Field(
        ...,
        min_length=3,
        description="Corrected polygon vertices in real-world coordinates"
    )
    real_world_unit: str = Field(
        default="metres",
        description="Unit system for the provided coordinates"
    )
    note: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional note explaining the correction"
    )


class GeometryCorrectionResponse(BaseModel):
    plot_id: str
    geometry: GeometrySchema
    recalculated_area_m2: Optional[float] = None
    message: str = "Geometry updated. source set to 'manual'."
