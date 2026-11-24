"""
Geometry correction routes.

POST /api/geometry/{plot_id}/correct — submit a manual geometry correction
GET  /api/geometry/{plot_id}         — retrieve current geometry for a plot
GET  /api/geometry/{plot_id}/history — retrieve correction history
"""

import json
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.engine import get_db
from app.database.models import Geometry, ManualCorrection, Measurement, Plot, Validation
from app.schemas.correction import ManualCorrectionCreate, ManualCorrectionResponse
from app.schemas.geometry import GeometryCorrectionResponse, GeometrySchema
from app.utils.math_utils import (
    area_m2_to_hectares, calculate_polygon_area, compute_bounding_box, is_polygon_convex,
)
from app.services.geometry_service import _valid_polygon

router = APIRouter()


@router.post(
    "/geometry/{plot_id}/correct",
    response_model=GeometryCorrectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit manual geometry correction",
    description=(
        "Submit a user-corrected polygon for a plot. "
        "The previous geometry is preserved in the correction history. "
        "The geometry source is set to 'manual'. "
        "Area and bounding box are recalculated from the new coordinates."
    ),
)
async def correct_geometry(
    plot_id: str,
    correction: ManualCorrectionCreate,
    db: AsyncSession = Depends(get_db),
) -> GeometryCorrectionResponse:
    """Apply a manual geometry correction to a plot."""

    # ── Verify plot exists ─────────────────────────────────────────────────────
    result = await db.execute(
        select(Plot)
        .where(Plot.id == plot_id)
        .options(
            selectinload(Plot.geometry),
            selectinload(Plot.measurements),
            selectinload(Plot.validation),
        )
    )
    plot = result.scalar_one_or_none()
    if not plot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plot '{plot_id}' not found.",
        )

    # ── Preserve previous geometry ─────────────────────────────────────────────
    # ── Preserve previous geometry ─────────────────────────────────────────────
    coords = correction.real_world_coordinates or correction.pixel_coordinates
    if not coords or not _valid_polygon(coords):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid polygon coordinates.")

    is_pixel = correction.pixel_coordinates is not None
    unit = None if is_pixel else correction.real_world_unit
    if not is_pixel and unit not in {"metres", "meters", "m", "feet", "ft"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Choose metres or feet for real-world coordinates.")

    previous_geometry_json = None
    if plot.geometry:
        previous_geometry_json = json.dumps({
            "real_world_coordinates": json.loads(plot.geometry.real_world_coordinates_json or "null"),
            "pixel_coordinates": json.loads(plot.geometry.pixel_coordinates_json or "null"),
            "source": plot.geometry.source,
            "confidence": plot.geometry.confidence,
        })

    # Pixel-space geometry has pixel² area, never m². Real-world coordinates
    # produce a square-unit area, normalized to m² only when units support it.
    raw_area = calculate_polygon_area(coords)
    unit_key = (unit or "").casefold()
    area_m2 = raw_area if unit_key in {"metres", "meters", "m"} else (raw_area * 0.09290304 if unit_key in {"feet", "ft"} else None)
    real_bbox = compute_bounding_box(coords) if not is_pixel else None

    others = (await db.execute(
        select(Plot).where(Plot.analysis_id == plot.analysis_id, Plot.id != plot.id)
        .options(selectinload(Plot.geometry))
    )).scalars().all()

    if is_pixel:
        from app.services.geometry_service import _topology_for_polygon
        topology = _topology_for_polygon(coords, [
            (other.plot_number or other.id, json.loads(other.geometry.pixel_coordinates_json))
            for other in others if other.geometry and other.geometry.pixel_coordinates_json
        ])
        if topology["overlaps"]["status"] == "fail":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Polygon overlaps another reconstructed plot. Please resolve the overlap before saving.")
        if not is_polygon_convex([tuple(point) for point in coords]):
            # Example self-intersection check if convex fails or simple check
            pass # Keep it simple for now

    # ── Create or update geometry ──────────────────────────────────────────────
    if plot.geometry:
        geom = plot.geometry
    else:
        geom = Geometry(id=str(uuid.uuid4()), plot_id=plot_id)
        db.add(geom)

    geom.source = "manual"
    geom.real_world_coordinates_json = None if is_pixel else json.dumps(coords)
    geom.pixel_coordinates_json = json.dumps(coords) if is_pixel else None
    geom.real_world_unit = unit
    geom.bounding_box_json = json.dumps(real_bbox) if real_bbox else None
    geom.calculated_area_m2 = area_m2
    geom.is_closed = True
    geom.confidence = None  # Manual corrections don't have AI confidence
    geom.is_convex = is_polygon_convex([tuple(point) for point in coords])

    # Determine type
    geom.geom_type = _infer_geom_type(coords)

    # ── Update plot status ─────────────────────────────────────────────────────
    plot.status = "manual"

    # ── Save correction record ────────────────────────────────────────────────
    from app.services.revision_service import add_revision
    await add_revision(
        db=db,
        analysis_id=plot.analysis_id,
        object_id=plot_id,
        object_type="plot",
        operation="geometry_update",
        previous_state={
            "real_world_coordinates": json.loads(plot.geometry.real_world_coordinates_json) if (plot.geometry and plot.geometry.real_world_coordinates_json) else None,
            "pixel_coordinates": json.loads(plot.geometry.pixel_coordinates_json) if (plot.geometry and plot.geometry.pixel_coordinates_json) else None,
            "source": plot.geometry.source if plot.geometry else None,
            "confidence": plot.geometry.confidence if plot.geometry else None,
        } if previous_geometry_json else None,
        new_state={
            "real_world_coordinates": None if is_pixel else coords,
            "pixel_coordinates": coords if is_pixel else None,
            "real_world_unit": unit,
            "source": "manual",
            "calculated_area_m2": area_m2,
        },
        note=correction.note
    )

    if plot.measurements:
        plot.measurements.calculated_area_m2 = area_m2
        plot.measurements.area_ha = area_m2_to_hectares(area_m2) if area_m2 is not None else None
    if not plot.validation:
        plot.validation = Validation(id=str(uuid.uuid4()), plot_id=plot_id)
    from app.services.validation_service import validate_measurements
    checks = validate_measurements(
        length_m=plot.measurements.length_m if plot.measurements else None,
        width_m=plot.measurements.width_m if plot.measurements else None,
        stated_area_m2=plot.measurements.stated_area_m2 if plot.measurements else None,
        geometry_area_m2=area_m2,
    )
    warnings = list(checks["warnings"])
    
    if not is_pixel:
        topology = {"geometry_valid": {"status": "pass"},
                    "overlaps": {"status": "not_assessable", "plots": []},
                    "gaps": {"status": "not_assessable", "reason": "Other plot geometries use image pixel coordinates."},
                    "boundary_closed": {"status": "pass"}}

    # ── Propagate topology to adjacent plots ───────────────────────────────────
    TOPOLOGY_TOLERANCE_PX = 15.0  # Configurable spatial tolerance for matching image-space coordinates
    
    if previous_geometry_json and is_pixel:
        old_coords = json.loads(previous_geometry_json).get("pixel_coordinates")
        if old_coords and len(old_coords) == len(coords):
            # Find vertices that were moved
            moved_vertices = []
            for i, old_pt in enumerate(old_coords):
                new_pt = coords[i]
                if math.hypot(old_pt[0] - new_pt[0], old_pt[1] - new_pt[1]) > 0.1:
                    moved_vertices.append((i, old_pt, new_pt))

            if moved_vertices:
                for other in others:
                    if not other.geometry or not other.geometry.pixel_coordinates_json:
                        continue
                    other_coords = json.loads(other.geometry.pixel_coordinates_json)
                    changed = False
                    
                    for idx_a, old_pt, new_pt in moved_vertices:
                        prev_a = old_coords[(idx_a - 1) % len(old_coords)]
                        next_a = old_coords[(idx_a + 1) % len(old_coords)]
                        
                        for idx_b, opt in enumerate(other_coords):
                            if math.hypot(opt[0] - old_pt[0], opt[1] - old_pt[1]) <= TOPOLOGY_TOLERANCE_PX:
                                prev_b = other_coords[(idx_b - 1) % len(other_coords)]
                                next_b = other_coords[(idx_b + 1) % len(other_coords)]
                                
                                share_prev = math.hypot(prev_b[0] - prev_a[0], prev_b[1] - prev_a[1]) <= TOPOLOGY_TOLERANCE_PX or \
                                             math.hypot(prev_b[0] - next_a[0], prev_b[1] - next_a[1]) <= TOPOLOGY_TOLERANCE_PX
                                share_next = math.hypot(next_b[0] - prev_a[0], next_b[1] - prev_a[1]) <= TOPOLOGY_TOLERANCE_PX or \
                                             math.hypot(next_b[0] - next_a[0], next_b[1] - next_a[1]) <= TOPOLOGY_TOLERANCE_PX
                                
                                if share_prev or share_next:
                                    other_coords[idx_b] = new_pt
                                    changed = True

                    if changed:
                        other.geometry.pixel_coordinates_json = json.dumps(other_coords)
                        other.geometry.source = "manual"
                        
                        other_area = calculate_polygon_area(other_coords)
                        if other.measurements:
                            other.measurements.calculated_area_m2 = other_area
                            
                        # Save correction for topology propagation
                        await add_revision(
                            db=db,
                            analysis_id=plot.analysis_id,
                            object_id=other.id,
                            object_type="plot",
                            operation="topology_propagation",
                            previous_state={
                                "pixel_coordinates": json.loads(other.geometry.pixel_coordinates_json),
                                "source": other.geometry.source,
                            },
                            new_state={
                                "pixel_coordinates": other_coords,
                                "source": "manual",
                            },
                            note=f"Automatic topology propagation from Plot {plot.plot_number or plot.id}",
                        )

    plot.validation.status = "warning" if warnings else checks["status"]
    plot.validation.warnings_json = json.dumps(warnings)
    plot.validation.area_match = checks["area_match"]
    plot.validation.dimension_match = checks["dimension_match"]
    plot.validation.geometry_consistent = checks["geometry_consistent"]
    plot.validation.area_discrepancy_pct = checks["area_discrepancy_pct"]
    plot.validation.dimension_discrepancy_pct = checks["area_discrepancy_pct"]
    try:
        details = json.loads(plot.validation.details_json or "{}")
        if not isinstance(details, dict):
            details = {}
    except (TypeError, ValueError):
        details = {}
    details.update({"manual_geometry": True, "area_m2": area_m2, "topology": topology})
    plot.validation.details_json = json.dumps(details, ensure_ascii=False)
    await db.flush()

    if is_pixel:
        from app.services.calibration_service import apply_calibration
        await apply_calibration(plot.analysis_id, db)
        await db.refresh(plot, ['geometry', 'measurements'])
        if plot.geometry:
            area_m2 = plot.geometry.calculated_area_m2
        
    await db.commit()

    # ── Build response geometry ────────────────────────────────────────────────
    from app.schemas.geometry import BoundingBox
    geom_schema = GeometrySchema(
        geom_type=geom.geom_type,
        source="manual",
        confidence=None,
        real_world_coordinates=None if is_pixel else coords,
        pixel_coordinates=coords if is_pixel else None,
        real_world_unit=unit,
        bounding_box=BoundingBox(**real_bbox) if real_bbox else None,
        calculated_area_m2=area_m2,
        is_convex=geom.is_convex,
        is_closed=True,
    )

    return GeometryCorrectionResponse(
        plot_id=plot_id,
        geometry=geom_schema,
        recalculated_area_m2=area_m2,
        message=(f"Geometry corrected. Area: {area_m2:.2f} m²" if area_m2 is not None
                 else "Geometry corrected. Real-world area remains unknown without a scale."),
    )


@router.get(
    "/geometry/{plot_id}",
    response_model=GeometrySchema,
    summary="Get current geometry for a plot",
)
async def get_geometry(
    plot_id: str,
    db: AsyncSession = Depends(get_db),
) -> GeometrySchema:
    """Retrieve the current geometry for a plot."""
    result = await db.execute(
        select(Plot)
        .where(Plot.id == plot_id)
        .options(selectinload(Plot.geometry))
    )
    plot = result.scalar_one_or_none()
    if not plot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plot '{plot_id}' not found.",
        )

    if not plot.geometry:
        return GeometrySchema()  # All nulls — geometry not detected

    g = plot.geometry
    from app.schemas.geometry import BoundingBox
    return GeometrySchema(
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


@router.get(
    "/geometry/{plot_id}/history",
    summary="Get geometry correction history",
    description="Returns all manual corrections for a plot, newest first.",
)
async def get_correction_history(
    plot_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all manual corrections for a plot."""
    result = await db.execute(
        select(Plot)
        .where(Plot.id == plot_id)
        .options(selectinload(Plot.corrections))
    )
    plot = result.scalar_one_or_none()
    if not plot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plot '{plot_id}' not found.",
        )

    corrections = sorted(plot.corrections, key=lambda c: c.corrected_at, reverse=True)
    return {
        "plot_id": plot_id,
        "total_corrections": len(corrections),
        "corrections": [
            {
                "id": c.id,
                "corrected_at": c.corrected_at.isoformat(),
                "note": c.note,
                "previous_geometry": json.loads(c.previous_geometry_json) if c.previous_geometry_json else None,
                "new_geometry": json.loads(c.new_geometry_json),
            }
            for c in corrections
        ],
    }


def _infer_geom_type(coords: list) -> str:
    """Classify a corrected polygon without treating every quadrilateral as a rectangle."""
    n = len(coords)
    if n == 4:
        edges = []
        for i, point in enumerate(coords):
            other = coords[(i + 1) % 4]
            edges.append((other[0] - point[0], other[1] - point[1]))
        for i in range(4):
            a, b = edges[i], edges[(i + 1) % 4]
            la, lb = math.hypot(*a), math.hypot(*b)
            if not la or not lb or abs((a[0] * b[0] + a[1] * b[1]) / (la * lb)) > 0.08:
                return "Polygon"
        return "Rectangle"
    return "IrregularPolygon" if n > 4 else "Polygon"


def _validate_polygon(coords: list) -> str | None:
    if len(coords) < 3 or len(coords) > 500:
        return "A boundary must contain between 3 and 500 vertices."
    points = []
    for point in coords:
        if len(point) != 2 or not all(math.isfinite(float(value)) for value in point):
            return "Coordinates must be finite x,y pairs."
        points.append((float(point[0]), float(point[1])))
    if any(math.dist(points[i], points[(i + 1) % len(points)]) < 1e-8 for i in range(len(points))):
        return "Boundary contains duplicate adjacent vertices."
    if not calculate_polygon_area(points):
        return "Boundary area must be greater than zero."
    # Detect intersections among non-adjacent edges.
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if j in {i, (i + 1) % n} or (j + 1) % n in {i, (i + 1) % n}:
                continue
            c, d = points[j], points[(j + 1) % n]
            if orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0:
                return "Boundary edges cross. Adjust the vertices to make a simple polygon."
    return None
