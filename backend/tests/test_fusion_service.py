from app.services.fusion_service import _classify, _plot_labels


def _ocr(text, center, confidence=0.99):
    return {"text": text, "center": center, "confidence": confidence}


def _outline(x1, y1=100, size=100, page=(1000, 1000)):
    points = [[x1, y1], [x1 + size, y1], [x1 + size, y1 + size], [x1, y1 + size]]
    return {
        "pixel_coordinates": points,
        "area_pixels": size * size,
        "image_size": list(page),
    }


def test_repeated_bare_numbers_inside_distinct_plot_contours_are_recognized():
    candidates = [_outline(100), _outline(300), _outline(500)]
    ocr = [
        _ocr("101", [150, 150]),
        _ocr("102", [350, 150]),
        _ocr("103", [550, 150]),
        # Shorter number tokens in one plot cannot outvote the repeated label series.
        _ocr("00", [160, 170]),
        _ocr("8", [170, 180]),
    ]

    labels = _plot_labels(ocr, candidates)

    assert [label["number"] for label in labels] == ["101", "102", "103"]
    assert [label["item"]["text"] for label in labels] == ["101", "102", "103"]


def test_two_bare_numbers_are_not_enough_to_infer_a_plot_series():
    ocr = [_ocr("101", [150, 150]), _ocr("102", [350, 150])]

    assert _plot_labels(ocr, [_outline(100), _outline(300)]) == []


def test_low_confidence_tokens_and_page_frame_do_not_create_plot_labels():
    page_frame = _outline(0, y1=0, size=950)
    ocr = [
        _ocr("101", [150, 150], confidence=0.89),
        _ocr("102", [350, 150], confidence=0.89),
        _ocr("103", [550, 150], confidence=0.89),
    ]

    assert _plot_labels(ocr, [page_frame]) == []


def test_explicit_plot_labels_remain_supported_without_cv_candidates():
    ocr = [
        _ocr("Plot No. A-12", [150, 150], confidence=0.7),
        _ocr("Plot Number 17", [350, 150], confidence=0.7),
        _ocr("Plot LAYOUT", [550, 150], confidence=0.99),
    ]

    labels = _plot_labels(ocr)

    assert [label["number"] for label in labels] == ["A-12", "17"]
    assert _classify("Plot LAYOUT") == "other"
