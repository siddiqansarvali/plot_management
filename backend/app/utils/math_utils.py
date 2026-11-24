"""
Mathematical utility functions for geometry calculations.

All calculations are pure Python — no dependencies on OpenCV or numpy for basics.
"""

import math
from typing import Dict, List, Optional, Tuple

Coordinate = Tuple[float, float]
CoordinateList = List[Coordinate]


def calculate_polygon_area(coordinates: CoordinateList) -> Optional[float]:
    """
    Calculate the area of a polygon using the Shoelace (Gauss) formula.

    Works for any simple (non-self-intersecting) polygon.
    Returns None if fewer than 3 points are provided.

    Args:
        coordinates: List of (x, y) tuples in real-world units.

    Returns:
        Area in the same square units as the input coordinates.
        Always positive (absolute value of signed area).
    """
    n = len(coordinates)
    if n < 3:
        return None

    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coordinates[i][0] * coordinates[j][1]
        area -= coordinates[j][0] * coordinates[i][1]

    return abs(area) / 2.0


def calculate_rectangle_area(length: float, width: float) -> float:
    """
    Calculate rectangle area.

    Args:
        length: Length in metres.
        width: Width in metres.

    Returns:
        Area in square metres.
    """
    return length * width


def area_m2_to_hectares(area_m2: float) -> float:
    """
    Convert area from square metres to hectares.

    Args:
        area_m2: Area in square metres.

    Returns:
        Area in hectares.
    """
    return area_m2 / 10_000.0


def area_m2_to_acres(area_m2: float) -> float:
    """
    Convert area from square metres to acres.

    Args:
        area_m2: Area in square metres.

    Returns:
        Area in acres.
    """
    return area_m2 / 4046.856422


def compute_bounding_box(coordinates: CoordinateList) -> Optional[Dict[str, float]]:
    """
    Compute the axis-aligned bounding box of a polygon.

    Args:
        coordinates: List of (x, y) tuples.

    Returns:
        Dict with min_x, min_y, max_x, max_y or None if empty.
    """
    if not coordinates:
        return None

    xs = [c[0] for c in coordinates]
    ys = [c[1] for c in coordinates]

    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def polygon_perimeter(coordinates: CoordinateList) -> float:
    """
    Calculate the perimeter of a polygon.

    Args:
        coordinates: List of (x, y) tuples.

    Returns:
        Perimeter in the same units as coordinates.
    """
    n = len(coordinates)
    if n < 2:
        return 0.0

    perimeter = 0.0
    for i in range(n):
        j = (i + 1) % n
        dx = coordinates[j][0] - coordinates[i][0]
        dy = coordinates[j][1] - coordinates[i][1]
        perimeter += math.sqrt(dx * dx + dy * dy)

    return perimeter


def is_polygon_convex(coordinates: CoordinateList) -> Optional[bool]:
    """
    Determine if a polygon is convex.

    Args:
        coordinates: List of (x, y) tuples.

    Returns:
        True if convex, False if concave, None if insufficient points.
    """
    n = len(coordinates)
    if n < 3:
        return None

    sign = None
    for i in range(n):
        p1 = coordinates[i]
        p2 = coordinates[(i + 1) % n]
        p3 = coordinates[(i + 2) % n]

        cross = (p2[0] - p1[0]) * (p3[1] - p2[1]) - (p2[1] - p1[1]) * (p3[0] - p2[0])

        if cross != 0:
            current_sign = 1 if cross > 0 else -1
            if sign is None:
                sign = current_sign
            elif sign != current_sign:
                return False

    return True


def calculate_area_discrepancy_pct(
    stated_area: float,
    calculated_area: float,
) -> float:
    """
    Calculate the percentage discrepancy between stated and calculated area.

    Args:
        stated_area: Area as stated in the survey document.
        calculated_area: Area as mathematically calculated.

    Returns:
        Absolute percentage discrepancy (0.0 = exact match).
    """
    if stated_area == 0:
        return 0.0 if calculated_area == 0 else 100.0
    return abs(stated_area - calculated_area) / stated_area * 100.0


def rectangle_from_dimensions(
    length_m: float,
    width_m: float,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> CoordinateList:
    """
    Create a rectangle polygon from length and width dimensions.

    The rectangle is anchored at the given origin.
    This is ONLY used when no image geometry is available AND
    both dimensions are reliably observed.

    Args:
        length_m: Length in metres.
        width_m: Width in metres.
        origin_x: X coordinate of bottom-left corner.
        origin_y: Y coordinate of bottom-left corner.

    Returns:
        List of 4 (x, y) coordinates (counter-clockwise order).
    """
    return [
        (origin_x, origin_y),
        (origin_x + length_m, origin_y),
        (origin_x + length_m, origin_y + width_m),
        (origin_x, origin_y + width_m),
    ]


def centroid(coordinates: CoordinateList) -> Optional[Tuple[float, float]]:
    """
    Calculate the centroid of a polygon.

    Args:
        coordinates: List of (x, y) tuples.

    Returns:
        (cx, cy) centroid or None.
    """
    if not coordinates:
        return None
    cx = sum(c[0] for c in coordinates) / len(coordinates)
    cy = sum(c[1] for c in coordinates) / len(coordinates)
    return (cx, cy)


def pixels_to_metres(
    pixel_value: float,
    scale_factor_px_per_m: float,
) -> float:
    """
    Convert a pixel measurement to metres.

    Args:
        pixel_value: Measurement in pixels.
        scale_factor_px_per_m: Scale factor (pixels per metre).

    Returns:
        Measurement in metres.
    """
    if scale_factor_px_per_m <= 0:
        raise ValueError("scale_factor_px_per_m must be positive.")
    return pixel_value / scale_factor_px_per_m


def estimate_scale_factor(
    known_dimension_m: float,
    measured_dimension_px: float,
) -> Optional[float]:
    """
    Estimate the scale factor (pixels per metre) from a known dimension.

    Args:
        known_dimension_m: The known real-world dimension in metres.
        measured_dimension_px: The measured pixel length of that dimension.

    Returns:
        Scale factor in pixels per metre, or None if inputs are invalid.
    """
    if known_dimension_m <= 0 or measured_dimension_px <= 0:
        return None
    return measured_dimension_px / known_dimension_m
