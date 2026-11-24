import pytest

from app.config import settings
from app.services.vision_service import (
    _decode_json,
    _safe_response_excerpt,
    _validate_observations,
)


@pytest.mark.parametrize("text", [
    '{"plots": [], "features": [], "relationships": [], "uncertain_items": []}',
    '```json\n{"plots": [], "features": [], "relationships": [], "uncertain_items": []}\n```',
    'Here is the result:\n{"plots": [], "features": [], "relationships": [], "uncertain_items": []}\nEnd.',
    '{plots: [], features: [], relationships: [], uncertain_items: [],}',
    "{'plots': [], 'features': [], 'relationships': [], 'uncertain_items': [],}",
])
def test_vision_decoder_accepts_raw_fenced_prose_and_minor_json_repairs(text):
    parsed = _decode_json(text)
    assert parsed["plots"] == []
    assert _validate_observations(parsed)["features"] == []


@pytest.mark.parametrize("text, message", [
    ("", "empty response"),
    ("I cannot read this image", "no JSON object"),
    ('{"plots": [}', "malformed JSON"),
])
def test_vision_decoder_rejects_empty_and_invalid_responses(text, message):
    with pytest.raises(ValueError, match=message):
        _decode_json(text)


def test_vision_observations_normalize_semantics_and_do_not_invent_features():
    normalized = _validate_observations({
        "plots": [{"plot_number": "Q7", "description": "parcel", "confidence": 0.91,
                   "evidence": ["Q7"]}],
        "features": [
            {"type": "ROAD", "label": "12 M WIDE ROAD", "confidence": 0.9,
             "evidence": ["12 M WIDE ROAD"]},
            {"type": "forest", "label": None, "confidence": 0.7, "evidence": []},
        ],
        "relationships": [{"subject": "Q7", "relation": "adjacent_to", "object": "road",
                           "confidence": 0.8, "evidence": ["road borders Q7"]}],
        "uncertain_items": [],
    })
    assert normalized["plots"][0]["plot_number"] == "Q7"
    assert normalized["plots"][0]["neighbors"] == ["road"]
    assert normalized["features"][0]["type"] == "road"
    assert len(normalized["features"]) == 2
    assert normalized["plots"][0]["dimensions"] == []
    assert normalized["dimensions"] == {}


def test_vision_observations_reject_model_geometry():
    with pytest.raises(ValueError, match="coordinates or geometry"):
        _validate_observations({"plots": [{"plot_number": "Q7", "polygon": [[0, 0]]}]})


def test_safe_excerpt_redacts_key_and_collapses_control_characters(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-secret-value")
    excerpt = _safe_response_excerpt("first\nsecond test-secret-value\x00", limit=240)
    assert "test-secret-value" not in excerpt
    assert "first second" in excerpt


def test_vision_observations_accept_string_plots_and_flexible_features():
    normalized = _validate_observations({
        "plots": ["101", "102", 103],
        "features": [{"type": "road", "label": "30M ROAD"}],
        "relationships": [],
        "uncertain_items": [],
    })
    assert len(normalized["plots"]) == 3
    assert normalized["plots"][0]["plot_number"] == "101"
    assert normalized["plots"][1]["plot_number"] == "102"
    assert normalized["plots"][2]["plot_number"] == "103"
    assert normalized["features"][0]["confidence"] == 0.7
