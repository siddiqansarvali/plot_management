"""
Analysis API routes.

POST /api/analyze/{document_id}  — trigger the analysis pipeline
GET  /api/analysis/{document_id} — retrieve analysis results

KEY FIX: The background task uses its OWN session (AsyncSessionLocal) and
commits independently. The request handler commits the pending/analysis
record BEFORE the background task runs, so the task always finds the record.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.engine import get_db, AsyncSessionLocal
from app.database.models import (
    AnalysisResult, Boundary, CVCandidate, Detection, Document, Geometry,
    ManualCorrection, Measurement, OCRResult, Plot, SurveyFeature, Validation,
)
from app.schemas.analysis import (
    AnalysisResponse,
    AnalysisTriggerRequest,
    AnalysisTriggerResponse,
    ComponentStatusSchema,
    ConfidenceSchema,
    ImagesSchema,
)

router = APIRouter()


@router.post(
    "/analyze/{document_id}",
    response_model=AnalysisTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger analysis pipeline",
    description=(
        "Starts the full AI analysis pipeline for the uploaded document. "
        "The pipeline runs asynchronously. Poll GET /api/analysis/{document_id} for results."
    ),
)
async def trigger_analysis(
    document_id: str,
    request: AnalysisTriggerRequest = None,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
) -> AnalysisTriggerResponse:
    """Trigger the analysis pipeline for a document."""

    if request is None:
        request = AnalysisTriggerRequest()

    # ── Verify document exists ─────────────────────────────────────────────────
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    # ── Check existing analysis ────────────────────────────────────────────────
    existing = await db.execute(
        select(AnalysisResult).where(AnalysisResult.document_id == document_id)
    )
    analysis = existing.scalar_one_or_none()

    if analysis and analysis.status in ("pending", "running"):
        return AnalysisTriggerResponse(
            document_id=document_id,
            analysis_id=analysis.id,
            status=analysis.status,
            message="Analysis is already in progress.",
        )

    if analysis and not request.force_reanalyze and analysis.status == "completed":
        return AnalysisTriggerResponse(
            document_id=document_id,
            analysis_id=analysis.id,
            status="completed",
            message="Analysis already completed. Set force_reanalyze=true to re-run.",
        )

    # ── Create or reset analysis record ───────────────────────────────────────
    if analysis:
        plot_ids = select(Plot.id).where(Plot.analysis_id == analysis.id)
        for model in (ManualCorrection, Validation, Geometry, Boundary, Measurement):
            await db.execute(delete(model).where(model.plot_id.in_(plot_ids)))
        for model in (Plot, OCRResult, Detection, CVCandidate, SurveyFeature):
            await db.execute(delete(model).where(model.analysis_id == analysis.id))
        analysis.status = "pending"
        analysis.started_at = None
        analysis.completed_at = None
        analysis.error_message = None
        analysis.ocr_status = None
        analysis.llm_status = None
        analysis.yolo_status = None
        analysis.opencv_status = None
        analysis.fusion_status = None
        analysis.component_diagnostics_json = None
        analysis.preprocessed_image_path = None
        analysis.annotated_image_path = None
        analysis.llm_raw_response = None
        analysis.overall_confidence = None
        analysis_id = analysis.id
    else:
        analysis_id = str(uuid.uuid4())
        analysis = AnalysisResult(
            id=analysis_id,
            document_id=document_id,
            status="pending",
        )
        db.add(analysis)

    # Update document status
    document.status = "processing"

    # ── CRITICAL: flush + commit NOW so background task can find this record ───
    await db.flush()
    await db.commit()

    # ── Queue background task ─────────────────────────────────────────────────
    # The background task uses its own independent session — no shared state.
    background_tasks.add_task(
        _run_pipeline_background,
        document_id=document_id,
        analysis_id=analysis_id,
        target_plot_number=request.target_plot_number,
    )

    return AnalysisTriggerResponse(
        document_id=document_id,
        analysis_id=analysis_id,
        status="pending",
        message="Analysis pipeline queued. Poll GET /api/analysis/{document_id} for results.",
    )


async def _run_pipeline_background(
    document_id: str,
    analysis_id: str,
    target_plot_number: str | None,
) -> None:
    """
    Run the full analysis pipeline in a background task.

    Uses its own independent DB session — fully self-contained.
    The pipeline commits at each checkpoint so polls see live progress.
    On any fatal error, a fresh session writes the failure status.
    """
    from app.services.pipeline import _diagnostic, run_full_pipeline

    pipeline_error: Exception | None = None

    async with AsyncSessionLocal() as db:
        try:
            await run_full_pipeline(
                db=db,
                document_id=document_id,
                analysis_id=analysis_id,
                target_plot_number=target_plot_number,
            )
            # Pipeline already committed its final "completed" checkpoint.
            # This is a safety net commit for any last-flush not yet committed.
            await db.commit()
        except Exception as exc:
            pipeline_error = exc
            try:
                await db.rollback()
            except Exception:
                pass

    # ── If pipeline failed, write failure status in a fresh clean session ──────
    if pipeline_error is not None:
        async with AsyncSessionLocal() as error_db:
            try:
                result = await error_db.execute(
                    select(AnalysisResult).where(AnalysisResult.id == analysis_id)
                )
                analysis = result.scalar_one_or_none()
                if analysis and analysis.status not in ("completed", "partial"):
                    analysis.status = "failed"
                    analysis.error_message = _diagnostic("Analysis pipeline", pipeline_error)
                    analysis.completed_at = datetime.now(timezone.utc)

                doc_result = await error_db.execute(
                    select(Document).where(Document.id == document_id)
                )
                doc = doc_result.scalar_one_or_none()
                if doc and doc.status == "processing":
                    doc.status = "failed"

                await error_db.commit()
            except Exception:
                await error_db.rollback()



@router.get(
    "/analysis/{document_id}",
    response_model=AnalysisResponse,
    summary="Get analysis results",
    description="Retrieve the full analysis result for a document, including all plots, geometry, OCR, and validation.",
)
async def get_analysis(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> AnalysisResponse:
    """Retrieve the full analysis result for a document."""

    # Verify document exists
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    document = doc_result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    # Load analysis with all relationships
    result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.document_id == document_id)
        .options(
            selectinload(AnalysisResult.plots),
            selectinload(AnalysisResult.ocr_results),
            selectinload(AnalysisResult.detections),
            selectinload(AnalysisResult.cv_candidates),
            selectinload(AnalysisResult.features),
            selectinload(AnalysisResult.calibration),
            selectinload(AnalysisResult.plots).selectinload(Plot.measurements),
            selectinload(AnalysisResult.plots).selectinload(Plot.boundaries),
            selectinload(AnalysisResult.plots).selectinload(Plot.geometry),
            selectinload(AnalysisResult.plots).selectinload(Plot.validation),
        )
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        return AnalysisResponse(
            status="not_started",
            document_id=document_id,
            message="Analysis has not been started for this document.",
        )

    # ── Build response ─────────────────────────────────────────────────────────
    from app.utils.response_builder import build_analysis_response
    return await build_analysis_response(analysis, document, db)

@router.post("/analysis/{analysis_id}/undo", summary="Undo last manual correction")
async def undo_analysis_correction(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    from app.services.revision_service import undo_revision
    rev = await undo_revision(db, analysis_id)
    if not rev:
        raise HTTPException(status_code=400, detail="Nothing to undo.")
    return {"status": "success", "message": "Reverted to previous state."}

@router.post("/analysis/{analysis_id}/redo", summary="Redo next manual correction")
async def redo_analysis_correction(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    from app.services.revision_service import redo_revision
    rev = await redo_revision(db, analysis_id)
    if not rev:
        raise HTTPException(status_code=400, detail="Nothing to redo.")
    return {"status": "success", "message": "Restored later state."}

@router.get("/analysis/{analysis_id}/history", summary="Get revision history")
async def get_analysis_history(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    from app.services.revision_service import get_revision_history
    history = await get_revision_history(db, analysis_id)
    return [{
        "id": h.id,
        "revision_number": h.revision_number,
        "object_id": h.object_id,
        "object_type": h.object_type,
        "operation": h.operation,
        "is_undone": h.is_undone,
        "corrected_at": h.corrected_at,
        "note": h.note
    } for h in history]
