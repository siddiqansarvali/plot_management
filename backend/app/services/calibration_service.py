import json
import logging
import math
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import AnalysisResult, Calibration, Plot, Geometry, Measurement

log = logging.getLogger(__name__)

def _dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

async def calibrate_coordinates(analysis_id: str, db: AsyncSession) -> Optional[Calibration]:
    # 1. Fetch analysis with plots, measurements, and geometry
    result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.id == analysis_id)
        .options(
            selectinload(AnalysisResult.calibration),
            selectinload(AnalysisResult.plots).selectinload(Plot.measurements),
            selectinload(AnalysisResult.plots).selectinload(Plot.geometry),
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        return None

    # Do not overwrite if it's already manually calibrated
    if analysis.calibration and analysis.calibration.is_manual:
        log.info("Skipping auto-calibration; manual calibration exists.")
        return analysis.calibration
        
    calibration = analysis.calibration
    if not calibration:
        calibration = Calibration(id=str(uuid.uuid4()), analysis_id=analysis_id)
        db.add(calibration)
        analysis.calibration = calibration

    # 2. Extract scale observations
    observations = []
    area_scale_observations = []
    
    for plot in analysis.plots:
        m = plot.measurements
        g = plot.geometry
        if not m or not g or not g.pixel_coordinates_json:
            continue
            
        pts = json.loads(g.pixel_coordinates_json)
        
        # Plot dimensions (highest priority)
        if m.length_m and m.width_m and len(pts) >= 4:
            side_a = (_dist(pts[0], pts[1]) + _dist(pts[2], pts[3])) / 2.0
            side_b = (_dist(pts[1], pts[2]) + _dist(pts[3], pts[0])) / 2.0
            
            px_max = max(side_a, side_b)
            px_min = min(side_a, side_b)
            
            m_max = max(m.length_m, m.width_m)
            m_min = min(m.length_m, m.width_m)
            
            if m_min > 0 and px_min > 0:
                ratio_px = px_max / px_min
                ratio_m = m_max / m_min
                # Only use if ratios match reasonably well (not totally skewed)
                if abs(ratio_px - ratio_m) / max(ratio_m, 1.0) < 0.2:
                    observations.append({
                        "scale_px_per_m": px_max / m_max,
                        "dimension_m": m_max,
                        "dimension_px": px_max,
                        "source": f"Plot {plot.plot_number} Length"
                    })
                    observations.append({
                        "scale_px_per_m": px_min / m_min,
                        "dimension_m": m_min,
                        "dimension_px": px_min,
                        "source": f"Plot {plot.plot_number} Width"
                    })

        # Area-based scale (fallback: sqrt(pixel_area / stated_area_m2))
        if m.stated_area_m2 and m.stated_area_m2 > 0 and len(pts) >= 3:
            # Compute polygon pixel area using shoelace
            pixel_area = abs(sum(
                pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts))
            )) / 2.0
            if pixel_area > 0:
                scale = math.sqrt(pixel_area / m.stated_area_m2)
                area_scale_observations.append({
                    "scale_px_per_m": scale,
                    "pixel_area": pixel_area,
                    "stated_area_m2": m.stated_area_m2,
                    "source": f"Plot {plot.plot_number} Area"
                })

    # 3. Analyze scale consistency
    if not observations and not area_scale_observations:
        calibration.status = "uncalibrated"
        calibration.scale_factor_px_per_m = None
        calibration.supporting_dimensions_json = "[]"
        calibration.confidence = 0.0
        return calibration

    # If no dimension observations, derive scale from stated areas using median
    if not observations and area_scale_observations:
        area_scales = sorted(obs["scale_px_per_m"] for obs in area_scale_observations)
        mid = len(area_scales) // 2
        median_scale = area_scales[mid] if len(area_scales) % 2 else (area_scales[mid - 1] + area_scales[mid]) / 2.0
        # Accept if spread < 20% of median (documents are consistent scale)
        max_dev = max(abs(s - median_scale) for s in area_scales) if area_scales else 0.0
        if median_scale > 0 and max_dev / median_scale < 0.20:
            observations = area_scale_observations
            log.info(
                "Auto-calibrated from stated areas: scale=%.4f px/m (%.0f plots, spread=%.1f%%)",
                median_scale, len(area_scale_observations), 100 * max_dev / median_scale
            )
        else:
            # Wider spread — still use median but mark conflicted
            observations = area_scale_observations
            log.warning(
                "Area-based scale spread too wide (%.1f%%), marking conflicted",
                100 * max_dev / median_scale if median_scale > 0 else 0
            )
        
    scales = [obs["scale_px_per_m"] for obs in observations]
    avg_scale = sum(scales) / len(scales)
    
    max_dev = max(abs(s - avg_scale) for s in scales) if scales else 0.0
    
    calibration.supporting_dimensions_json = json.dumps(observations)
    
    if max_dev / avg_scale > 0.15: # > 15% variation implies perspective distortion or conflicting evidence
        calibration.status = "conflicted"
        calibration.confidence = 0.3
        calibration.scale_factor_px_per_m = avg_scale # Keep estimate but mark conflicted
        calibration.residual_error = max_dev
    else:
        calibration.status = "auto_calibrated"
        calibration.confidence = min(0.95, 0.5 + 0.1 * len(observations))
        calibration.scale_factor_px_per_m = avg_scale
        calibration.residual_error = max_dev
        
    # Local coordinate origin
    calibration.origin_x_px = 0.0
    calibration.origin_y_px = 0.0
    calibration.rotation_deg = 0.0
    
    await db.flush()
    return calibration

async def apply_calibration(analysis_id: str, db: AsyncSession):
    """Update all geometry real_world_coordinates based on current calibration."""
    result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.id == analysis_id)
        .options(
            selectinload(AnalysisResult.calibration),
            selectinload(AnalysisResult.plots).selectinload(Plot.geometry),
            selectinload(AnalysisResult.plots).selectinload(Plot.validation),
            selectinload(AnalysisResult.plots).selectinload(Plot.measurements),
            selectinload(AnalysisResult.features)
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis or not analysis.calibration:
        return
        
    calib = analysis.calibration
    scale = calib.scale_factor_px_per_m
    
    for plot in analysis.plots:
        g = plot.geometry
        if g and g.pixel_coordinates_json:
            pts = json.loads(g.pixel_coordinates_json)
            if scale and scale > 0 and calib.status != "uncalibrated":
                g.scale_factor_px_per_m = scale
                g.real_world_unit = "metres"
                
                ox = calib.origin_x_px or 0.0
                oy = calib.origin_y_px or 0.0
                # Transform to local coordinates: (px - ox) / scale, -(py - oy) / scale
                # Y is inverted so Y grows upwards
                real_coords = [
                    [(pt[0] - ox) / scale, -(pt[1] - oy) / scale] for pt in pts
                ]
                g.real_world_coordinates_json = json.dumps(real_coords)
                
                from app.utils.math_utils import calculate_polygon_area, compute_bounding_box
                world_area = calculate_polygon_area([tuple(p) for p in real_coords])
                g.calculated_area_m2 = world_area
                g.bounding_box_json = json.dumps(compute_bounding_box([tuple(p) for p in real_coords]))
                
                if plot.measurements:
                    # Update measurements world area
                    plot.measurements.calculated_area_m2 = world_area
                    from app.utils.math_utils import area_m2_to_hectares
                    plot.measurements.area_ha = area_m2_to_hectares(world_area) if world_area is not None else None
                
                # Re-validate areas with new real-world coordinates
                if plot.validation and plot.measurements:
                    stated = plot.measurements.stated_area_m2
                    if stated is not None and world_area is not None:
                        from app.utils.math_utils import calculate_area_discrepancy_pct
                        discrepancy = calculate_area_discrepancy_pct(stated, world_area)
                        plot.validation.area_match = discrepancy <= 2.0
                        plot.validation.area_discrepancy_pct = discrepancy
                        
                        # Rebuild warnings JSON to reflect new area
                        warnings = json.loads(plot.validation.warnings_json or "[]")
                        warnings = [w for w in warnings if "Area discrepancy" not in w]
                        if not plot.validation.area_match:
                            severity = "warning" if discrepancy < 5.0 else "error"
                            warnings.append(f"Area discrepancy: stated={stated:.2f} m², calculated={world_area:.2f} m² ({discrepancy:.1f}% difference). [{severity}]")
                        plot.validation.warnings_json = json.dumps(warnings)
                        if any("[error]" in w for w in warnings):
                            plot.validation.status = "error"
                        elif warnings:
                            plot.validation.status = "warning"
                        else:
                            plot.validation.status = "valid"
            else:
                g.scale_factor_px_per_m = None
                g.real_world_coordinates_json = None
                g.calculated_area_m2 = None
                
    await db.flush()
