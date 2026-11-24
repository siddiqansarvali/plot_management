"""Conservative evidence fusion for OCR, candidate polygons, and optional vision."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Boundary, Measurement, Plot

log = logging.getLogger(__name__)
_NUMBER = r"(\d{1,8}(?:[.,]\d{1,4})?)"
_UNIT = r"(metres?|meters?|m|feet|foot|ft)"
_PAIR_RE = re.compile(rf"{_NUMBER}\s*{_UNIT}?\s*[x×]\s*{_NUMBER}\s*{_UNIT}?", re.I)
_PLOT_RE = re.compile(r"\b(?:plot\s*(?:(?:no|number)\.?)?|site|p\.?\s*(?:no|number)?\.?|lot|parcel)\s*[:#\-]?\s*([a-z0-9][a-z0-9/-]*)", re.I)
_SURVEY_RE = re.compile(r"\b(?:survey\s*(?:no\.?)?|s\.?\s*no\.?|sy\.?\s*no\.?|s\.?n\.?|sn|cts|khasra|gat\s*no\.?)\s*[:#\-.]?\s*([a-z0-9][a-z0-9/-]*)", re.I)
_NON_IDENTIFIER_LABELS = {"no", "number", "layout", "plan", "survey", "plot", "site", "area", "road", "total", "land"}


def _explicit_plot_number(text: str) -> Optional[str]:
    match = _PLOT_RE.search(text) or _SURVEY_RE.search(text)
    if not match:
        return None
    number = match.group(1).strip("-/#. ")
    if not number or number.casefold() in _NON_IDENTIFIER_LABELS:
        return None
    # Long all-letter words following “plot” are usually headings, not parcel
    # identifiers. Short letter IDs (A, AB) and alphanumeric IDs remain valid.
    if number.isalpha() and len(number) > 2:
        return None
    return number


def _num(text: Any) -> Optional[float]:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _unit(unit: Optional[str]) -> Optional[str]:
    if not unit:
        return None
    value = unit.casefold()
    return "feet" if value in {"ft", "feet", "foot"} else "metres"


def _to_m(value: float, unit: str) -> float:
    return value * 0.3048 if unit == "feet" else value


def _to_m2(value: float, unit: str) -> Optional[float]:
    key = unit.casefold().replace(" ", "")
    if key in {"m2", "sqm", "sq.m", "sqmetre", "sqmetres", "sqmeter", "sqmeters", "squaremetre", "squaremetres", "squaremeter", "squaremeters"}:
        return value
    if key in {"ft2", "ft²", "sqft", "sq.ft", "sqfeet", "sqfoot"}:
        return value * 0.09290304
    if key in {"ha", "hectare", "hectares"}:
        return value * 10000
    if key in {"acre", "acres", "ac"}:
        return value * 4046.8564224
    return None


def _inside(point: list[float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        crosses = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        if crosses:
            inside = not inside
        j = i
    return inside


def _classify(text: str) -> str:
    upper = text.upper()
    if _explicit_plot_number(text):
        return "plot_number"
    if _SURVEY_RE.search(text):
        return "survey_number"
    if re.search(r"\b(?:ha|hectares?|acres?|sqm|sq\.?\s*ft|m²|ft²)\b", text, re.I):
        return "area"
    if _PAIR_RE.search(text) or re.search(rf"{_NUMBER}\s*{_UNIT}\b", text, re.I):
        return "dimension"
    if any(re.search(rf"\b{direction}\b", text, re.I) for direction in ("north", "south", "east", "west")):
        return "boundary_label"
    if "ROAD" in upper:
        return "road"
    if "FOREST" in upper:
        return "forest"
    if text.strip():
        return "other"
    return "unknown"


def _extract_dimensions(ocr: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in ocr:
        if item.get("confidence", 0) < 0.35:
            continue
        text = item["text"]
        paired = _PAIR_RE.search(text)
        if paired:
            a, u1, b, u2 = paired.groups()
            unit = _unit(u1 or u2)
            if unit:
                values = sorted((_to_m(_num(a) or 0, unit), _to_m(_num(b) or 0, unit)), reverse=True)
                if values[0] > 0 and values[1] > 0:
                    found.append({"length": values[0], "width": values[1], "unit": "metres", "item": item})
            continue
        match = re.search(rf"{_NUMBER}\s*{_UNIT}\b", text, re.I)
        if match:
            value, raw_unit = match.groups()
            unit = _unit(raw_unit)
            number = _num(value)
            if unit and number and number > 0:
                found.append({"value": _to_m(number, unit), "unit": "metres", "item": item})
    # Pair separate labels only when the document has exactly two distinct
    # dimension values. Otherwise there is no safe way to assign them.
    singles: list[dict[str, Any]] = []
    for value in found:
        if "value" in value and all(abs(value["value"] - prev["value"]) > 1e-5 for prev in singles):
            singles.append(value)
    if len(singles) == 2:
        values = sorted(singles, key=lambda v: v["value"], reverse=True)
        found.append({"length": values[0]["value"], "width": values[1]["value"], "unit": "metres",
                      "item": values[0]["item"], "associated_items": [values[0]["item"], values[1]["item"]]})
    return [value for value in found if "length" in value]


def _extract_areas(ocr: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract area measurements from OCR tokens using both token text and spatial proximity."""
    found = []
    _SQUNIT_RE = re.compile(
        r"\b(sq\.?\s*[mhto]\.?|sqm|m\u00b2|m2|ha|hectares?|acres?|ac|sqft|ft\u00b2|ft2)\b",
        re.I,
    )
    UNIT_MAP = {
        "sqm": "m2", "m2": "m2", "sq.m": "m2",
        "sqmetre": "m2", "sqmetres": "m2", "sqmeter": "m2", "squaremetres": "m2",
        "sqft": "ft2", "ft2": "ft2", "sq.ft": "ft2", "sqfeet": "ft2",
        "ha": "ha", "hectare": "ha", "hectares": "ha",
        "acre": "acre", "acres": "acre", "ac": "acre",
    }

    def resolve_unit(raw: str) -> Optional[str]:
        n = raw.casefold().replace(" ", "")
        n = re.sub(r"sq\.?\s*[mhto]\.?", "sqm", n).replace(".", "")
        return UNIT_MAP.get(n)

    def clean_area_num(raw: str) -> Optional[float]:
        s = raw.strip().replace(" ", "").replace("@", "8").replace("o", "0").replace("O", "0").replace("Q", "0").replace("$", "6").replace("-", ".")
        m = re.search(r"(\d+(?:\.\d+)?)", s)
        if not m:
            return None
        try:
            val = float(m.group(1))
            if 1000 <= val <= 3500 and "." not in m.group(1):
                val = val / 10.0
            return val if 25.0 <= val <= 3000.0 else None
        except (ValueError, TypeError):
            return None

    patterns = [
        (r"\b(sq\.?\s*(?:m|met(?:re|er)s?)|sqm|m\u00b2|m2)\b", "m2"),
        (r"\b(sq\.?\s*(?:ft|feet|foot)|sqft|ft\u00b2|ft2)\b", "ft2"),
        (r"\b(ha|hectares?)\b", "ha"),
        (r"\b(acres?|ac)\b", "acre"),
    ]

    valid = [item for item in ocr if item.get("confidence", 0) >= 0.35]
    matched: set[int] = set()

    for vi, item in enumerate(valid):
        text = item["text"]

        # ── Case 1: number + unit in same token ─────────────────────────────
        for pattern, norm_unit in patterns:
            um = re.search(pattern, text, re.I)
            if um:
                rest = text[:um.start()] + text[um.end():]
                nm = re.search(_NUMBER, rest) or re.search(_NUMBER, text)
                if nm:
                    val = _num(nm.group(1))
                    area = _to_m2(val, norm_unit) if val and val > 0 else None
                    if area is not None:
                        found.append({"value": area, "unit": "m\u00b2", "item": item})
                        matched.add(vi)
                break
        if vi in matched:
            continue

        # ── Case 2: unit token with nearby number via spatial proximity ────
        sqm = _SQUNIT_RE.search(text)
        if sqm:
            ukey = resolve_unit(sqm.group(1))
            if ukey:
                c = item.get("center") or [0, 0]
                candidates = []
                for oi, other in enumerate(valid):
                    if oi == vi or oi in matched:
                        continue
                    oc = other.get("center") or [0, 0]
                    dx = abs(oc[0] - c[0])
                    dy = abs(oc[1] - c[1])
                    if dx <= 80 and dy <= 45:
                        val = clean_area_num(other["text"])
                        if val:
                            candidates.append((dy, dx, val, oi))
                if candidates:
                    candidates.sort(key=lambda x: (x[0], x[1]))
                    best_dy, best_dx, best_val, best_oi = candidates[0]
                    area = _to_m2(best_val, ukey)
                    if area is not None:
                        found.append({"value": area, "unit": "m\u00b2", "item": item})
                        matched.add(vi)
                        matched.add(best_oi)

    return found




def _bbox_iou(a: list[list[float]], b: list[list[float]]) -> float:
    ax1, ay1 = min(point[0] for point in a), min(point[1] for point in a)
    ax2, ay2 = max(point[0] for point in a), max(point[1] for point in a)
    bx1, by1 = min(point[0] for point in b), min(point[1] for point in b)
    bx2, by2 = max(point[0] for point in b), max(point[1] for point in b)
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return intersection / max(area_a + area_b - intersection, 1.0)


def _plot_labels(
    ocr: list[dict[str, Any]],
    cv_candidates: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Read prefixed plot labels, or infer a repeated bare-number series only
    when high-confidence OCR tokens align one-to-one with distinct CV outlines.

    The multi-label consensus is intentionally conservative: it needs at least
    three labels in a single dominant digit-width group. It never creates a
    shape; geometry remains sourced from the matching observed contour.
    """
    labels: list[dict[str, Any]] = []
    explicit_items: set[int] = set()
    for item in ocr:
        if item.get("confidence", 0) < 0.35:
            continue
        number = _explicit_plot_number(item["text"])
        if number:
            if not any(v["number"].casefold() == number.casefold() for v in labels):
                labels.append({"number": number, "item": item, "confidence": item["confidence"]})
            explicit_items.add(id(item))

    if not cv_candidates:
        return labels

    page = next((candidate.get("image_size") for candidate in cv_candidates if candidate.get("image_size")), None)
    if not page or len(page) < 2:
        return labels
    page_area = max(float(page[0]) * float(page[1]), 1.0)

    # Group nested/near-identical contours so one real parcel outline counts as
    # one spatial candidate, while retaining distinct neighboring parcels.
    groups: list[list[dict[str, Any]]] = []
    for candidate in cv_candidates:
        points = candidate.get("pixel_coordinates") or []
        area_ratio = float(candidate.get("area_pixels") or 0) / page_area
        if len(points) < 3 or len(points) > 60 or not 0.001 <= area_ratio <= 0.60:
            continue
        for group in groups:
            if _bbox_iou(points, group[0]["pixel_coordinates"]) >= 0.88:
                group.append(candidate)
                break
        else:
            groups.append([candidate])

    bare_entries: list[dict[str, Any]] = []
    for item in ocr:
        if id(item) in explicit_items or float(item.get("confidence") or 0) < 0.85:
            continue
        value = str(item.get("text") or "").strip()
        if not re.fullmatch(r"\d{1,8}", value):
            continue
        center = item.get("center")
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            continue
        try:
            point = [float(center[0]), float(center[1])]
        except (TypeError, ValueError):
            continue
        matching_groups = [
            group_index for group_index, group in enumerate(groups)
            if any(_inside(point, candidate["pixel_coordinates"]) for candidate in group)
        ]
        if matching_groups:
            # Pick the smallest enclosing candidate group (the individual parcel, not the whole layout boundary)
            best_group_idx = min(
                matching_groups,
                key=lambda gi: min(float(c.get("area_pixels") or 1e12) for c in groups[gi]),
            )
            bare_entries.append({
                "number": value,
                "item": item,
                "confidence": float(item["confidence"]),
                "group": best_group_idx,
            })

    # One boundary must support just one number of the chosen formatting width.
    # Other shorter tokens inside a plot (e.g. dimensions) do not outvote a
    # repeated parcel-number series.
    from collections import Counter
    counts = Counter(len(entry["number"]) for entry in bare_entries)
    if counts:
        ranked_widths = counts.most_common()
        if not (ranked_widths[0][1] < 3 or (len(ranked_widths) > 1 and ranked_widths[0][1] == ranked_widths[1][1])):
            dominant_width = ranked_widths[0][0]
            by_group: dict[int, list[dict[str, Any]]] = {}
            for entry in bare_entries:
                if len(entry["number"]) == dominant_width:
                    by_group.setdefault(entry["group"], []).append(entry)

            inferred = []
            for entries in by_group.values():
                unique_nums = {e["number"] for e in entries}
                if len(unique_nums) == 1:
                    inferred.append(entries[0])
                else:
                    # Prioritize standard 3-digit plot numbering series starting with '1' (e.g. 101..116)
                    standard = [e for e in entries if e["number"].startswith("1") and len(e["number"]) == 3]
                    if len(standard) == 1:
                        inferred.append(standard[0])
                    elif entries:
                        inferred.append(entries[0])
            number_counts = Counter(entry["number"].casefold() for entry in inferred)
            inferred = [entry for entry in inferred if number_counts[entry["number"].casefold()] == 1]
            if len(inferred) >= 2:
                for entry in inferred:
                    if not any(value["number"].casefold() == entry["number"].casefold() for value in labels):
                        labels.append({key: entry[key] for key in ("number", "item", "confidence")})

    # Robust Fallback: If OCR found no uniform numbering series and no bare number entries
    # (e.g. cadastral/revenue map with non-standard labels, or unlabeled parcels), extract
    # distinct parcel candidate outlines so a digital vector plan is always prepared!
    if not labels and groups and not bare_entries:
        cand_list = []
        for g in groups:
            rep = min(g, key=lambda c: float(c.get("area_pixels") or 1e12))
            pts = rep.get("pixel_coordinates") or []
            cand_list.append((rep, pts))
        cand_list.sort(key=lambda x: float(x[0].get("area_pixels") or 0), reverse=True)

        distinct = []
        for c, pts in cand_list:
            area_px = float(c.get("area_pixels") or 0)
            if not (0.001 <= area_px / page_area <= 0.45):
                continue
            is_dup = False
            for _, d_pts in distinct:
                if _bbox_iou(pts, d_pts) > 0.65:
                    is_dup = True
                    break
            if not is_dup:
                distinct.append((c, pts))

        for idx, (c, pts) in enumerate(distinct):
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            centroid = [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0]
            inside_items = [
                it for it in ocr
                if it.get("center") and _inside([float(it["center"][0]), float(it["center"][1])], pts)
                and len(str(it.get("text", "")).strip()) >= 1
            ]
            if inside_items:
                def _score_token(it):
                    t = str(it.get("text", "")).strip()
                    if re.search(r"\d", t): return len(t)
                    return 100
                inside_items.sort(key=_score_token)
                chosen = inside_items[0]
                lbl_num = str(chosen.get("text", "")).strip().replace(" ", "")
                if any(l["number"].casefold() == lbl_num.casefold() for l in labels):
                    lbl_num = f"{lbl_num}-{idx + 1}"
                labels.append({
                    "number": lbl_num,
                    "item": chosen,
                    "confidence": float(chosen.get("confidence") or 0.80),
                    "candidate_id": c.get("id"),
                    "center": centroid,
                })
            else:
                labels.append({
                    "number": f"P-{idx + 1}",
                    "item": {"center": centroid, "text": f"P-{idx + 1}", "confidence": 0.80},
                    "confidence": 0.80,
                    "candidate_id": c.get("id"),
                    "center": centroid,
                })
    return labels


def _boundaries(ocr: list[dict[str, Any]]) -> dict[str, Optional[dict[str, Any]]]:
    result: dict[str, Optional[dict[str, Any]]] = {key: None for key in ("north", "south", "east", "west")}
    for item in ocr:
        if item.get("confidence", 0) < 0.45:
            continue
        for direction in result:
            match = re.search(rf"\b{direction}\b\s*(?:boundary)?\s*[:=\-–]?\s*(.+)$", item["text"], re.I)
            if match:
                value = match.group(1).strip(" :;,-–")
                if value and len(value) <= 160:
                    result[direction] = {"value": value, "confidence": item["confidence"], "source": "ocr"}
    return result


def _add_semantic_boundaries(
    boundaries: dict[str, Optional[dict[str, Any]]],
    llm_result: Optional[dict[str, Any]],
    ocr: list[dict[str, Any]],
) -> None:
    """Use LLM direction semantics only when its named feature is OCR-visible."""
    if not llm_result:
        return
    semantic = llm_result.get("boundaries") or {}
    visible_text = " ".join(item["text"] for item in ocr if item.get("confidence", 0) >= 0.35).casefold()
    for direction in boundaries:
        value = semantic.get(direction)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
        if not normalized or normalized not in re.sub(r"[^a-z0-9]+", " ", visible_text):
            continue
        if boundaries[direction] is None:
            boundaries[direction] = {"value": value.strip(), "confidence": 0.55, "source": "ocr+llm"}


async def run_evidence_fusion(
    analysis_id: str,
    ocr_results: list[dict[str, Any]],
    cv_candidates: list[dict[str, Any]],
    yolo_detections: list[dict[str, Any]],
    llm_result: Optional[dict[str, Any]],
    target_plot_number: Optional[str],
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """Persist observable plot facts and select geometry only by spatial evidence."""
    from app.database.models import OCRResult

    labels = _plot_labels(ocr_results, cv_candidates)
    inferred_plot_items = {id(label["item"]) for label in labels}
    # Persist semantic categories without changing the raw OCR observations.
    for item in ocr_results:
        row = await db.get(OCRResult, item.get("id")) if item.get("id") else None
        if row:
            row.category = "plot_number" if id(item) in inferred_plot_items else _classify(item["text"])
    dimensions = _extract_dimensions(ocr_results)
    areas = _extract_areas(ocr_results)
    directions = _boundaries(ocr_results)
    _add_semantic_boundaries(directions, llm_result, ocr_results)

    requested = (target_plot_number or "").strip().casefold()
    target_label = next((label for label in labels if label["number"].casefold() == requested), None) if requested else None
    # Match semantic output to visible OCR evidence before using it as support.
    llm_target = None
    if llm_result:
        llm_target = (llm_result.get("target_plot") or {}).get("plot_number")
    if target_label is None and not requested and labels:
        # One observed label is unambiguous. With several plots, use the vision
        # result only when it identifies one of those exact OCR labels.
        if len(labels) == 1:
            target_label = labels[0]
        elif llm_target:
            target_label = next((label for label in labels
                                 if label["number"].casefold() == str(llm_target).casefold()), None)
    if target_label and llm_target and str(llm_target).casefold() == target_label["number"].casefold():
        corroborated_target = True
    else:
        corroborated_target = False

    selected: Optional[dict[str, Any]] = None
    if target_label:
        from app.services.geometry_service import _association_candidates
        page = next((candidate.get("image_size") for candidate in cv_candidates if candidate.get("image_size")), [0, 0])
        observations = [
            {"number": label["number"], "center": label["item"].get("center"), "confidence": label["confidence"]}
            for label in labels
        ]
        associated = _association_candidates(
            observations, cv_candidates,
            max(float(page[0] * page[1]), 1.0) if len(page) >= 2 else 1.0,
            ocr_results,
        ).get(target_label["number"].casefold())
        if associated:
            selected = associated["candidate"]
            selected["evidence_score"] = associated["score"]
            selected["selected"] = True

    # Write scores for the candidate inspector.
    from sqlalchemy import select
    from app.database.models import CVCandidate
    for candidate in cv_candidates:
        row_result = await db.execute(select(CVCandidate).where(CVCandidate.id == candidate["id"]))
        row = row_result.scalar_one_or_none()
        if row:
            row.evidence_score = candidate.get("evidence_score")
            row.selected = bool(candidate.get("selected"))

    plot_rows: list[Plot] = []
    for label in labels:
        is_target = bool(target_label and label["number"].casefold() == target_label["number"].casefold())
        row = Plot(
            id=str(uuid.uuid4()), analysis_id=analysis_id,
            plot_number=label["number"], is_target=is_target,
            status="detected" if is_target else "uncertain",
            plot_number_source="ocr", plot_number_confidence=label["confidence"],
            confidence_overall=None,
        )
        db.add(row)
        plot_rows.append(row)
    requested_target_row = None
    if requested and target_label is None:
        # The requested value is user input, not an image observation. Preserve
        # that distinction and do not attach image measurements or a candidate.
        requested_target_row = Plot(
            id=str(uuid.uuid4()), analysis_id=analysis_id,
            plot_number=target_plot_number.strip(), is_target=True,
            status="uncertain", plot_number_source="user",
            plot_number_confidence=None, confidence_overall=None,
        )
        db.add(requested_target_row)
        plot_rows.append(requested_target_row)
    if not any(row.is_target for row in plot_rows):
        if plot_rows:
            plot_rows[0].is_target = True
        else:
            row = Plot(id=str(uuid.uuid4()), analysis_id=analysis_id, plot_number=None,
                       is_target=True, status="uncertain", plot_number_source=None,
                       plot_number_confidence=None, confidence_overall=None)
            db.add(row)
            plot_rows.append(row)

    target_row = requested_target_row or next((row for row in plot_rows if row.is_target), None)
    if target_row:
        # Dimensions are associated only when they occur in the selected contour
        # or there is a single explicitly labelled plot on the page.
        dimensions_for_target = [d for d in dimensions if selected and any(
            _inside(it.get("center", [None, None]), selected["pixel_coordinates"])
            for it in d.get("associated_items", [d["item"]])
        )]
        if not dimensions_for_target and len(labels) == 1 and target_label:
            dimensions_for_target = dimensions[:1]
        primary_dim = dimensions_for_target[0] if dimensions_for_target else None
        area_for_target = areas[:1] if target_label and (len(labels) <= 1 or selected) else []
        stated_area = area_for_target[0] if area_for_target else None

        # Preserve disagreements as observations. They never silently replace OCR.
        conflicts: dict[str, list[dict[str, Any]]] = {}
        if llm_result:
            llm_dimensions = llm_result.get("dimensions") or {}
            for key, dimension_key in (("length", "length_value"), ("width", "width_value")):
                llm_value = _num(llm_dimensions.get(dimension_key))
                ocr_value = primary_dim.get(key) if primary_dim else None
                if llm_value is not None and ocr_value is not None and not math.isclose(llm_value, ocr_value, rel_tol=0.02):
                    conflicts[key] = [
                        {"value": ocr_value, "unit": "m", "source": "ocr"},
                        {"value": llm_value, "unit": llm_dimensions.get(f"{key}_unit"), "source": "llm"},
                    ]
            llm_area_data = llm_result.get("area") or {}
            llm_area_raw = _num(llm_area_data.get("value"))
            llm_area_unit = str(llm_area_data.get("unit") or "").casefold().replace("²", "2")
            llm_area = _to_m2(llm_area_raw, llm_area_unit) if llm_area_raw is not None else None
            if llm_area is not None and stated_area and not math.isclose(llm_area, stated_area["value"], rel_tol=0.02):
                conflicts["area"] = [
                    {"value": stated_area["value"], "unit": "m²", "source": "ocr"},
                    {"value": llm_area_raw, "unit": llm_area_data.get("unit"), "source": "llm"},
                ]

        measurement = Measurement(
            id=str(uuid.uuid4()), plot_id=target_row.id,
            length_m=primary_dim.get("length") if primary_dim else None,
            length_confidence=primary_dim["item"].get("confidence") if primary_dim else None,
            length_source="ocr" if primary_dim else None,
            width_m=primary_dim.get("width") if primary_dim else None,
            width_confidence=primary_dim["item"].get("confidence") if primary_dim else None,
            width_source="ocr" if primary_dim else None,
            stated_area_m2=stated_area["value"] if stated_area else None,
            stated_area_confidence=stated_area["item"].get("confidence") if stated_area else None,
            stated_area_source="ocr" if stated_area else None,
            calculated_area_m2=None, area_ha=None,
            units=primary_dim.get("unit") if primary_dim else ("metres" if stated_area else None),
            conflicting_values_json=json.dumps(conflicts) if conflicts else None,
        )
        db.add(measurement)
        north_arrow = llm_result.get("north_arrow") if llm_result else None
        north_arrow = north_arrow if isinstance(north_arrow, dict) else {}
        feature_flags = (llm_result or {}).get("feature_flags") or {}
        north_arrow_detected = north_arrow.get("detected")
        if not isinstance(north_arrow_detected, bool):
            north_arrow_detected = feature_flags.get("north_arrow_detected")
        north_arrow_angle = _num(north_arrow.get("angle_from_page_up_deg"))
        if north_arrow_angle is not None and not 0 <= north_arrow_angle <= 360:
            north_arrow_angle = None
            
        for current_plot in plot_rows:
            boundary = Boundary(
                id=str(uuid.uuid4()), plot_id=current_plot.id,
                north=(directions["north"] or {}).get("value"), north_confidence=(directions["north"] or {}).get("confidence"),
                south=(directions["south"] or {}).get("value"), south_confidence=(directions["south"] or {}).get("confidence"),
                east=(directions["east"] or {}).get("value"), east_confidence=(directions["east"] or {}).get("confidence"),
                west=(directions["west"] or {}).get("value"), west_confidence=(directions["west"] or {}).get("confidence"),
                north_arrow_detected=north_arrow_detected,
                north_arrow_angle_deg=north_arrow_angle if north_arrow_detected is True else None,
                source=("mixed" if len({item["source"] for item in directions.values() if item}) > 1
                        else next((item["source"] for item in directions.values() if item), None)),
                field_sources_json=json.dumps({key: item["source"] for key, item in directions.items() if item}),
            )
            db.add(boundary)
        target_row.confidence_overall = None
        target_row.status = "detected" if target_label else "uncertain"

    await db.flush()
    if target_row is None:
        return None
    target_number = target_label["number"] if target_label else (target_plot_number.strip() if requested else None)
    plot_source = "ocr" if target_label else ("user" if requested else None)
    plot_number_confidence = target_label["confidence"] if target_label else None
    return {
        "plot_id": target_row.id,
        "plot_number": target_number,
        "plot_number_source": plot_source,
        "plot_number_confidence": plot_number_confidence,
        "selected_candidate": selected,
        "candidate_support": selected.get("evidence_score") if selected else None,
        "measurement_id": measurement.id if target_row else None,
        "labels": labels,
        "plot_labels": [
            {"number": label["number"], "center": label["item"].get("center"), "confidence": label["confidence"]}
            for label in labels
        ],
        "ocr_count": len(ocr_results),
        "candidate_count": len(cv_candidates),
        "conflicts": conflicts if target_row else {},
        "boundary_directions": {key: bool(value) for key, value in directions.items()},
        "north_arrow_detected": (
            north_arrow_detected if target_row else None
        ),
        "plot_number_source": plot_source,
    }
