"""Orchestrate one isolated analysis and preserve partial-stage results."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import AnalysisResult, Document

log = logging.getLogger(__name__)


async def _checkpoint(db: AsyncSession) -> None:
    await db.flush()
    await db.commit()


def _diagnostic(component: str, exc: Exception) -> str:
    """Return useful stage detail without ever returning a configured secret."""
    detail = str(exc).strip() or "No additional error detail was provided."
    if settings.openrouter_api_key:
        detail = detail.replace(settings.openrouter_api_key, "[redacted]")
    detail = detail[:900]

    if component == "ocr" and isinstance(exc, (ImportError, ModuleNotFoundError)):
        return (
            f"PaddleOCR could not be imported ({detail}). Install the pinned optional OCR "
            "dependencies from backend/requirements-ocr.txt in this backend environment."
        )
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return f"{component} dependency import failed ({detail})."
    return f"{component} failed ({type(exc).__name__}: {detail})."


async def run_full_pipeline(
    db: AsyncSession,
    document_id: str,
    analysis_id: str,
    target_plot_number: str | None = None,
) -> None:
    doc = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    analysis = (await db.execute(select(AnalysisResult).where(AnalysisResult.id == analysis_id))).scalar_one_or_none()
    if doc is None or analysis is None:
        raise ValueError("Analysis document or run was not found.")

    analysis.status = "running"
    analysis.started_at = datetime.now(timezone.utc)
    analysis.error_message = None
    analysis.component_diagnostics_json = "{}"
    doc.status = "processing"
    await _checkpoint(db)

    preprocessed_path = doc.file_path
    diagnostics: dict[str, str] = {}
    required_failures: set[str] = set()

    def add_diagnostic(component: str, message: str, *, required: bool = False) -> None:
        diagnostics[component] = message[:1200]
        analysis.component_diagnostics_json = json.dumps(diagnostics, ensure_ascii=False)
        if required:
            required_failures.add(component)

    ocr_results: list[dict] = []
    cv_candidates: list[dict] = []
    yolo_detections: list[dict] = []
    llm_result = None
    fusion_result = None
    geometry_result = None

    try:
        try:
            from app.services.preprocessing import preprocess_image
            preprocessed_path = await preprocess_image(doc.file_path, analysis_id)
            analysis.preprocessed_image_path = preprocessed_path
            preprocessing_status = "ok"
        except Exception as exc:
            log.warning("Preprocessing failed: %s", exc)
            preprocessing_status = "failed"
            add_diagnostic(
                "preprocessing",
                f"{_diagnostic('Preprocessing', exc)} The original image was used for later stages.",
                required=True,
            )
            preprocessed_path = doc.file_path

        if settings.enable_ocr:
            try:
                analysis.ocr_status = "running"
                await _checkpoint(db)
                from app.services.ocr_service import run_ocr
                # CRITICAL FIX: Run OCR on the high-fidelity original image doc.file_path
                # (CLAHE preprocessing washes out fine numbers like 106, 110 and distorts fonts)
                ocr_results = await run_ocr(doc.file_path, analysis_id, db)
                analysis.ocr_status = "ok"
            except Exception as exc:
                log.warning("OCR failed: %s", exc)
                analysis.ocr_status = "failed"
                add_diagnostic("ocr", _diagnostic("ocr", exc), required=True)
        else:
            analysis.ocr_status = "disabled"
            add_diagnostic("ocr", "OCR is disabled by backend configuration; plot labels and text will not be extracted.", required=True)
        await _checkpoint(db)

        # Fast local OpenCV geometry detection (runs on CPU in <1s, before external network calls)
        try:
            analysis.opencv_status = "running"
            await _checkpoint(db)
            from app.services.opencv_service import detect_geometry_candidates
            cv_candidates = await detect_geometry_candidates(preprocessed_path, analysis_id, db)
            analysis.opencv_status = "ok"
        except Exception as exc:
            log.warning("OpenCV failed: %s", exc)
            analysis.opencv_status = "failed"
            add_diagnostic("opencv", _diagnostic("OpenCV geometry detection", exc), required=True)
        await _checkpoint(db)

        if settings.enable_llm:
            try:
                if not settings.has_openrouter_key:
                    analysis.llm_status = "not_configured"
                    add_diagnostic("llm", "Vision AI was skipped because OPENROUTER_API_KEY is not configured. This is an optional component.")
                else:
                    analysis.llm_status = "running"
                    await _checkpoint(db)
                    from app.services.vision_service import run_vision_llm
                    import asyncio
                    try:
                        # Adaptive timeout: If local OCR got plenty of tokens (>= 15), keep fast 3.5s timeout.
                        # If OCR found few tokens (< 15, e.g. low-res thumbnail), allow up to 10.0s for Vision AI.
                        llm_timeout = 3.5 if len(ocr_results) >= 15 else 10.0
                        llm_result = await asyncio.wait_for(
                            run_vision_llm(doc.file_path, target_plot_number, document_id),
                            timeout=llm_timeout,
                        )
                        analysis.llm_status = "ok" if llm_result else "no_result"
                        if llm_result:
                            analysis.llm_raw_response = json.dumps(llm_result, ensure_ascii=False)[:30000]
                        else:
                            add_diagnostic("llm", "Vision AI returned no structured result. Fast local OpenCV & OCR pipeline used.")
                    except (asyncio.TimeoutError, Exception) as llm_exc:
                        log.info("Vision LLM bypassed after fast timeout/error (%s); proceeding with local CV+OCR", llm_exc)
                        analysis.llm_status = "no_result"
                        add_diagnostic("llm", "Vision AI timed out (fast bypass); local OpenCV and OCR completed directly.")
            except Exception as exc:
                log.warning("Vision analysis failed: %s", exc)
                analysis.llm_status = "failed"
                add_diagnostic("llm", f"{_diagnostic('Vision AI', exc)} OCR and computer vision continued; this is optional.")
        else:
            analysis.llm_status = "disabled"
            add_diagnostic("llm", "Vision AI is disabled by backend configuration. This is an optional component.")
        await _checkpoint(db)

        if settings.enable_yolo and settings.yolo_is_configured:
            try:
                from app.services.yolo_service import run_yolo_detection
                yolo_detections = await run_yolo_detection(preprocessed_path, analysis_id, db)
                analysis.yolo_status = "ok"
            except Exception as exc:
                log.warning("YOLO detection failed: %s", exc)
                analysis.yolo_status = "failed"
                add_diagnostic("yolo", f"{_diagnostic('YOLO', exc)} Survey-specific object detection is optional.")
        else:
            analysis.yolo_status = "not_configured"
            if settings.enable_yolo:
                add_diagnostic("yolo", "YOLO is enabled, but no local survey-specific weights file and explicit YOLO_ALLOWED_CLASSES are configured. Add both before enabling detection.")
            else:
                add_diagnostic("yolo", "YOLO detector is not configured; YOLO_ENABLED is false and no survey-specific weights were run. This optional capability can be configured later.")

        try:
            from app.services.fusion_service import run_evidence_fusion
            fusion_result = await run_evidence_fusion(
                analysis_id=analysis_id,
                ocr_results=ocr_results,
                cv_candidates=cv_candidates,
                yolo_detections=yolo_detections,
                llm_result=llm_result,
                target_plot_number=target_plot_number,
                db=db,
            )
            analysis.fusion_status = "ok"
        except Exception as exc:
            log.exception("Evidence fusion failed")
            analysis.fusion_status = "failed"
            add_diagnostic("fusion", _diagnostic("Evidence fusion", exc), required=True)
        await _checkpoint(db)

        if fusion_result:
            try:
                from app.services.geometry_service import reconstruct_geometry
                geometry_result = await reconstruct_geometry(analysis_id, fusion_result, db)
            except Exception as exc:
                log.exception("Geometry reconstruction failed")
                add_diagnostic("geometry", _diagnostic("Geometry reconstruction", exc), required=True)
        await _checkpoint(db)

        try:
            from app.services.feature_service import extract_survey_features
            await extract_survey_features(
                analysis_id=analysis_id,
                ocr_results=ocr_results,
                llm_result=llm_result,
                db=db,
            )
        except Exception as exc:
            log.exception("Survey feature extraction failed")
            add_diagnostic("features", _diagnostic("Survey feature extraction", exc), required=True)
        await _checkpoint(db)

        try:
            from app.services.calibration_service import calibrate_coordinates, apply_calibration
            await calibrate_coordinates(analysis_id, db)
            await apply_calibration(analysis_id, db)
        except Exception as exc:
            log.exception("Real-world coordinate calibration failed")
            add_diagnostic("calibration", _diagnostic("Calibration", exc), required=False)
        await _checkpoint(db)

        try:
            from app.services.annotation_service import create_annotated_image
            analysis.annotated_image_path = await create_annotated_image(doc.file_path, analysis_id, db)
        except Exception as exc:
            log.warning("Annotation failed: %s", exc)
            add_diagnostic("annotation", _diagnostic("Annotation generation", exc), required=True)

        analysis.status = "partial" if required_failures else "completed"
        analysis.completed_at = datetime.now(timezone.utc)
        doc.status = analysis.status
        analysis.overall_confidence = (
            geometry_result.get("geometry_support") if geometry_result else None
        )
        await _checkpoint(db)
        log.info("Analysis %s finished as %s", analysis_id, analysis.status)
    except Exception as exc:
        log.exception("Fatal analysis error")
        analysis.status = "failed"
        analysis.error_message = _diagnostic("Analysis pipeline", exc)[:2000]
        add_diagnostic("pipeline", _diagnostic("Analysis pipeline", exc), required=True)
        analysis.completed_at = datetime.now(timezone.utc)
        doc.status = "failed"
        await _checkpoint(db)
        raise
