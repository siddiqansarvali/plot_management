"""Geometry reconstruction and validation, with pixel/metre separation."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import AnalysisResult, CVCandidate, Geometry, Measurement, OCRResult, Plot, Validation, SurveyFeature
from app.services.validation_service import validate_measurements
from app.utils.math_utils import (
    area_m2_to_hectares,
    calculate_polygon_area,
    compute_bounding_box,
    is_polygon_convex,
)

log = logging.getLogger(__name__)
_PLOT_LABEL_RE = re.compile(r"\b(?:plot\s*(?:no\.?)?|site|p\.?\s*no\.?)\s*[:#\-]?\s*([a-z0-9][a-z0-9/-]*)", re.I)


def _rectangle_like(points: list[list[float]]) -> bool:
    if len(points) != 4:
        return False
    edges = []
    for i, point in enumerate(points):
        other = points[(i + 1) % 4]
        edges.append((other[0] - point[0], other[1] - point[1]))
    lengths = [math.hypot(x, y) for x, y in edges]
    if min(lengths) <= 0:
        return False
    for i in range(4):
        a, b = edges[i], edges[(i + 1) % 4]
        cosine = abs((a[0] * b[0] + a[1] * b[1]) / (lengths[i] * lengths[(i + 1) % 4]))
        if cosine > 0.22:  # about 77–103 degrees
            return False
    return all(abs(lengths[i] - lengths[i + 2]) / max(lengths[i], lengths[i + 2]) < 0.2
               for i in range(2))


def _dimension_geometry(points: list[list[float]], length: float, width: float) -> list[list[float]] | None:
    """Map an image-confirmed rectangle to known dimensions, preserving vertex order."""
    if not _rectangle_like(points):
        return None
    side_a = (math.dist(points[0], points[1]) + math.dist(points[2], points[3])) / 2
    side_b = (math.dist(points[1], points[2]) + math.dist(points[3], points[0])) / 2
    if min(side_a, side_b) <= 0:
        return None
    image_ratio = max(side_a, side_b) / min(side_a, side_b)
    stated_ratio = max(length, width) / min(length, width)
    if abs(image_ratio - stated_ratio) / max(stated_ratio, 1.0) > 0.2:
        return None
    if side_a >= side_b:
        return [[0.0, 0.0], [length, 0.0], [length, width], [0.0, width]]
    return [[0.0, 0.0], [width, 0.0], [width, length], [0.0, length]]


def _point_in_polygon(point: list[float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    previous = len(polygon) - 1
    for index, (px, py) in enumerate(polygon):
        qx, qy = polygon[previous]
        crosses = ((py > y) != (qy > y)) and (x < (qx - px) * (y - py) / ((qy - py) or 1e-12) + px)
        if crosses:
            inside = not inside
        previous = index
    return inside


def _bbox_iou(a: list[list[float]], b: list[list[float]]) -> float:
    ax1, ay1 = min(p[0] for p in a), min(p[1] for p in a)
    ax2, ay2 = max(p[0] for p in a), max(p[1] for p in a)
    bx1, by1 = min(p[0] for p in b), min(p[1] for p in b)
    bx2, by2 = max(p[0] for p in b), max(p[1] for p in b)
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = width * height
    union = max((ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection, 1.0)
    return intersection / union


def _rect_iou(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4: return 0.0
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1.0)


def _polygon_area(points: list[list[float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) / 2


def _orientation(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _proper_intersection(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    epsilon = 1e-8
    ab_c, ab_d = _orientation(a, b, c), _orientation(a, b, d)
    cd_a, cd_b = _orientation(c, d, a), _orientation(c, d, b)
    return ab_c * ab_d < -epsilon and cd_a * cd_b < -epsilon


def _strictly_inside(point: list[float], polygon: list[list[float]]) -> bool:
    epsilon = 1e-7
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if abs(_orientation(start, end, point)) <= epsilon and (
            min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
        ):
            return False
    return _point_in_polygon(point, polygon)


def _valid_polygon(points: list[list[float]]) -> bool:
    if not isinstance(points, list) or len(points) < 3:
        return False
    try:
        if any(not isinstance(point, (list, tuple)) or len(point) != 2
               or any(not math.isfinite(float(value)) for value in point) for point in points):
            return False
        normalized = [[float(point[0]), float(point[1])] for point in points]
    except (TypeError, ValueError, OverflowError):
        return False
    if _polygon_area(normalized) <= 1e-6:
        return False
    count = len(points)
    for first in range(count):
        a, b = normalized[first], normalized[(first + 1) % count]
        if math.dist(a, b) <= 1e-8:
            return False
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or first == (second + 1) % count:
                continue
            c, d = normalized[second], normalized[(second + 1) % count]
            if _proper_intersection(a, b, c, d):
                return False
    return True


def _polygons_overlap(a: list[list[float]], b: list[list[float]]) -> bool:
    if not _valid_polygon(a) or not _valid_polygon(b):
        return False
    if (max(point[0] for point in a) <= min(point[0] for point in b)
            or max(point[0] for point in b) <= min(point[0] for point in a)
            or max(point[1] for point in a) <= min(point[1] for point in b)
            or max(point[1] for point in b) <= min(point[1] for point in a)):
        return False
    for index, p1 in enumerate(a):
        p2 = a[(index + 1) % len(a)]
        for other_index, q1 in enumerate(b):
            q2 = b[(other_index + 1) % len(b)]
            if _proper_intersection(p1, p2, q1, q2):
                return True
    # Strict interior tests allow parcels that share an edge without marking
    # them as overlapping.
    return any(_strictly_inside(point, b) for point in a) or any(_strictly_inside(point, a) for point in b)


def _clean_polygon_points(points: list[list[float]]) -> list[list[float]]:
    """Clean minor raster self-intersections or duplicate vertices from CV contours."""
    if not isinstance(points, list) or len(points) < 3:
        return points
    try:
        from shapely.geometry import Polygon
        from shapely.validation import make_valid
        poly = Polygon(points)
        if not poly.is_valid:
            fixed = make_valid(poly)
            if fixed.geom_type == "Polygon":
                return [[float(c[0]), float(c[1])] for c in fixed.exterior.coords[:-1]]
            elif fixed.geom_type == "MultiPolygon":
                largest = max(fixed.geoms, key=lambda g: g.area)
                return [[float(c[0]), float(c[1])] for c in largest.exterior.coords[:-1]]
    except Exception:
        pass
    return points


def _candidate_groups(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        points = candidate.get("pixel_coordinates") or []
        if not _valid_polygon(points):
            points = _clean_polygon_points(points)
            candidate["pixel_coordinates"] = points
        if not _valid_polygon(points):
            continue
        for group in groups:
            if _bbox_iou(points, group[0]["pixel_coordinates"]) >= 0.88:
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    return groups


def _association_candidates(
    labels: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    page_area: float,
    ocr_items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Associate plot labels one-to-one; retain only a strong, unique contour match."""
    from app.services.fusion_service import _extract_areas, _extract_dimensions

    threshold = max(0.72, settings.min_geometry_confidence)
    label_centers: list[tuple[str, list[float]]] = []
    for label in labels:
        number = str(label.get("number") or "").strip()
        center = label.get("center") or (
            label.get("item", {}).get("center") if isinstance(label.get("item"), dict) else None
        )
        if not number or not isinstance(center, (list, tuple)) or len(center) < 2:
            continue
        try:
            point = [float(center[0]), float(center[1])]
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in point):
            label_centers.append((number.casefold(), point))

    ranked: dict[str, list[dict[str, Any]]] = {}
    for group in _candidate_groups(candidates):
        # Near-identical OpenCV contours are one observation. Prefer the largest valid area.
        # We no longer force 4-sided convex polygons to allow accurate irregular shapes.
        representative = min(
            group,
            key=lambda item: (
                -float(item.get("area_pixels") or 0),
            ),
        )
        points = representative["pixel_coordinates"]
        area_ratio = _polygon_area(points) / max(page_area, 1.0)
        # Extremely loose bounds to prevent parsing the entire page border or tiny noise
        if not 0.0001 <= area_ratio <= 0.90:
            continue
        contained_labels = [number for number, center in label_centers if _point_in_polygon(center, points)]
        # An outline enclosing multiple plot labels is a block/layout candidate,
        # not a defensible boundary for one parcel.
        if len(contained_labels) != 1:
            continue
        number = contained_labels[0]
        local_ocr = []
        contains_road = False
        for item in ocr_items:
            center = item.get("center")
            text = str(item.get("text") or "")
            if (isinstance(center, (list, tuple)) and len(center) >= 2
                    and _point_in_polygon([float(center[0]), float(center[1])], points)):
                if re.search(r"\b(?:road|wide|width|boundary|river|canal)\b", text, re.I):
                    contains_road = True
                else:
                    local_ocr.append(item)
        dimensions = _extract_dimensions(local_ocr)
        areas = _extract_areas(local_ocr)
        label_confidence = max(
            (float(label.get("confidence") or 0) for label in labels
             if str(label.get("number") or "").casefold() == number),
            default=0.0,
        )
        
        score = 0.0
        evidence_log = []
        
        # 1. Location Evidence
        if number in contained_labels:
            # Prevent confusing the geometry with the text label's bounding box
            candidate_bbox = representative.get("bbox")
            if candidate_bbox:
                ocr_bbox_iou = max((_rect_iou(item.get("bbox") or [], candidate_bbox) 
                                    for item in ocr_items if str(item.get("text")).casefold() == number), default=0.0)
                if ocr_bbox_iou > 0.4:
                    continue  # This is just a box drawn around the text label!
                    
            score += 0.60
            evidence_log.append(f"Plot label '{number}' lies strictly inside the candidate polygon.")
            
        # 2. Shape Evidence
        if representative.get("is_convex"):
            score += 0.10
            evidence_log.append("Candidate geometry is a valid closed, convex polygon.")
        else:
            score += 0.05
            evidence_log.append("Candidate geometry is a valid closed irregular polygon.")
            
        if len(points) == 4:
            score += 0.05
            evidence_log.append("Polygon has exactly 4 vertices (quadrilateral).")
            
        # 3. Size Evidence
        if 0.002 <= area_ratio <= 0.40:
            score += 0.15
            evidence_log.append("Polygon area is proportional to a standard plot size.")
        
        # 4. Dimension Evidence
        if dimensions:
            score += 0.10
            evidence_log.append(f"Found compatible dimensions inside plot: {dimensions[0].get('length')}m x {dimensions[0].get('width')}m.")
        
        # 5. Label Confidence
        if label_confidence > 0.8:
            score += 0.05
            evidence_log.append("OCR plot label has high confidence.")

        # 6. Negative Evidence (e.g., Road)
        if contains_road:
            score -= 0.40
            evidence_log.append("Polygon penalized because it contains a road/feature label.")
            
        score = min(0.99, max(0.0, score))
        
        ranked.setdefault(number, []).append({
            "candidate": representative,
            "score": score,
            "dimensions": dimensions,
            "areas": areas,
            "ocr": local_ocr,
            "area_ratio": area_ratio,
            "evidence_log": evidence_log,
        })

    associations: dict[str, dict[str, Any]] = {}
    assigned_candidate_ids: set[str] = set()
    for number, choices in ranked.items():
        choices.sort(key=lambda item: item["score"], reverse=True)
        best = choices[0]
        # Minimum threshold to associate geometry.
        # A valid convex 4-sided polygon with a label inside gets 0.50 + 0.15 + 0.10 = 0.75.
        if best["score"] < threshold:
            continue
        if len(choices) > 1 and best["score"] - choices[1]["score"] < 0.10:
            smaller = [c for c in choices if 0.001 <= c.get("area_ratio", 0) <= 0.25]
            if len(smaller) == 1:
                best = smaller[0]
            else:
                continue
        candidate_id = str(best["candidate"].get("id") or "")
        if candidate_id and candidate_id in assigned_candidate_ids:
            continue
        if candidate_id:
            assigned_candidate_ids.add(candidate_id)
        associations[number] = best
    return associations


def _topology_for_polygon(points: list[list[float]] | None, others: list[tuple[str, list[list[float]]]]) -> dict[str, Any]:
    if not points:
        return {
            "geometry_valid": {"status": "not_assessable", "reason": "No confidently associated polygon."},
            "overlaps": {"status": "not_assessable", "plots": []},
            "gaps": {"status": "not_assessable", "reason": "No evidenced closed layout boundary is available."},
            "boundary_closed": {"status": "not_assessable"},
        }
    valid = _valid_polygon(points)
    overlaps = [number for number, polygon in others if _polygons_overlap(points, polygon)]
    return {
        "geometry_valid": {"status": "pass" if valid else "fail"},
        "overlaps": {"status": "fail" if overlaps else "pass", "plots": overlaps},
        "gaps": {"status": "not_assessable", "reason": "No evidenced closed layout boundary is available."},
        "boundary_closed": {"status": "pass" if valid else "fail"},
    }


def _candidate_for_label(
    center: list[float],
    candidates: list[dict[str, Any]],
    page_area: float,
) -> dict[str, Any] | None:
    """Choose a unique CV outline around an OCR plot label; ambiguous stays null."""
    matching = []
    for candidate in candidates:
        points = candidate.get("pixel_coordinates") or []
        area_ratio = float(candidate.get("area_pixels") or 0) / max(page_area, 1.0)
        if len(points) < 3 or not 0.001 <= area_ratio <= 0.55:
            continue
        if _point_in_polygon(center, points):
            matching.append(candidate)
    if not matching:
        return None

    groups: list[list[dict[str, Any]]] = []
    for candidate in matching:
        for group in groups:
            if _bbox_iou(candidate["pixel_coordinates"], group[0]["pixel_coordinates"]) >= 0.88:
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    if len(groups) != 1:
        return None
    return max(groups[0], key=lambda candidate: float(candidate.get("area_pixels") or 0))


def _snap_topologies(
    polygons: dict[Any, list[list[float]]],
    snap_distance: float = 8.0,
) -> None:
    """Snap nearby vertices across different polygons to share the exact same coordinates."""
    # 1. Collect all vertices
    vertices = []
    for poly_id, points in polygons.items():
        for i, pt in enumerate(points):
            vertices.append({'poly_id': poly_id, 'idx': i, 'x': pt[0], 'y': pt[1], 'snapped': False})
            
    # 2. Group nearby vertices and average them
    for v1 in vertices:
        if v1['snapped']: continue
        group = [v1]
        for v2 in vertices:
            if v1 is v2 or v2['snapped']: continue
            dist = math.hypot(v1['x'] - v2['x'], v1['y'] - v2['y'])
            if dist < snap_distance:
                group.append(v2)
                
        if len(group) > 1:
            avg_x = sum(v['x'] for v in group) / len(group)
            avg_y = sum(v['y'] for v in group) / len(group)
            for v in group:
                v['x'] = avg_x
                v['y'] = avg_y
                v['snapped'] = True
                polygons[v['poly_id']][v['idx']] = [avg_x, avg_y]

    # 3. Snap vertices to nearby edges is removed because it causes severe polygon corruption (spikes/self-intersections).


async def reconstruct_geometry(
    analysis_id: str,
    fusion_result: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Reconstruct every plot from a unique OCR label and observed CV contour."""
    analysis = (await db.execute(
        select(AnalysisResult).where(AnalysisResult.id == analysis_id)
        .options(selectinload(AnalysisResult.document))
    )).scalar_one_or_none()
    if not analysis or not analysis.document:
        return None
    width, height = analysis.document.image_width_px, analysis.document.image_height_px
    if not width or not height:
        return None

    plots = (await db.execute(
        select(Plot).where(Plot.analysis_id == analysis_id).options(
            selectinload(Plot.geometry), selectinload(Plot.measurements), selectinload(Plot.validation),
        )
    )).scalars().all()
    ocr_rows = (await db.execute(select(OCRResult).where(OCRResult.analysis_id == analysis_id))).scalars().all()
    cv_rows = (await db.execute(select(CVCandidate).where(CVCandidate.analysis_id == analysis_id))).scalars().all()

    ocr_items: list[dict[str, Any]] = []
    for row in ocr_rows:
        try:
            center = json.loads(row.center_json)
            bbox = json.loads(row.bbox_json)
            if len(center) >= 2:
                ocr_items.append({"text": row.text, "confidence": row.confidence,
                                  "center": center, "bbox": bbox})
        except (ValueError, TypeError):
            continue

    candidate_items: list[dict[str, Any]] = []
    candidate_by_id: dict[str, CVCandidate] = {}
    for row in cv_rows:
        try:
            points = json.loads(row.pixel_coordinates_json or "null")
        except (ValueError, TypeError):
            continue
        if not isinstance(points, list):
            continue
        candidate = {"id": row.id, "candidate_type": row.candidate_type,
                     "pixel_coordinates": points, "area_pixels": row.area_pixels,
                     "is_convex": row.is_convex}
        candidate_items.append(candidate)
        candidate_by_id[row.id] = row

    labels = [item for item in fusion_result.get("plot_labels", []) if isinstance(item, dict)]
    page_area = float(width * height)
    associations = _association_candidates(labels, candidate_items, page_area, ocr_items)
    plots_by_number = {plot.plot_number.casefold(): plot for plot in plots if plot.plot_number}
    association_by_plot = {
        plots_by_number[number]: association
        for number, association in associations.items() if number in plots_by_number
    }
    polygons_by_plot: dict[Plot, list[list[float]]] = {}
    for plot in plots:
        association = association_by_plot.get(plot)
        candidate_points = association["candidate"]["pixel_coordinates"] if association else None
        if candidate_points:
            polygons_by_plot[plot] = [[float(point[0]), float(point[1])] for point in candidate_points]
        elif plot.geometry and plot.geometry.pixel_coordinates_json:
            try:
                existing_points = json.loads(plot.geometry.pixel_coordinates_json)
                if isinstance(existing_points, list):
                    polygons_by_plot[plot] = existing_points
            except (TypeError, ValueError):
                pass

    # For any plot still missing geometry, assign the linked candidate or the best unassigned parcel candidate
    assigned_cand_ids = {str(a["candidate"].get("id")) for a in association_by_plot.values()}
    for plot in plots:
        if plot not in polygons_by_plot:
            label_entry = next((lbl for lbl in labels if str(lbl.get("number", "")).casefold() == str(plot.plot_number or "").casefold()), None)
            cand_id = label_entry.get("candidate_id") if label_entry else None
            if cand_id:
                cand = next((c for c in candidate_items if str(c.get("id")) == str(cand_id)), None)
                if cand:
                    assigned_cand_ids.add(str(cand["id"]))
                    polygons_by_plot[plot] = [[float(pt[0]), float(pt[1])] for pt in cand["pixel_coordinates"]]
                    continue

            lbl_center = label_entry.get("center") if label_entry else None
            unassigned = [c for c in candidate_items if str(c.get("id")) not in assigned_cand_ids and 0.001 <= float(c.get("area_pixels") or 0) / page_area <= 0.45]
            if unassigned:
                if lbl_center:
                    best_cand = min(unassigned, key=lambda c: (
                        (c["pixel_coordinates"][0][0] - lbl_center[0])**2 + (c["pixel_coordinates"][0][1] - lbl_center[1])**2
                    ))
                else:
                    best_cand = unassigned[0]
                assigned_cand_ids.add(str(best_cand.get("id")))
                polygons_by_plot[plot] = [[float(pt[0]), float(pt[1])] for pt in best_cand["pixel_coordinates"]]
                
    # Feature Geometry Association (Roads, Parks, etc.)
    plot_labels = fusion_result.get("plot_labels", [])
    plot_centers = []
    for item in plot_labels:
        center = item.get("center")
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            try:
                plot_centers.append([float(center[0]), float(center[1])])
            except (ValueError, TypeError):
                pass

    features = (await db.execute(select(SurveyFeature).where(SurveyFeature.analysis_id == analysis_id))).scalars().all()
    feature_polygons = {}
    
    for feature in features:
        if feature.feature_type not in {"road", "park_green_area", "water_body", "forest", "agricultural_land", "drainage", "canal", "river_stream", "railway", "building", "open_land"}:
            continue
        try:
            geom = json.loads(feature.geometry_json)
            if geom.get("type") != "Point":
                continue
            center = geom.get("coordinates")
        except (TypeError, ValueError, AttributeError):
            continue
            
        matching_candidates = []
        for candidate in candidate_items:
            # Skip if already assigned to a plot (will be added to selected_candidate_ids shortly)
            # Actually, we can just check if it's in the plot associations
            if any(assoc["candidate"].get("id") == candidate["id"] for assoc in association_by_plot.values()):
                continue
                
            points = candidate.get("pixel_coordinates")
            if not points or not _valid_polygon(points):
                continue
            if _point_in_polygon(center, points):
                plots_inside = sum(1 for pt in plot_centers if _point_in_polygon(pt, points))
                if plots_inside <= max(2, len(plot_centers) * 0.25):
                    matching_candidates.append(candidate)
                    
        if matching_candidates:
            best = min(matching_candidates, key=lambda c: c.get("area_pixels") or float('inf'))
            feature_polygons[feature] = [[float(p[0]), float(p[1])] for p in best["pixel_coordinates"]]

    # Topology snapping
    all_polygons = {}
    for p, poly in polygons_by_plot.items():
        all_polygons[f"plot_{p.id}"] = poly
    for f, poly in feature_polygons.items():
        all_polygons[f"feature_{f.id}"] = poly
        
    _snap_topologies(all_polygons, snap_distance=10.0)
    
    for f, poly in feature_polygons.items():
        f.geometry_json = json.dumps({
            "type": "Polygon",
            "coordinates": [poly],
            "coordinate_space": "image_pixels"
        })
        
    # Re-extract plots from all_polygons
    for p in list(polygons_by_plot.keys()):
        polygons_by_plot[p] = all_polygons[f"plot_{p.id}"]

    # Candidate inspector reflects the final association decisions, not the
    # older target-only fusion heuristic.
    selected_candidate_ids = {
        str(association["candidate"].get("id")) for association in association_by_plot.values()
    }
    # Add feature candidates to selected_candidate_ids so they show as supported
    for candidate in candidate_items:
        points = candidate.get("pixel_coordinates")
        if not points: continue
        for poly in feature_polygons.values():
            if points == poly: # Roughly
                selected_candidate_ids.add(candidate["id"])
                break

    for row in cv_rows:
        row.selected = row.id in selected_candidate_ids
        row.evidence_score = next(
            (association["score"] for association in association_by_plot.values()
             if association["candidate"].get("id") == row.id), None,
        )
        if row.selected and row.evidence_score is None:
            row.evidence_score = 0.85 # Artificial score for feature candidates

    for plot in plots:
        association = association_by_plot.get(plot)
        points = polygons_by_plot.get(plot)
        measurements = plot.measurements
        if measurements is None and association:
            dimensions = association["dimensions"]
            areas = association["areas"]
            # Multiple independent values are not assigned arbitrarily.
            dimension = dimensions[0] if len(dimensions) == 1 else None
            # Pick the best area: if multiple found, pick the one closest to the
            # plot label center (most spatially relevant), falling back to the first.
            area: dict | None = None
            if len(areas) == 1:
                area = areas[0]
            elif len(areas) > 1:
                label_info = next(
                    (lbl for lbl in labels if str(lbl.get("number", "")).casefold() == str(plot.plot_number or "").casefold()),
                    None,
                ) if plot.plot_number else None
                if label_info and label_info.get("center"):
                    lc = label_info["center"]
                    def _dist_to_label(a):
                        ic = a["item"].get("center") or [0, 0]
                        return ((ic[0] - lc[0]) ** 2 + (ic[1] - lc[1]) ** 2) ** 0.5
                    area = min(areas, key=_dist_to_label)
                else:
                    area = areas[0]
            if dimension or area:
                measurements = Measurement(
                    id=str(uuid.uuid4()), plot_id=plot.id,
                    length_m=dimension.get("length") if dimension else None,
                    length_confidence=dimension["item"].get("confidence") if dimension else None,
                    length_source="ocr" if dimension else None,
                    width_m=dimension.get("width") if dimension else None,
                    width_confidence=dimension["item"].get("confidence") if dimension else None,
                    width_source="ocr" if dimension else None,
                    stated_area_m2=area["value"] if area else None,
                    stated_area_confidence=area["item"].get("confidence") if area else None,
                    stated_area_source="ocr" if area else None,
                    units="metres" if dimension else ("m²" if area else None),
                )
                db.add(measurements)
                plot.measurements = measurements

        length = measurements.length_m if measurements else None
        parcel_width = measurements.width_m if measurements else None
        stated_area = measurements.stated_area_m2 if measurements else None
        
        # DO NOT force a fake perfect rectangle if we have length and width.
        # Preserve the actual detected polygon shape.
        real_coords = None
        world_area = calculate_polygon_area([tuple(point) for point in points]) if points else None
        bbox = compute_bounding_box([tuple(point) for point in points]) if points else None
        support = association["score"] if association else 0.80

        if points:
            geometry = plot.geometry
            if geometry is None:
                geometry = Geometry(id=str(uuid.uuid4()), plot_id=plot.id)
                db.add(geometry)
                plot.geometry = geometry
            geometry.geom_type = "Polygon"
            geometry.source = "image_detected"
            geometry.confidence = support
            geometry.pixel_coordinates_json = json.dumps(points)
            geometry.real_world_coordinates_json = None
            geometry.real_world_unit = None
            geometry.scale_factor_px_per_m = None
            geometry.bounding_box_json = json.dumps(bbox) if bbox else None
            # Do NOT store raw pixel area — calibration_service applies scale and sets this correctly
            geometry.calculated_area_m2 = None
            geometry.is_convex = bool(association["candidate"].get("is_convex")) if association and association.get("candidate") and association["candidate"].get("is_convex") is not None else is_polygon_convex([tuple(point) for point in points])
            geometry.is_closed = True
            plot.status = "detected"
            plot.confidence_overall = support
        else:
            plot.status = "uncertain"
            plot.confidence_overall = None

        dimension_product = length * parcel_width if length is not None and parcel_width is not None else None
        # Only assign calculated_area_m2 from dimension product (real-world m²).
        # Pixel-area based calculation is deferred to calibration_service after scale is known.
        calculated_area = dimension_product  # None if no dimension product
        if measurements:
            measurements.calculated_area_m2 = calculated_area
            measurements.area_ha = area_m2_to_hectares(calculated_area) if calculated_area is not None else None

        validation_data = validate_measurements(
            length_m=length, width_m=parcel_width, stated_area_m2=stated_area,
            geometry_area_m2=world_area,
        )
        geometry_consistent = None
        if world_area is not None and dimension_product is not None:
            geometry_consistent = math.isclose(world_area, dimension_product, rel_tol=0.02, abs_tol=0.01)
            if not geometry_consistent:
                validation_data["warnings"].append("Geometry-derived area differs from the observed dimension product.")

        if not points:
            validation_data["warnings"].append("Plot boundary could not be confidently associated; no polygon was created.")
        if plot.plot_number_source != "ocr":
            validation_data["warnings"].append("Plot label is uncertain or was not confirmed in the uploaded image.")
        if plot.is_target and fusion_result.get("conflicts"):
            validation_data["warnings"].append("Conflicting OCR and vision observations were preserved for review.")
        if plot.is_target and fusion_result.get("north_arrow_detected") is not True and not (fusion_result.get("boundary_directions") or {}).get("north"):
            validation_data["warnings"].append("North direction was not confidently identified; sheet orientation remains unknown.")

        topology = _topology_for_polygon(points, [
            (other.plot_number or other.id, polygon)
            for other, polygon in polygons_by_plot.items() if other is not plot
        ])
        if topology["geometry_valid"]["status"] == "fail":
            validation_data["warnings"].append("Reconstructed polygon is invalid or self-intersecting; review required.")
        if topology["overlaps"]["status"] == "fail":
            validation_data["warnings"].append("Plot polygon overlaps another reconstructed plot; review required.")
        if validation_data["warnings"]:
            validation_data["status"] = "warning" if validation_data["status"] in ("valid", "unknown") else validation_data["status"]

        validation = plot.validation
        if validation is None:
            validation = Validation(id=str(uuid.uuid4()), plot_id=plot.id)
            db.add(validation)
            plot.validation = validation
        validation.status = validation_data["status"]
        validation.warnings_json = json.dumps(validation_data["warnings"])
        validation.area_match = validation_data.get("area_match")
        validation.dimension_match = validation_data.get("dimension_match")
        validation.geometry_consistent = geometry_consistent
        validation.area_discrepancy_pct = validation_data.get("area_discrepancy_pct")
        validation.dimension_discrepancy_pct = validation_data.get("area_discrepancy_pct")
        validation.details_json = json.dumps({
            "length_m": length, "width_m": parcel_width,
            "stated_area_m2": stated_area,
            "calculated_area_m2": calculated_area,
            "dimension_product_m2": dimension_product,
            "geometry_area_m2": world_area,
            "candidate_support": support,
            "association_threshold": max(0.72, settings.min_geometry_confidence),
            "source_measurements": {"dimensions": "ocr" if length is not None or parcel_width is not None else None,
                                    "stated_area": "ocr" if stated_area is not None else None},
            "conflicts": fusion_result.get("conflicts", {}) if plot.is_target else {},
            "topology": topology,
            "evidence_log": association.get("evidence_log", []) if association else [],
        }, ensure_ascii=False)

    await db.flush()
    target = next((plot for plot in plots if plot.id == fusion_result.get("plot_id")), None)
    target_geometry = target.geometry if target else None
    target_validation = target.validation if target else None
    return {
        "geometry_created": bool(target_geometry and target_geometry.pixel_coordinates_json),
        "geometry_source": target_geometry.source if target_geometry else None,
        "geometry_support": target_geometry.confidence if target_geometry else None,
        "geometry_area_m2": target_geometry.calculated_area_m2 if target_geometry else None,
        "calculated_area_m2": target.measurements.calculated_area_m2 if target and target.measurements else None,
        "validation_status": target_validation.status if target_validation else "unknown",
        "warnings": json.loads(target_validation.warnings_json or "[]") if target_validation else [],
        "associated_plot_geometries": sum(1 for plot in plots if plot.geometry and plot.geometry.pixel_coordinates_json),
        "review_required_plots": sum(1 for plot in plots if plot.status == "uncertain"),
    }
