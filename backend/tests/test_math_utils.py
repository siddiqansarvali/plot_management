"""
Tests for mathematical utility functions.
Run with: pytest tests/test_math_utils.py -v
"""

import pytest
from app.utils.math_utils import (
    area_m2_to_hectares,
    calculate_polygon_area,
    calculate_rectangle_area,
    calculate_area_discrepancy_pct,
    compute_bounding_box,
    estimate_scale_factor,
    is_polygon_convex,
    polygon_perimeter,
    rectangle_from_dimensions,
)


class TestPolygonArea:
    def test_rectangle_area(self):
        """30m × 15m rectangle should have area 450 m²"""
        coords = [(0, 0), (30, 0), (30, 15), (0, 15)]
        area = calculate_polygon_area(coords)
        assert area == pytest.approx(450.0, rel=1e-6)

    def test_unit_square(self):
        coords = [(0, 0), (1, 0), (1, 1), (0, 1)]
        assert calculate_polygon_area(coords) == pytest.approx(1.0)

    def test_triangle(self):
        coords = [(0, 0), (4, 0), (0, 3)]
        assert calculate_polygon_area(coords) == pytest.approx(6.0)

    def test_insufficient_points(self):
        assert calculate_polygon_area([(0, 0), (1, 1)]) is None

    def test_empty(self):
        assert calculate_polygon_area([]) is None


class TestRectangleArea:
    def test_basic(self):
        assert calculate_rectangle_area(30, 15) == pytest.approx(450.0)

    def test_square(self):
        assert calculate_rectangle_area(10, 10) == pytest.approx(100.0)


class TestHectares:
    def test_450_m2(self):
        """450 m² = 0.045 hectares"""
        assert area_m2_to_hectares(450.0) == pytest.approx(0.045, rel=1e-6)

    def test_10000_m2(self):
        assert area_m2_to_hectares(10000.0) == pytest.approx(1.0)


class TestBoundingBox:
    def test_rectangle(self):
        coords = [(0, 0), (30, 0), (30, 15), (0, 15)]
        bbox = compute_bounding_box(coords)
        assert bbox == {"min_x": 0, "min_y": 0, "max_x": 30, "max_y": 15}

    def test_empty(self):
        assert compute_bounding_box([]) is None


class TestAreaDiscrepancy:
    def test_no_discrepancy(self):
        assert calculate_area_discrepancy_pct(450.0, 450.0) == pytest.approx(0.0)

    def test_10_percent(self):
        assert calculate_area_discrepancy_pct(500.0, 450.0) == pytest.approx(10.0)

    def test_zero_stated(self):
        assert calculate_area_discrepancy_pct(0.0, 0.0) == pytest.approx(0.0)


class TestScaleFactor:
    def test_basic(self):
        """30 metres maps to 300 pixels → 10 px/m"""
        sf = estimate_scale_factor(known_dimension_m=30.0, measured_dimension_px=300.0)
        assert sf == pytest.approx(10.0)

    def test_invalid(self):
        assert estimate_scale_factor(0, 100) is None
        assert estimate_scale_factor(30, 0) is None


class TestConvexity:
    def test_convex_rectangle(self):
        coords = [(0, 0), (30, 0), (30, 15), (0, 15)]
        assert is_polygon_convex(coords) is True

    def test_insufficient_points(self):
        assert is_polygon_convex([(0, 0), (1, 1)]) is None


class TestRectangleFromDimensions:
    def test_basic(self):
        coords = rectangle_from_dimensions(30, 15)
        assert len(coords) == 4
        area = calculate_polygon_area(coords)
        assert area == pytest.approx(450.0)
