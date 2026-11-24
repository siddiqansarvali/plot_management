from app.services.geometry_service import _candidate_for_label


def _candidate(points, area):
    return {"pixel_coordinates": points, "area_pixels": area}


def test_plot_label_inside_one_candidate_selects_that_outline():
    outline = _candidate([[10, 10], [110, 10], [110, 110], [10, 110]], 10_000)

    assert _candidate_for_label([60, 60], [outline], page_area=1_000_000) is outline


def test_plot_label_inside_multiple_distinct_outlines_is_ambiguous():
    inner = _candidate([[20, 20], [100, 20], [100, 100], [20, 100]], 6_400)
    outer = _candidate([[10, 10], [120, 10], [120, 120], [10, 120]], 12_100)

    assert _candidate_for_label([60, 60], [inner, outer], page_area=1_000_000) is None


def test_duplicate_contour_candidates_with_same_bounds_are_deduplicated():
    small = _candidate([[10, 10], [110, 10], [110, 110], [10, 110]], 9_800)
    best = _candidate([[10, 10], [110, 10], [110, 110], [10, 110]], 10_000)

    assert _candidate_for_label([60, 60], [small, best], page_area=1_000_000) is best


def test_page_frame_and_tiny_contours_are_not_plot_outlines():
    page_frame = _candidate([[0, 0], [1000, 0], [1000, 1000], [0, 1000]], 900_000)
    tiny = _candidate([[49, 49], [51, 49], [51, 51], [49, 51]], 4)

    assert _candidate_for_label([50, 50], [page_frame, tiny], page_area=1_000_000) is None
