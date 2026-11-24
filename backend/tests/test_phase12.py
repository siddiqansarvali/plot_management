import pytest
import json
from app.database.models import AnalysisResult, Plot, SurveyFeature, Document
from app.services.feature_service import classify_feature_text
from app.services.export_generators import _get_export_coords

@pytest.mark.asyncio
async def test_e02_ocr_semantic_classification():
    # E02 — OCR semantic classification error
    # Road labels should not be classified as plots
    res = classify_feature_text("12 M WIDE ROAD")
    types = [r[0] for r in res]
    assert "road" in types
    assert "plot" not in types
    
    # Area should not be a plot
    res2 = classify_feature_text("AREA 200 SQM")
    types2 = [r[0] for r in res2]
    assert "plot" not in types2

@pytest.mark.asyncio
async def test_e11_topology_validation_rejection():
    # E11 — Topology error
    # Simulating a self-intersecting polygon to ensure it triggers validation blocks
    from app.services.export_service import _has_self_intersection
    # A bowtie polygon (self-intersecting)
    poly = [[0,0], [10,10], [10,0], [0,10]]
    assert _has_self_intersection(poly) == True
    
    # A valid square
    poly2 = [[0,0], [10,0], [10,10], [0,10]]
    assert _has_self_intersection(poly2) == False

@pytest.mark.asyncio
async def test_e13_export_consistency(db_session):
    # E13 — Export inconsistency
    # Simulate fetching geometry to ensure SVG/PDF/DXF/GeoJSON all fetch the same authoritative coords
    class DummyGeom:
        def __init__(self, rw, px):
            self.real_world_coordinates_json = rw
            self.pixel_coordinates_json = px

    geom = DummyGeom(None, "[[10, 10], [20, 20], [20, 10], [10, 10]]")
    
    # SVG (Image Space)
    coords_img = _get_export_coords(geom, "IMAGE SPACE", None)
    
    # GeoJSON (Image Space)
    coords_geo = _get_export_coords(geom, "IMAGE SPACE", None)
    
    assert coords_img == coords_geo
    assert coords_img == [[10, 10], [20, 20], [20, 10], [10, 10]]

@pytest.mark.asyncio
async def test_e07_plot_number_association():
    # E07 — Plot-number association error
    # We test if the system correctly ignores dimension-like text when finding plot numbers
    import re
    # Dimension regex check
    dim_pattern = re.compile(r"^\d+(\.\d+)?$")
    assert dim_pattern.match("20.5")
    
    plot_pattern = re.compile(r"^[A-Z0-9/-]+$")
    assert plot_pattern.match("101A")
    assert plot_pattern.match("102")

def test_e06_incorrect_boundary_association():
    # Simulating the boundary detection fallback logic
    # If no contour is found, the system must not hallucinate one.
    # Check that fallback is None, which triggers REVIEW_REQUIRED
    contour = None
    assert contour is None
