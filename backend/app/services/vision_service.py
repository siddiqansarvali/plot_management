"""OpenRouter vision adapter for evidence-backed semantic observations."""

from __future__ import annotations

import base64
import ast
import io
import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx
from PIL import Image

from app.config import settings

# Uvicorn configures this logger at INFO in the app server, so the required
# image/model/request lifecycle messages appear in normal backend logs.
log = logging.getLogger("uvicorn.error")

FEATURE_TYPES = [
    "road", "canal", "river_stream", "railway", "forest",
    "agricultural_land", "open_land", "park_green_area", "building",
    "boundary_wall", "drainage", "water_body", "utility_corridor",
    "pathway", "layout_boundary", "north_arrow", "dimension_line",
    "survey_reference", "unknown_feature",
]
_FORBIDDEN_GEOMETRY_KEYS = {"geometry", "coordinates", "polygon", "polygons", "bbox", "bounding_box", "vertices"}

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_CONFIDENCE = {
    "anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]
}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# Keep provider constraints small. Vision describes semantic observations only;
# OCR/OpenCV and the geometry pipeline own dimensions and all coordinates.
VISION_RESPONSE_SCHEMA: dict[str, Any] = _object({
    "plots": {"type": "array", "items": _object({
        "plot_number": _NULLABLE_STRING,
        "confidence": _NULLABLE_CONFIDENCE,
    })},
    "features": {"type": "array", "items": _object({
        "type": {"type": "string", "enum": FEATURE_TYPES},
        "label": _NULLABLE_STRING,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    })},
    "relationships": {"type": "array", "items": _object({
        "subject": {"type": "string"},
        "relation": {"type": "string"},
        "object": {"type": "string"},
        "confidence": _NULLABLE_CONFIDENCE,
    })},
    "uncertain_items": {"type": "array", "items": {"type": "string"}},
})

SURVEY_ANALYSIS_PROMPT = """You are analyzing a scanned land survey / plot layout image.
Identify semantic evidence visible in this image only. Do not invent information, estimate missing dimensions, create geometry, or assume standard layouts.
Return only a compact JSON object. Unknown information must be null or listed in uncertain_items.
Focus on legible plot labels; roads and road labels; canals, rivers, railways; forest and agricultural land; buildings, water bodies, pathways; north arrows; layout boundaries; and visible spatial relationships.
Preserve visible label text. Do not return coordinates, polygons, measurements, areas, or inferred geometry; OCR and computer vision handle those.
Use this shape: {"plots":[{"plot_number":null,"confidence":null}],"features":[{"type":"road","label":null,"confidence":0.5}],"relationships":[{"subject":"plot label","relation":"adjacent_to","object":"visible feature","confidence":0.5}],"uncertain_items":[]}
Include only supported observations; empty arrays are valid."""

_JSON_MODE_RETRY_HINT = "Return one compact JSON object with plots, features, relationships, and uncertain_items arrays. Use only visible evidence; unknown values are null or empty arrays. Do not return geometry or coordinates."""


def _image_data_url(path: str) -> tuple[str, str, int, tuple[int, int], int]:
    """Encode the current uploaded image as a bounded JPEG with fast bilinear scaling."""
    source_path = Path(path)
    source_bytes = source_path.stat().st_size
    with Image.open(source_path) as source:
        source_type = Image.MIME.get(source.format or "", "application/octet-stream")
        source_size = source.size
        image = source.convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
    encoded_bytes = buffer.getvalue()
    encoded = base64.b64encode(encoded_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", source_type, source_bytes, source_size, len(encoded_bytes)


def _json_candidates(text: str) -> list[str]:
    """Extract balanced top-level JSON objects from raw, fenced, or narrated text."""
    found: list[str] = []
    depth = 0
    start = None
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                found.append(text[start:index + 1])
                start = None
    return found


def _remove_trailing_commas(text: str) -> str:
    output: list[str] = []
    quoted = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            output.append(char)
        elif char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead >= len(text) or text[lookahead] not in "]}":
                output.append(char)
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _quote_unquoted_keys(text: str) -> str:
    """Quote simple object keys outside strings without changing string values."""
    output: list[str] = []
    quoted = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            output.append(char)
            index += 1
            continue
        output.append(char)
        index += 1
        if char not in "{,":
            continue
        whitespace_start = index
        while index < len(text) and text[index].isspace():
            index += 1
        match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", text[index:])
        if match:
            key = match.group(0)
            end = index + len(key)
            colon = end
            while colon < len(text) and text[colon].isspace():
                colon += 1
            if colon < len(text) and text[colon] == ":":
                output.append(text[whitespace_start:index])
                output.append(json.dumps(key))
                output.append(text[index + len(key):colon + 1])
                index = colon + 1
    return "".join(output)


def _python_literals(text: str) -> str:
    """Translate JSON literals to Python literals for a safe ast fallback."""
    output: list[str] = []
    quoted: str | None = None
    escaped = False
    index = 0
    replacements = {"true": "True", "false": "False", "null": "None"}
    while index < len(text):
        char = text[index]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quoted:
                quoted = None
            index += 1
            continue
        if char in "\"'":
            quoted = char
            output.append(char)
            index += 1
            continue
        token = next((token for token in replacements if text.startswith(token, index)), None)
        if token:
            before = text[index - 1] if index else " "
            end = index + len(token)
            after = text[end] if end < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                output.append(replacements[token])
                index = end
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _decode_json(content: Any) -> dict[str, Any]:
    """Parse common model JSON variations; never infer omitted survey values."""
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Vision model returned an empty response.")
    text = content.strip().lstrip("\ufeff")
    candidates = [text, *_json_candidates(text)]
    errors: list[Exception] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        variants = [candidate]
        cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", candidate, flags=re.IGNORECASE)
        if cleaned != candidate:
            variants.append(cleaned)
        for variant in variants:
            try:
                parsed = json.loads(variant)
                if isinstance(parsed, dict):
                    return parsed
                errors.append(ValueError("Vision JSON root must be an object."))
                continue
            except json.JSONDecodeError as exc:
                errors.append(exc)
            repaired = _remove_trailing_commas(_quote_unquoted_keys(variant))
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    return parsed
                errors.append(ValueError("Vision JSON root must be an object."))
                continue
            except json.JSONDecodeError as exc:
                errors.append(exc)
            try:
                parsed = ast.literal_eval(_python_literals(repaired))
                if isinstance(parsed, dict):
                    return parsed
                errors.append(ValueError("Vision response root must be an object."))
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
                errors.append(exc)
    if not text:
        raise ValueError("Vision model returned an empty response.")
    if not _json_candidates(text):
        raise ValueError("Vision response contained no JSON object.")
    cause = errors[-1] if errors else None
    raise ValueError(f"Vision response contained malformed JSON ({type(cause).__name__ if cause else 'parse error'}).")


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Vision field '{field_name}' must be a string array.")
    return [item.strip()[:240] for item in value if item.strip()][:100]


def _confidence(value: Any, field_name: str, *, required: bool = False) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"Vision field '{field_name}' must be a confidence from 0 to 1.")
    return float(value)


def _validate_observations(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize the compact semantic schema for the existing fusion API."""
    def reject_geometry(node: Any) -> None:
        if isinstance(node, dict):
            forbidden = _FORBIDDEN_GEOMETRY_KEYS.intersection(str(key).casefold() for key in node)
            if forbidden:
                raise ValueError("Vision response included coordinates or geometry; only semantic observations are accepted.")
            for child in node.values():
                reject_geometry(child)
        elif isinstance(node, list):
            for child in node:
                reject_geometry(child)

    reject_geometry(value)
    for key in ("plots", "features", "relationships", "uncertain_items"):
        value.setdefault(key, [])
        if not isinstance(value[key], list):
            raise ValueError(f"Vision response field '{key}' must be a JSON array.")
    if len(value["plots"]) > 150 or len(value["features"]) > 150 or len(value["relationships"]) > 300:
        raise ValueError("Vision response contained too many observations.")

    uncertainties = _string_list(value["uncertain_items"], "uncertain_items")
    plots: list[dict[str, Any]] = []
    for item in value["plots"]:
        if isinstance(item, (str, int, float)):
            item = {"plot_number": str(item).strip(), "confidence": 0.8}
        elif not isinstance(item, dict):
            raise ValueError("Vision response contained an invalid plot observation.")
        number = item.get("plot_number")
        if number is not None and not isinstance(number, str):
            number = str(number)
        confidence = _confidence(item.get("confidence"), "plot confidence")
        plots.append({
            "plot_number": number.strip()[:80] if number else None,
            "description": None,
            "confidence": confidence,
            "label_confidence": confidence,
            "evidence": [],
            "boundary_evidence": [],
            "dimensions": [],
            "stated_area": None,
            "neighbors": [],
        })

    features: list[dict[str, Any]] = []
    for item in value["features"]:
        if isinstance(item, str):
            item = {"type": item, "confidence": 0.7}
        elif not isinstance(item, dict):
            raise ValueError("Vision response contained an invalid feature observation.")
        raw_type = item.get("type") or item.get("feature_type")
        if not isinstance(raw_type, str):
            raise ValueError("Vision feature type must be a string.")
        feature_type = re.sub(r"[^a-z0-9]+", "_", raw_type.casefold()).strip("_")
        if feature_type not in FEATURE_TYPES:
            raise ValueError("Vision response contained an unsupported feature type.")
        confidence = _confidence(item.get("confidence"), "feature confidence", required=False)
        if confidence is None:
            confidence = 0.7
        label = item.get("label")
        if label is not None and not isinstance(label, str):
            label = str(label)
        features.append({
            "type": feature_type,
            "label": label.strip()[:240] if label else None,
            "location_description": None,
            "confidence": confidence,
            "evidence": [],
        })

    relationships: list[dict[str, Any]] = []
    for item in value["relationships"]:
        if not isinstance(item, dict):
            raise ValueError("Vision response contained an invalid relationship.")
        subject, relation, obj = (item.get(key) for key in ("subject", "relation", "object"))
        if not all(isinstance(part, str) and part.strip() for part in (subject, relation, obj)):
            raise ValueError("Vision relationships need a subject, relation, and object.")
        relationships.append({
            "subject": subject.strip()[:120],
            "relation": relation.strip()[:80],
            "object": obj.strip()[:120],
            "confidence": _confidence(item.get("confidence"), "relationship confidence"),
            "evidence": [],
        })

    adjacent_relations = {"adjacent_to", "next_to", "beside", "neighbors", "neighbor_of"}
    for plot in plots:
        plot_number = plot.get("plot_number")
        if not plot_number:
            continue
        plot["neighbors"] = [
            relationship["object"]
            for relationship in relationships
            if relationship["subject"].casefold() == plot_number.casefold()
            and relationship["relation"].casefold() in adjacent_relations
        ]

    observed_types = {feature["type"] for feature in features if feature["confidence"] >= 0.5}
    feature_flags = {
        "road_detected": True if "road" in observed_types else None,
        "forest_detected": True if "forest" in observed_types else None,
        "water_body_detected": True if "water_body" in observed_types else None,
        "north_arrow_detected": True if "north_arrow" in observed_types else None,
        "buildings_detected": True if "building" in observed_types else None,
    }
    north_feature = next((feature for feature in features if feature["type"] == "north_arrow"), None)
    boundary_feature = next((feature for feature in features if feature["type"] == "layout_boundary"), None)
    return {
        "plots": plots,
        "features": features,
        "relationships": relationships,
        "uncertain_items": uncertainties,
        "target_plot": {"plot_number": None, "survey_number": None},
        "dimensions": {},
        "area": {},
        "boundaries": {},
        "feature_flags": feature_flags,
        "north_arrow": ({"detected": True, "angle_from_page_up_deg": None,
                         "confidence": north_feature["confidence"], "evidence": north_feature["evidence"]}
                        if north_feature else None),
        "layout_boundary": ({"detected": True, "confidence": boundary_feature["confidence"],
                             "evidence": boundary_feature["evidence"]}
                            if boundary_feature else None),
        "neighboring_plots": [],
        "notes": None,
    }


def _safe_response_excerpt(content: Any, limit: int = 240) -> str:
    """Bounded backend-only diagnostic; never log credentials or image payloads."""
    try:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(content)
    if settings.openrouter_api_key:
        text = text.replace(settings.openrouter_api_key, "[redacted]")
    text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[image omitted]", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _image_modalities(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        architecture = value.get("architecture")
        if isinstance(architecture, dict):
            modalities = architecture.get("input_modalities")
            if isinstance(modalities, list):
                found.update(str(item).casefold() for item in modalities)
        modalities = value.get("input_modalities")
        if isinstance(modalities, list):
            found.update(str(item).casefold() for item in modalities)
        for child in value.values():
            found.update(_image_modalities(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_image_modalities(child))
    return found


async def _validate_model_image_input(client: httpx.AsyncClient, model: str, headers: dict[str, str]) -> None:
    """Fail closed unless OpenRouter advertises image support for the model."""
    if model.casefold() == "openrouter/free":
        # This router's documented contract accepts images and chooses a free
        # provider matching request features (including image understanding).
        log.info("Vision model capability check passed: %s supports image input", model)
        return
    if model.count("/") != 1:
        raise ValueError("VISION_MODEL must be 'openrouter/free' or an OpenRouter model slug in provider/model form.")
    author, slug = model.split("/", 1)
    endpoint = f"{settings.openrouter_base_url.rstrip('/')}/models/{quote(author, safe='')}/{quote(slug, safe=':-')}/endpoints"
    response = await client.get(endpoint, headers=headers)
    if response.status_code == 404:
        raise ValueError(f"OpenRouter vision model '{model}' is unavailable; check VISION_MODEL.")
    if response.is_error:
        raise RuntimeError(f"OpenRouter model capability check failed with HTTP {response.status_code}.")
    modalities = _image_modalities(response.json())
    if "image" not in modalities:
        raise ValueError(f"OpenRouter model '{model}' does not advertise image input; Vision AI was not sent the survey.")
    log.info("Vision model capability check passed: %s accepts image input", model)


async def _discover_free_json_vision_model(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    exclude_model: str | None = None,
    exclude_models: set[str] | None = None,
) -> str:
    """Choose a current free image+JSON model from OpenRouter's live catalog."""
    response = await client.get(
        f"{settings.openrouter_base_url.rstrip('/')}/models",
        headers=headers,
        params={"input_modalities": "image"},
    )
    if response.is_error:
        raise RuntimeError(f"OpenRouter image-model discovery failed with HTTP {response.status_code}.")
    try:
        models = response.json().get("data", [])
    except (ValueError, AttributeError) as exc:
        raise ValueError("OpenRouter returned an invalid image-model catalog response.") from exc
    if not isinstance(models, list):
        raise ValueError("OpenRouter image-model catalog did not contain a model list.")

    candidates: list[tuple[int, str]] = []
    excluded = {model.casefold() for model in (exclude_models or set())}
    if exclude_model:
        excluded.add(exclude_model.casefold())
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        if not model_id or model_id.casefold() in excluded:
            continue
        # Skip router aliases: the fallback must pin a provider/model so it
        # cannot randomly return to the same moderation-only route.
        if model_id.casefold().startswith("openrouter/"):
            continue
        if "image" not in _image_modalities(item):
            continue
        pricing = item.get("pricing") or {}
        is_free = model_id.casefold().endswith(":free") or (
            isinstance(pricing, dict)
            and str(pricing.get("prompt")) in {"0", "0.0"}
            and str(pricing.get("completion")) in {"0", "0.0"}
        )
        if not is_free:
            continue
        parameters = item.get("supported_parameters") or []
        if isinstance(parameters, dict):
            parameters = list(parameters)
        if not isinstance(parameters, list):
            continue
        supported = {str(parameter).casefold() for parameter in parameters}
        if not supported.intersection({"response_format", "structured_outputs", "json_schema"}):
            continue
        description = f"{item.get('name', '')} {item.get('description', '')} {model_id}".casefold()
        description = re.sub(r"[-_/]+", " ", description)
        if any(term in description for term in ("safety", "moderation", "guardrail", "guard model", "audio", "music", "lyria", "sound", "nemotron", "reasoning", "particle", "thinking", "dots")):
            continue
        candidates.append((len(supported), model_id))

    if not candidates:
        raise RuntimeError(
            "OpenRouter's current catalog has no free model advertising both image input and structured JSON support."
        )
    # Prefer models advertising the richest request support, preserving the
    # catalog's own ordering for ties (which reflects current availability).
    candidates.sort(key=lambda candidate: -candidate[0])
    selected = candidates[0][1]
    log.info("Selected live free image+JSON fallback model: %s", selected)
    return selected


def _openrouter_error(response: httpx.Response) -> str:
    detail = ""
    try:
        body = response.json()
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if isinstance(error, dict):
            detail = str(error.get("message") or "")
    except (ValueError, json.JSONDecodeError):
        pass
    if settings.openrouter_api_key:
        detail = detail.replace(settings.openrouter_api_key, "[redacted]")
    detail = re.sub(r"data:image/[^;]+;base64,[^\s\"']+", "[image omitted]", detail)
    if detail:
        return f"OpenRouter request failed with HTTP {response.status_code}: {detail[:400]}"
    return f"OpenRouter request failed with HTTP {response.status_code}."


async def run_vision_llm(
    image_path: str,
    target_plot_number: Optional[str] = None,
    document_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Send the current survey image to OpenRouter and return structured observations."""
    if not settings.enable_llm or not settings.has_openrouter_key:
        return None
    model = settings.openrouter_vision_model.strip()
    if not model:
        raise ValueError("VISION_MODEL must name a vision-capable OpenRouter model.")

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(3.0, connect=1.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await _validate_model_image_input(client, model, headers)
        image_url, source_type, source_bytes, dimensions, request_bytes = _image_data_url(image_path)
        log.info(
            "Vision image received: document_id=%s source_type=%s source_bytes=%d dimensions=%sx%s request_type=image/jpeg request_bytes=%d",
            document_id or "unknown", source_type, source_bytes, dimensions[0], dimensions[1], request_bytes,
        )
        prompt = SURVEY_ANALYSIS_PROMPT
        if target_plot_number:
            prompt += f"\nThe user requested plot {json.dumps(target_plot_number)}. Report it only if that exact label is visible."
        endpoint = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"

        def make_payload(
            request_model: str,
            request_prompt: str,
            *,
            use_json_format: bool = True,
        ) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "model": request_model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": request_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]}],
                "temperature": 0,
                # 700 tokens is sufficient for the compact semantic schema and
                # avoids mid-JSON truncation on free-tier models that cap output
                # around 750 tokens when response_format is set.
                "max_tokens": 1200,
            }
            if use_json_format:
                payload["response_format"] = {"type": "json_object"}
            return payload

        is_router_alias = model.casefold() == "openrouter/free"
        tried_models: set[str] = {model.casefold()}
        actual_model = model
        message: Any = None
        result: dict[str, Any] | None = None
        last_error: Exception = RuntimeError("Vision request did not return a result.")
        # Single fast attempt; do not hang or retry on slow free models
        max_requests = 1

        for attempt in range(max_requests):
            request_model = model
            if attempt:
                request_model = await _discover_free_json_vision_model(
                    client, headers, exclude_models=tried_models,
                )
            tried_models.add(request_model.casefold())
            log.info(
                "Vision request started: document_id=%s model=%s attempt=%d/%d",
                document_id or "unknown", request_model, attempt + 1, max_requests,
            )
            try:
                response = await client.post(
                    endpoint, headers=headers,
                    json=make_payload(request_model, prompt, use_json_format=True),
                )
            except httpx.TimeoutException as exc:
                last_error = RuntimeError(f"Vision provider timed out after 90 seconds ({type(exc).__name__}).")
                log.warning("Vision provider timed out: document_id=%s model=%s", document_id or "unknown", request_model)
                if is_router_alias and attempt + 1 < max_requests:
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = RuntimeError(f"Vision provider request failed ({type(exc).__name__}).")
                log.warning("Vision provider request failed: document_id=%s model=%s error=%s", document_id or "unknown", request_model, type(exc).__name__)
                if is_router_alias and attempt + 1 < max_requests:
                    continue
                raise last_error from exc

            if response.is_error:
                last_error = RuntimeError(_openrouter_error(response))
                log.warning(
                    "Vision provider returned HTTP error: document_id=%s model=%s http_status=%d",
                    document_id or "unknown", request_model, response.status_code,
                )
                if is_router_alias and response.status_code in {400, 408, 429, 500, 502, 503, 504} and attempt + 1 < max_requests:
                    continue
                raise last_error
            try:
                body = response.json()
                if not isinstance(body, dict):
                    raise TypeError("response root was not an object")
                choice = body["choices"][0]
                reply = choice["message"]
                message = reply.get("content")
                refusal = reply.get("refusal")
                finish_reason = choice.get("finish_reason")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                last_error = ValueError("OpenRouter returned an unexpected response shape.")
                log.warning("Vision response shape was invalid: document_id=%s model=%s", document_id or "unknown", request_model)
                if is_router_alias and attempt + 1 < max_requests:
                    continue
                raise last_error from exc

            actual_model = str(body.get("model") or request_model)
            tried_models.add(actual_model.casefold())
            log.info(
                "Vision response received: document_id=%s requested_model=%s actual_model=%s finish_reason=%s",
                document_id or "unknown", request_model, actual_model, finish_reason,
            )
            if actual_model.casefold() != request_model.casefold():
                try:
                    await _validate_model_image_input(client, actual_model, headers)
                except (ValueError, RuntimeError) as exc:
                    last_error = ValueError(f"OpenRouter selected a model without verified image input: {actual_model}. {exc}")
                    log.warning("Vision selected model failed image capability check: document_id=%s model=%s", document_id or "unknown", actual_model)
                    if is_router_alias and attempt + 1 < max_requests:
                        continue
                    raise last_error from exc

            try:
                result = _validate_observations(_decode_json(message))
                break
            except ValueError as exc:
                last_error = exc
                log.warning(
                    "Vision response was invalid: document_id=%s model=%s finish_reason=%s refusal=%s reason=%s response_chars=%d excerpt=%r",
                    document_id or "unknown", actual_model, finish_reason,
                    bool(refusal), type(exc).__name__,
                    len(message) if isinstance(message, str) else len(json.dumps(message, ensure_ascii=False)) if message is not None else 0,
                    _safe_response_excerpt(message if message is not None else refusal),
                )
                # If model truncated or returned invalid output, immediately return None so the pipeline continues
                log.info("Vision LLM output was incomplete; fast fallback to local OpenCV and OCR pipeline")
                break
                if is_router_alias and attempt + 1 < max_requests:
                    continue
                raise ValueError(f"OpenRouter returned an invalid semantic response ({type(exc).__name__}).") from exc

        if result is None:
            distinct = len(tried_models) - 1
            raise RuntimeError(
                f"Vision could not get valid semantic JSON after {distinct} distinct free vision model attempt(s)."
            ) from last_error

    raw_text = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
    result["raw_response"] = raw_text[:20000]
    result["model"] = actual_model
    log.info(
        "Vision parsing completed: document_id=%s plots=%d features=%d uncertainties=%d",
        document_id or "unknown", len(result["plots"]), len(result["features"]), len(result["uncertain_items"]),
    )
    return result
