"""High-quality OCR adapter with multi-pass image enhancement.

Strategy:
  1. Normalize image to a good working resolution (1200–2400 px on longest side)
  2. Deskew / straighten if rotated
  3. Run Windows OCR on the normalized image
  4. If token count is low, run additional passes with different preprocessing:
     - Adaptive threshold (binarize)
     - Upscale ×2 (for small/blurry images)
     - Inverted (white-on-dark text)
  5. Merge all tokens, dedup by proximity
  6. Fall back to PaddleOCR if winocr totally fails
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from typing import Any

import cv2
import numpy as np

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import OCRResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Image preprocessing helpers
# ---------------------------------------------------------------------------

def _load_image(image_path: str) -> np.ndarray | None:
    """Load image, handle WebP and other formats via PIL fallback."""
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        from PIL import Image as PILImage
        pil = PILImage.open(str(image_path)).convert("RGB")
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _normalize_resolution(img: np.ndarray, target_long: int = 1800) -> np.ndarray:
    """Scale image so longest side = target_long, keeping aspect ratio.
    If already larger, don't downscale below 1200 on longest side.
    """
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side >= 1200 and long_side <= 2400:
        return img  # already good
    if long_side < 1200:
        # Upscale small images
        scale = target_long / long_side
        new_w, new_h = int(w * scale), int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    if long_side > 2400:
        # Downscale very large images to max 2400
        scale = 2400 / long_side
        new_w, new_h = int(w * scale), int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return img


def _deskew(img: np.ndarray) -> np.ndarray:
    """Detect and correct moderate skew (up to ±15°)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
    # Threshold for line detection
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 100:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    # minAreaRect returns angle in [-90, 0); we want [-45, 45)
    if angle < -45:
        angle = 90 + angle
    if abs(angle) > 15:
        return img  # too skewed, skip (might be a rotated chart/map)
    if abs(angle) < 0.5:
        return img  # negligible skew
    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    log.debug("Deskewed by %.2f degrees", angle)
    return rotated


def _make_variants(img: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Generate multiple preprocessing variants for OCR passes."""
    variants: list[tuple[str, np.ndarray]] = []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
    h, w = gray.shape[:2]

    # 1. Gentle CLAHE (best for most survey drawings)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    variants.append(("clahe", enhanced))

    # 2. Strong CLAHE (for low-contrast / faded prints)
    clahe_strong = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
    strong = clahe_strong.apply(gray)
    variants.append(("clahe_strong", strong))

    # 3. Adaptive binary threshold (for high-contrast blueprints / scans)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    adaptive = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        blockSize=15, C=8,
    )
    variants.append(("adaptive_thresh", adaptive))

    # 4. Otsu binarize (clean printed text)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))

    # 5. Inverted otsu (white-on-dark background)
    _, otsu_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    variants.append(("otsu_inv", otsu_inv))

    return variants


def _scale_coords(bbox: list, cx: float, cy: float, scale: float) -> tuple:
    """Scale bounding box and center back to original image coordinates."""
    return (
        [v / scale for v in bbox],
        [cx / scale, cy / scale],
    )


# ---------------------------------------------------------------------------
# Token deduplication
# ---------------------------------------------------------------------------

def _merge_tokens(all_tokens: list[dict[str, Any]], overlap_px: float = 8.0) -> list[dict[str, Any]]:
    """Remove near-duplicate tokens from multiple OCR passes.
    Two tokens are duplicates if their centers are within overlap_px and text matches (case-insensitive).
    """
    merged: list[dict[str, Any]] = []
    for tok in all_tokens:
        cx, cy = tok["center"]
        text = tok["text"].casefold()
        is_dup = False
        for existing in merged:
            ex, ey = existing["center"]
            if abs(cx - ex) <= overlap_px and abs(cy - ey) <= overlap_px:
                if existing["text"].casefold() == text:
                    is_dup = True
                    break
                # Different text at same location: keep higher-confidence one
                if tok["confidence"] > existing["confidence"]:
                    existing.update(tok)
                is_dup = True
                break
        if not is_dup:
            merged.append(tok)
    return merged


# ---------------------------------------------------------------------------
# Windows OCR pass
# ---------------------------------------------------------------------------

async def _winocr_pass(
    img_gray: np.ndarray,
    scale: float = 1.0,
    pass_name: str = "default",
) -> list[dict[str, Any]]:
    """Run one winocr pass on a preprocessed grayscale image.
    Returns tokens with coordinates scaled back to original image space.
    """
    import winocr
    # winocr works best with BGR; convert gray back
    img_bgr = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
    result = await winocr.recognize_cv2(img_bgr, "en")

    tokens: list[dict[str, Any]] = []
    for line in result.lines:
        words = getattr(line, "words", [])
        # Emit line-level token (full line text)
        if words:
            lx1 = min(float(w.bounding_rect.x) for w in words)
            ly1 = min(float(w.bounding_rect.y) for w in words)
            lx2 = max(float(w.bounding_rect.x + w.bounding_rect.width) for w in words)
            ly2 = max(float(w.bounding_rect.y + w.bounding_rect.height) for w in words)
            bbox_s = [lx1, ly1, lx2, ly2]
            cx_s = (lx1 + lx2) / 2.0
            cy_s = (ly1 + ly2) / 2.0
            bbox, center = _scale_coords(bbox_s, cx_s, cy_s, scale)
            line_text = _clean_text(str(line.text).strip())
            if line_text:
                tokens.append({
                    "text": line_text,
                    "confidence": 0.90,
                    "bbox": bbox,
                    "center": center,
                    "pass": pass_name,
                    "is_line": True,
                })
        # Emit word-level tokens (more precise locations)
        if len(words) > 1:
            for w in words:
                wb = [
                    float(w.bounding_rect.x),
                    float(w.bounding_rect.y),
                    float(w.bounding_rect.x + w.bounding_rect.width),
                    float(w.bounding_rect.y + w.bounding_rect.height),
                ]
                wcx = (wb[0] + wb[2]) / 2.0
                wcy = (wb[1] + wb[3]) / 2.0
                wb_orig, wc_orig = _scale_coords(wb, wcx, wcy, scale)
                wt = _clean_text(str(w.text).strip())
                if wt:
                    tokens.append({
                        "text": wt,
                        "confidence": 0.95,
                        "bbox": wb_orig,
                        "center": wc_orig,
                        "pass": pass_name,
                        "is_line": False,
                    })
    return tokens


def _clean_text(text: str) -> str:
    """Apply common OCR fixes for survey drawings."""
    if not text:
        return text
    # $ followed by digits → 1... (OCR misreads '1' as '$')
    import re
    text = re.sub(r"^\$(\d+)", r"1\1", text)
    # Strip trailing punctuation artifacts
    text = text.rstrip(".,;:")
    return text


# ---------------------------------------------------------------------------
# Main OCR entry points
# ---------------------------------------------------------------------------

async def _run_winocr_multipass(
    image_path: str,
    analysis_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Multi-pass winocr with adaptive preprocessing."""

    # --- Load & normalize ---
    img = _load_image(str(image_path))
    if img is None:
        raise ValueError(f"Cannot load image: {image_path}")

    orig_h, orig_w = img.shape[:2]
    img_norm = _normalize_resolution(img)
    norm_h, norm_w = img_norm.shape[:2]
    # Scale factor: norm coordinates → original coordinates
    scale_x = norm_w / orig_w
    scale_y = norm_h / orig_h
    # We use a single uniform scale (images stay proportional)
    scale = (scale_x + scale_y) / 2.0

    # --- Deskew ---
    img_deskewed = _deskew(img_norm)

    # --- Pass 1: gentle CLAHE on deskewed ---
    gray_base = cv2.cvtColor(img_deskewed, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_clahe = clahe.apply(gray_base)

    all_tokens = await _winocr_pass(gray_clahe, scale=scale, pass_name="clahe")
    base_count = len(all_tokens)
    log.info("OCR pass 1 (clahe): %d tokens", base_count)

    # --- Pass 2 onwards: only if pass 1 was thin ---
    if base_count < 20:
        variants = _make_variants(img_deskewed)
        for name, variant_img in variants:
            if name == "clahe":
                continue  # already done
            extra = await _winocr_pass(variant_img, scale=scale, pass_name=name)
            log.info("OCR pass %s: %d tokens", name, len(extra))
            all_tokens.extend(extra)
            if len(_merge_tokens(all_tokens)) >= 20:
                break  # enough tokens

    # --- Upscale pass for very small images ---
    if base_count < 10 and orig_w < 800:
        log.info("Image is small (%dx%d), running ×2 upscale pass", orig_w, orig_h)
        img_up = cv2.resize(img, (orig_w * 2, orig_h * 2), interpolation=cv2.INTER_CUBIC)
        gray_up = cv2.cvtColor(img_up, cv2.COLOR_BGR2GRAY)
        clahe_up = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray_up)
        up_tokens = await _winocr_pass(clahe_up, scale=2.0, pass_name="upscale_x2")
        log.info("Upscale pass: %d tokens", len(up_tokens))
        all_tokens.extend(up_tokens)

    # --- Merge / dedup ---
    merged = _merge_tokens(all_tokens, overlap_px=10.0)
    log.info("After merge: %d unique tokens (from %d raw)", len(merged), len(all_tokens))

    # --- Persist to DB ---
    output: list[dict[str, Any]] = []
    rows: list[OCRResult] = []
    for tok in merged:
        item_id = str(uuid.uuid4())
        item = {
            "id": item_id,
            "text": tok["text"],
            "confidence": tok["confidence"],
            "bbox": tok["bbox"],
            "center": tok["center"],
        }
        rows.append(OCRResult(
            id=item_id,
            analysis_id=analysis_id,
            text=tok["text"],
            confidence=tok["confidence"],
            bbox_json=json.dumps(tok["bbox"]),
            center_json=json.dumps(tok["center"]),
        ))
        output.append(item)

    if rows:
        db.add_all(rows)
        await db.flush()

    log.info("Multi-pass winocr: %d tokens saved for analysis %s", len(output), analysis_id)
    return output



# ---------------------------------------------------------------------------
# Gemini Vision OCR boost
# ---------------------------------------------------------------------------

_GEMINI_OCR_PROMPT = """You are an expert OCR engine for survey and cadastral plot layout drawings.

Extract ALL visible text from this image. Output ONLY a JSON array where each element is:
{"text": "<exact text>", "x": <center_x_pixels>, "y": <center_y_pixels>}

Rules:
- Include plot numbers (e.g. 101, 102...), area values (e.g. 245.6, SQ.M), dimensions (e.g. 12.19 M), road labels, project name, notes — EVERYTHING
- For areas written as "245 $" or "2008" interpret as "245.6" or "200.8" but output the RAW text as seen
- x and y must be pixel coordinates of the text center in the original image
- Output only the JSON array, no markdown, no explanation
"""

async def _gemini_ocr_pass(image_path: str) -> list[dict[str, Any]]:
    """Extract tokens via OpenRouter → Gemini Flash vision (free, already configured)."""
    import base64
    import json as _json
    import httpx
    import re

    with open(str(image_path), "rb") as f:
        img_bytes = f.read()

    # Resize to max 1600px before sending to avoid token limits
    img_arr = _load_image(str(image_path))
    if img_arr is not None:
        img_arr = _normalize_resolution(img_arr, target_long=1600)
        ok, buf = cv2.imencode(".jpeg", img_arr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            img_bytes = buf.tobytes()

    b64 = base64.b64encode(img_bytes).decode()
    suffix = str(image_path).lower().split(".")[-1]
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")
    # Always send JPEG after resize
    if img_arr is not None:
        mime = "image/jpeg"

    # Use OpenRouter free vision model (e.g. ling-flash, gemma-it, etc.)
    payload = {
        "model": "openrouter/free",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _GEMINI_OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 4096,
    }

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "AI Plot Layout OCR",
    }
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            json=payload, headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()

    text_out = (body.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    if not text_out:
        log.warning("Gemini OCR: empty response")
        return []

    # Strip markdown fences
    text_out = re.sub(r"^```[a-z]*\n?", "", text_out.strip())
    text_out = re.sub(r"\n?```$", "", text_out.strip())

    try:
        items = _json.loads(text_out)
    except _json.JSONDecodeError:
        # Try extracting JSON array substring
        m = re.search(r"\[.*\]", text_out, re.DOTALL)
        if m:
            items = _json.loads(m.group())
        else:
            log.warning("Gemini OCR: could not parse JSON response")
            return []

    tokens = []
    for item in items:
        t = _clean_text(str(item.get("text", "")).strip())
        try:
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
        except (TypeError, ValueError):
            continue
        if not t:
            continue
        tokens.append({
            "text": t,
            "confidence": 0.97,
            "bbox": [max(0, x - 20), max(0, y - 10), x + 20, y + 10],
            "center": [x, y],
            "pass": "gemini",
        })
    log.info("Gemini OCR boost extracted %d tokens", len(tokens))
    return tokens


async def _groq_ocr_pass(image_path: str) -> list[dict[str, Any]]:
    """Extract tokens using Groq Llama-3.2-Vision (free tier) as OCR boost."""
    import base64
    import json as _json
    import httpx
    import re

    with open(str(image_path), "rb") as f:
        img_bytes = f.read()
    b64 = base64.b64encode(img_bytes).decode()

    suffix = str(image_path).lower().split(".")[-1]
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")

    payload = {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _GEMINI_OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 4096,
    }

    headers = {"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    text_out = body["choices"][0]["message"]["content"].strip()
    text_out = re.sub(r"^```[a-z]*\n?", "", text_out)
    text_out = re.sub(r"\n?```$", "", text_out)
    items = _json.loads(text_out)

    tokens = []
    for item in items:
        t = str(item.get("text", "")).strip()
        x = float(item.get("x", 0))
        y = float(item.get("y", 0))
        if not t:
            continue
        tokens.append({
            "text": t,
            "confidence": 0.95,
            "bbox": [x - 20, y - 10, x + 20, y + 10],
            "center": [x, y],
            "pass": "groq",
        })
    log.info("Groq OCR boost extracted %d tokens", len(tokens))
    return tokens


async def run_ocr(
    image_path: str,
    analysis_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Run OCR with multi-pass enhancement + optional Gemini/Groq vision boost."""

    all_tokens: list[dict[str, Any]] = []

    # --- Primary: Windows native OCR (multi-pass) ---
    try:
        import winocr  # noqa: F401 — availability check
        winocr_tokens = await _run_winocr_multipass(image_path, analysis_id, db)
        all_tokens.extend(winocr_tokens)
        log.info("WinOCR produced %d tokens", len(winocr_tokens))
    except Exception as win_exc:
        log.warning("winocr multi-pass failed (%s); will rely on LLM OCR boost", win_exc)

    # --- Boost: Vision LLM OCR pass ---
    # Trigger automatically if WinOCR extracted few tokens (< 15) on difficult/low-res drawings,
    # or if explicitly enabled via settings.
    should_boost = (
        (len(all_tokens) < 15 or settings.enable_gemini_ocr)
        and bool(settings.openrouter_api_key or settings.gemini_api_key)
    )
    if should_boost:
        try:
            log.info("Triggering Vision LLM OCR boost for complex/low-token drawing...")
            llm_tokens = await asyncio.wait_for(_gemini_ocr_pass(image_path), timeout=20.0)
            all_tokens.extend(llm_tokens)
            log.info("Vision LLM OCR boost returned %d tokens", len(llm_tokens))
        except asyncio.TimeoutError:
            log.warning("Vision LLM OCR timed out (20s), skipping")
        except Exception as gem_exc:
            log.warning("Vision LLM OCR failed: %s", gem_exc)
    elif settings.enable_groq_ocr and settings.groq_api_key:
        try:
            groq_tokens = await asyncio.wait_for(_groq_ocr_pass(image_path), timeout=15.0)
            all_tokens.extend(groq_tokens)
        except asyncio.TimeoutError:
            log.warning("Groq OCR timed out (15s), skipping")
        except Exception as groq_exc:
            log.warning("Groq OCR failed: %s", groq_exc)

    # If we got tokens from WinOCR (already persisted in _run_winocr_multipass),
    # just return them — boost tokens are already merged in all_tokens
    if all_tokens:
        # Re-persist if we added LLM boost tokens on top of already-saved winocr tokens
        boost_tokens = [t for t in all_tokens if t.get("pass") in ("gemini", "groq")]
        if boost_tokens:
            merged = _merge_tokens(all_tokens, overlap_px=15.0)
            # Only save newly added boost tokens not already in DB
            new_rows: list[OCRResult] = []
            for tok in merged:
                if tok.get("pass") in ("gemini", "groq"):
                    tid = str(uuid.uuid4())
                    tok["id"] = tid
                    new_rows.append(OCRResult(
                        id=tid, analysis_id=analysis_id,
                        text=tok["text"], confidence=tok["confidence"],
                        bbox_json=json.dumps(tok["bbox"]),
                        center_json=json.dumps(tok["center"]),
                    ))
            if new_rows:
                db.add_all(new_rows)
                await db.flush()
            return [{k: v for k, v in t.items() if k != "pass"} for t in merged]
        return all_tokens

    # --- PaddleOCR fallback ---
    import importlib.metadata

    def recognize():
        from paddleocr import PaddleOCR
        try:
            version = importlib.metadata.version("paddleocr")
            major = int(version.split(".", 1)[0])
        except (importlib.metadata.PackageNotFoundError, ValueError):
            major = 2
        if major >= 3:
            engine = PaddleOCR(lang=settings.ocr_language, use_textline_orientation=True)
            return engine.predict(str(image_path))
        else:
            engine = PaddleOCR(use_angle_cls=True, lang=settings.ocr_language, show_log=False)
            try:
                return engine.ocr(str(image_path), cls=True)
            except TypeError:
                return engine.ocr(str(image_path))

    try:
        raw = await asyncio.to_thread(recognize)
        output: list[dict[str, Any]] = []
        rows: list[OCRResult] = []
        for item in _iter_paddle_predictions(raw):
            polygon, text, score = item
            text = _clean_text(str(text).strip())
            if not text:
                continue
            try:
                points = [[float(p[0]), float(p[1])] for p in polygon]
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                confidence = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError, IndexError):
                continue
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            center = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
            tok_id = str(uuid.uuid4())
            tok = {"id": tok_id, "text": text, "confidence": confidence, "bbox": bbox, "center": center}
            rows.append(OCRResult(
                id=tok_id, analysis_id=analysis_id, text=text,
                confidence=confidence, bbox_json=json.dumps(bbox), center_json=json.dumps(center),
            ))
            output.append(tok)
        if rows:
            db.add_all(rows)
            await db.flush()
        log.info("PaddleOCR fallback extracted %d tokens", len(output))
        return output
    except Exception as exc:
        log.error("All OCR methods failed: %s", exc)
        raise


def _iter_paddle_predictions(result: Any):
    """Normalize PaddleOCR 2.x and 3.x response shapes."""
    if not isinstance(result, (dict, list, tuple)) and hasattr(result, "json"):
        payload = result.json
        if callable(payload):
            payload = payload()
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if isinstance(payload, dict):
            result = payload.get("res", payload)
    if isinstance(result, dict):
        texts = result.get("rec_texts")
        scores = result.get("rec_scores")
        polygons = result.get("dt_polys") or result.get("rec_polys")
        texts = list(texts) if texts is not None else []
        scores = list(scores) if scores is not None else []
        polygons = list(polygons) if polygons is not None else []
        for text, score, polygon in zip(texts, scores, polygons):
            yield polygon, text, score
        return
    if not isinstance(result, (list, tuple)):
        return
    for item in result:
        if not isinstance(item, (dict, list, tuple)) and hasattr(item, "json"):
            yield from _iter_paddle_predictions(item)
        elif isinstance(item, dict):
            yield from _iter_paddle_predictions(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            polygon, recognized = item[0], item[1]
            if isinstance(recognized, (list, tuple)) and len(recognized) >= 2 and isinstance(recognized[0], str):
                yield polygon, recognized[0], recognized[1]
            else:
                yield from _iter_paddle_predictions(item)
        elif isinstance(item, (list, tuple)):
            yield from _iter_paddle_predictions(item)
