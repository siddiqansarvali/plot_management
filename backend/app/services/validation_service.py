"""
Mathematical validation service (Phase 8).

Validates extracted measurements against each other:
    - Stated area vs. calculated area (length × width)
    - Stated area vs. geometry-derived area
    - Dimension consistency

Validation statuses:
    valid   — all checks pass within tolerance
    warning — minor discrepancy detected (< 5%)
    error   — significant discrepancy (>= 5%)
    unknown — insufficient data to validate

RULES:
- Never silently change stated values.
- Never hide discrepancies.
- Always report both values when they conflict.
- Tolerance is applied for rounding differences.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Tolerance percentage — discrepancies below this are "valid"
AREA_TOLERANCE_PCT = 2.0
# Discrepancies above this are "error"
AREA_ERROR_THRESHOLD_PCT = 5.0


def validate_measurements(
    length_m: Optional[float],
    width_m: Optional[float],
    stated_area_m2: Optional[float],
    geometry_area_m2: Optional[float],
) -> Dict[str, Any]:
    """
    Validate all available measurements against each other.

    Args:
        length_m: Observed length in metres.
        width_m: Observed width in metres.
        stated_area_m2: Area explicitly stated in the survey.
        geometry_area_m2: Area calculated from polygon geometry.

    Returns:
        Dict with:
            status: "valid" | "warning" | "error" | "unknown"
            warnings: list of warning strings
            area_match: bool or None
            dimension_match: bool or None
            area_discrepancy_pct: float or None
            calculated_area_m2: float or None (from l × w)
    """
    from app.utils.math_utils import calculate_area_discrepancy_pct

    warnings: List[str] = []
    dimension_area = length_m * width_m if length_m is not None and width_m is not None else None
    comparison_area = dimension_area if dimension_area is not None else geometry_area_m2
    discrepancy = None
    area_match = None
    geometry_consistent = None

    if stated_area_m2 is not None and comparison_area is not None:
        discrepancy = calculate_area_discrepancy_pct(stated_area_m2, comparison_area)
        area_match = discrepancy <= AREA_TOLERANCE_PCT
        if not area_match:
            severity = "warning" if discrepancy < AREA_ERROR_THRESHOLD_PCT else "error"
            warnings.append(
                f"Area discrepancy: stated={stated_area_m2:.2f} m², "
                f"calculated={comparison_area:.2f} m² ({discrepancy:.1f}% difference). [{severity}]"
            )

    if geometry_area_m2 is not None and dimension_area is not None:
        geometry_discrepancy = calculate_area_discrepancy_pct(dimension_area, geometry_area_m2)
        geometry_consistent = geometry_discrepancy <= AREA_TOLERANCE_PCT
        if not geometry_consistent:
            warnings.append(
                f"Geometry area differs from the dimension product by {geometry_discrepancy:.1f}%."
            )

    if not warnings and (comparison_area is not None or geometry_area_m2 is not None):
        status = "valid"
    elif any("[error]" in warning for warning in warnings):
        status = "error"
    elif warnings:
        status = "warning"
    else:
        status = "unknown"

    return {
        "status": status,
        "warnings": warnings,
        "area_match": area_match,
        "dimension_match": area_match if dimension_area is not None and stated_area_m2 is not None else None,
        "geometry_consistent": geometry_consistent,
        "area_discrepancy_pct": discrepancy,
        "calculated_area_m2": comparison_area,
    }
