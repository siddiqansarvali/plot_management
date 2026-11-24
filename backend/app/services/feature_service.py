"""Evidence-only classification of survey labels for the digital redraw."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SurveyFeature

log = logging.getLogger(__name__)

# Keep this list small and explicit. A match means the text was read from the
# survey; it does not claim that the full physical extent was found.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unknown_feature", re.compile(r"\b(?:water\s*/\s*drainage|water\s+drainage|nallah|nala|channel)\b", re.I)),
    ("survey_reference", re.compile(r"\b(?:survey\s*(?:no\.?|number)|sy\.?\s*no\.?|s\.?\s*no\.?)\b", re.I)),
    # Plot identifiers are numeric, or short letter codes optionally followed
    # by digits. A page heading such as “PLOT LAYOUT” is not a plot feature.
    ("plot", re.compile(r"\bplot\s*(?:no\.?|number)?\s*[:#\-]?\s*(?:\d+[a-z0-9/-]*|[a-z]{1,2}(?:[-/]\d+[a-z0-9/-]*)?)\b", re.I)),
    ("boundary_wall", re.compile(r"\b(?:boundary|compound)\s+wall\b", re.I)),
    ("utility_corridor", re.compile(r"\b(?:electric(?:ity)?\s+(?:line|corridor)|power\s+line|transmission\s+line|utility\s+corridor|ht\s+line)\b", re.I)),
    ("agricultural_land", re.compile(r"\b(?:agricultural\s+land|farm(?:ing)?\s+land|farmland|crop\s+land)\b", re.I)),
    ("park_green_area", re.compile(r"\b(?:park|green\s+area)\b", re.I)),
    ("open_land", re.compile(r"\b(?:open\s+land|vacant\s+land)\b", re.I)),
    ("railway", re.compile(r"\b(?:railway|railroad|rail\s+line)\b", re.I)),
    ("water_body", re.compile(r"\b(?:water\s+body|lake|pond)\b", re.I)),
    ("canal", re.compile(r"\bcanal\b", re.I)),
    ("river_stream", re.compile(r"\b(?:river|stream)\b", re.I)),
    ("drainage", re.compile(r"\b(?:drain|drainage)\b", re.I)),
    ("road", re.compile(r"\broad\b", re.I)),
    ("forest", re.compile(r"\b(?:forest|woodland)\b", re.I)),
    ("pathway", re.compile(r"\b(?:pathway|access\s+path|footpath)\b", re.I)),
    ("layout_boundary", re.compile(r"\b(?:layout|site)\s+boundary\b", re.I)),
    ("north_arrow", re.compile(r"\bnorth\s+arrow\b", re.I)),
    ("dimension_line", re.compile(r"\bdimension\s+line\b", re.I)),
    ("building", re.compile(r"\b(?:building|house|bungalow)\b", re.I)),
)

_VISION_FLAGS = {
    "road": "road_detected",
    "forest": "forest_detected",
    "water_body": "water_body_detected",
    "building": "buildings_detected",
}
_OCR_REVIEW_THRESHOLD = 0.60


def classify_feature_text(text: str) -> list[tuple[str, list[str]]]:
    """Return only feature classes explicitly named in the OCR text."""
    if not text or not text.strip():
        return []
    matches: list[tuple[str, list[str]]] = []
    for feature_type, pattern in _RULES:
        if not pattern.search(text):
            continue
        possible = ["canal", "drainage", "river_stream"] if feature_type == "unknown_feature" else []
        matches.append((feature_type, possible))
    return matches


def _anchor(item: dict[str, Any]) -> list[float] | None:
    center = item.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            x, y = float(center[0]), float(center[1])
            return [x, y] if math.isfinite(x) and math.isfinite(y) else None
        except (TypeError, ValueError):
            return None
    bbox = item.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x1, y1, x2, y2 = (float(value) for value in bbox)
            center = [(x1 + x2) / 2, (y1 + y2) / 2]
            return center if all(math.isfinite(value) for value in center) else None
        except (TypeError, ValueError):
            return None
    return None


async def extract_survey_features(
    analysis_id: str,
    ocr_results: list[dict[str, Any]],
    llm_result: dict[str, Any] | None,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Persist explicit OCR feature labels with their image-space text anchor.

    The geometry is a Point at the OCR label only. It is intentionally not
    expanded into a road, waterway, vegetation, or plot footprint.
    """
    llm_flags = (llm_result or {}).get("feature_flags") or {}
    llm_features = (llm_result or {}).get("features") or []
    features: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()

    for item in ocr_results:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            ocr_confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            ocr_confidence = 0.0
        if not math.isfinite(ocr_confidence):
            ocr_confidence = 0.0
        ocr_confidence = min(1.0, max(0.0, ocr_confidence))
        point = _anchor(item)

        for detected_type, possible_types in classify_feature_text(text):
            uncertain = detected_type != "unknown_feature" and ocr_confidence < _OCR_REVIEW_THRESHOLD
            feature_type = "unknown_feature" if uncertain else detected_type
            possible = possible_types or ([detected_type] if uncertain else [])
            key_point = point or [0.0, 0.0]
            key = (feature_type, text.casefold(), round(key_point[0] / 12), round(key_point[1] / 12))
            if key in seen:
                continue
            seen.add(key)

            corroborating_flag = _VISION_FLAGS.get(detected_type)
            vision_support = bool(corroborating_flag and llm_flags.get(corroborating_flag) is True)
            if not vision_support:
                vision_support = any(
                    isinstance(observation, dict)
                    and observation.get("type") == detected_type
                    and float(observation.get("confidence") or 0) >= 0.5
                    and observation.get("evidence")
                    for observation in llm_features
                )
            source = "ocr+vision" if vision_support and not uncertain else "ocr"
            warning = None
            if uncertain:
                warning = "OCR confidence is low; confirm the feature type and label."
            elif detected_type == "unknown_feature":
                warning = "The survey text does not distinguish this feature type; review required."
            if point is None:
                warning = "Feature label was recognized but no reliable image anchor was returned."

            feature = SurveyFeature(
                id=str(uuid.uuid4()),
                analysis_id=analysis_id,
                feature_type=feature_type,
                label=text,
                geometry_json=(json.dumps({
                    "type": "Point",
                    "coordinates": point,
                    "coordinate_space": "image_pixels",
                }) if point is not None else None),
                coordinate_space="image_pixels",
                confidence=ocr_confidence,
                source=source,
                evidence_text=text,
                original_type=feature_type,
                possible_types_json=json.dumps(possible) if possible else None,
                warning=warning,
                review_required=bool(uncertain or detected_type == "unknown_feature" or point is None),
                review_status="detected",
            )
            db.add(feature)
            features.append({
                "id": feature.id,
                "feature_type": feature_type,
                "label": text,
                "geometry": json.loads(feature.geometry_json) if feature.geometry_json else None,
                "confidence": ocr_confidence,
                "source": source,
                "evidence_text": text,
                "original_type": feature_type,
                "possible_types": possible,
                "warning": warning,
                "review_required": feature.review_required,
                "review_status": "detected",
            })
            if len(features) >= 500:
                log.warning("Feature extraction capped at 500 observations for analysis %s", analysis_id)
                await db.flush()
                return features

    # Vision can identify a semantic feature with no OCR label, but this schema
    # deliberately stores no model-invented coordinates. Such observations are
    # visible in the review list and cannot be drawn into the SVG until located.
    observed_ocr_types = {feature["feature_type"] for feature in features}
    for observation in llm_features:
        if not isinstance(observation, dict):
            continue
        feature_type = observation.get("type")
        confidence = observation.get("confidence")
        evidence = observation.get("evidence")
        if (
            feature_type not in {kind for kind, _ in _RULES} | {"unknown_feature"}
            or feature_type in observed_ocr_types
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or float(confidence) < 0.5
            or not isinstance(evidence, list)
            or not any(isinstance(item, str) and item.strip() for item in evidence)
        ):
            continue
        label = str(observation.get("label") or feature_type.replace("_", " ")).strip()
        location = observation.get("location_description")
        evidence_text = "; ".join(item.strip() for item in evidence if isinstance(item, str) and item.strip())
        if location and isinstance(location, str):
            evidence_text = f"{evidence_text} · Relative location described by Vision: {location.strip()}".strip(" ·")
        warning = "Vision identified this feature, but did not provide a trustworthy image-space location. Review before placing it in the redraw."
        feature = SurveyFeature(
            id=str(uuid.uuid4()),
            analysis_id=analysis_id,
            feature_type=feature_type,
            label=label,
            geometry_json=None,
            coordinate_space=None,
            confidence=float(confidence),
            source="vision",
            evidence_text=evidence_text,
            original_type=feature_type,
            possible_types_json=None,
            warning=warning,
            review_required=True,
            review_status="detected",
        )
        db.add(feature)
        features.append({
            "id": feature.id,
            "feature_type": feature_type,
            "label": label,
            "geometry": None,
            "confidence": float(confidence),
            "source": "vision",
            "evidence_text": evidence_text,
            "original_type": feature_type,
            "possible_types": [],
            "warning": warning,
            "review_required": True,
            "review_status": "detected",
        })
        observed_ocr_types.add(feature_type)

    await db.flush()
    return features
