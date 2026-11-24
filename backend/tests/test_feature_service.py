from app.services.feature_service import classify_feature_text


def test_classifies_explicit_road_label_without_rewriting_text():
    text = "9.00 M WIDE ROAD"
    assert ("road", []) in classify_feature_text(text)
    assert text.endswith("ROAD")


def test_recognizes_supported_features_only_when_named():
    assert ("forest", []) in classify_feature_text("FOREST")
    assert ("canal", []) in classify_feature_text("6.00 M WIDE CANAL")
    assert ("railway", []) in classify_feature_text("RAILWAY LINE")
    assert classify_feature_text("two parallel lines") == []


def test_ambiguous_channel_is_review_required_candidate_not_a_canal():
    assert classify_feature_text("NALLA CHANNEL") == [
        ("unknown_feature", ["canal", "drainage", "river_stream"])
    ]


def test_empty_or_unrelated_text_does_not_create_a_feature():
    assert classify_feature_text("") == []
    assert classify_feature_text("dimension 30 x 15") == []


def test_plot_heading_is_not_misclassified_as_a_plot_feature():
    assert classify_feature_text("1. MANUAL SURVEYOR PROVIDED PLOT LAYOUT (Scanned Image)") == []


def test_explicit_plot_identifiers_remain_supported():
    assert ("plot", []) in classify_feature_text("Plot No. A-12")
    assert ("plot", []) in classify_feature_text("Plot 101")
