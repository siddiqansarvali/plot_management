from app.services.geometry_service import (
    _association_candidates,
    _polygons_overlap,
    _topology_for_polygon,
    _valid_polygon,
)


def candidate(points, area=None, *, convex=True, candidate_id="cv"):
    return {
        "id": candidate_id,
        "pixel_coordinates": points,
        "area_pixels": area or abs(sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        ) / 2),
        "is_convex": convex,
    }


def square(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def test_label_to_boundary_requires_single_label_and_one_unambiguous_candidate():
    contour = candidate(square(10, 10, 110, 110))
    labels = [{"number": "Q7", "center": [60, 60], "confidence": 0.95}]
    ocr = [{"text": "30 x 15 m", "confidence": 0.9, "center": [45, 45]}]

    matched = _association_candidates(labels, [contour], 1_000_000, ocr)
    assert matched["q7"]["candidate"] is contour
    assert matched["q7"]["score"] >= 0.72

    two_labels = labels + [{"number": "Q8", "center": [80, 80], "confidence": 0.95}]
    assert _association_candidates(two_labels, [contour], 1_000_000, ocr) == {}


def test_nested_competing_boundaries_remain_unassigned_without_discriminating_evidence():
    labels = [{"number": "Q7", "center": [60, 60], "confidence": 0.95}]
    inner = candidate(square(20, 20, 100, 100), candidate_id="inner")
    outer = candidate(square(10, 10, 110, 110), candidate_id="outer")

    assert _association_candidates(labels, [inner, outer], 1_000_000, []) == {}


def test_topology_detects_crossing_plot_polygons_but_not_shared_edges():
    left = square(0, 0, 10, 10)
    adjacent = square(10, 0, 20, 10)
    crossing = square(5, 5, 15, 15)

    assert _valid_polygon(left)
    assert not _polygons_overlap(left, adjacent)
    assert _polygons_overlap(left, crossing)
    assert _topology_for_polygon(left, [("Q8", crossing)])["overlaps"]["plots"] == ["Q8"]


def test_self_intersecting_polygon_is_invalid():
    bow_tie = [[0, 0], [10, 10], [0, 10], [10, 0]]
    assert not _valid_polygon(bow_tie)
