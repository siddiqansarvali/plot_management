"""
Image serving routes.

GET /api/image/{document_id}/original   — serve the original uploaded image
GET /api/image/{document_id}/annotated  — serve the annotated image
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.engine import get_db
from app.database.models import AnalysisResult, Document

router = APIRouter()


def _safe_media_path(file_path: str | None, root: Path) -> Path | None:
    if not file_path:
        return None
    path = Path(file_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


@router.get(
    "/image/{document_id}/original",
    summary="Get original survey image",
    description="Returns the original uploaded survey image, unmodified.",
    response_class=FileResponse,
)
async def get_original_image(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve the original uploaded survey image."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    file_path = _safe_media_path(document.file_path, settings.resolved_upload_dir)
    if not file_path or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original image file not found on disk.",
        )

    return FileResponse(
        path=str(file_path),
        media_type=document.mime_type or ("image/jpeg" if document.file_type in {"jpg", "jpeg"} else f"image/{document.file_type}"),
        filename=document.original_filename,
    )


@router.get(
    "/image/{document_id}/annotated",
    summary="Get annotated survey image",
    description=(
        "Returns the annotated version of the survey image. "
        "Annotations are added computationally (bounding boxes, OCR labels, etc.). "
        "The original image is NOT modified."
    ),
    response_class=FileResponse,
)
async def get_annotated_image(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve the annotated survey image."""
    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.document_id == document_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis found for this document. Run /analyze first.",
        )

    if not analysis.annotated_image_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated image not yet available. Analysis may still be running.",
        )

    annotated_path = _safe_media_path(analysis.annotated_image_path, settings.resolved_output_dir)
    if not annotated_path or not annotated_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated image file not found on disk.",
        )

    return FileResponse(
        path=str(annotated_path),
        media_type="image/png",
        filename=f"annotated_{document_id}.png",
    )


@router.get(
    "/image/{document_id}/preprocessed",
    summary="Get preprocessed image",
    description="Returns the preprocessed version of the survey image (used for OCR / CV).",
    response_class=FileResponse,
)
async def get_preprocessed_image(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve the preprocessed image."""
    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.document_id == document_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis or not analysis.preprocessed_image_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preprocessed image not available.",
        )

    preprocessed_path = _safe_media_path(analysis.preprocessed_image_path, settings.resolved_output_dir)
    if not preprocessed_path or not preprocessed_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preprocessed image file not found on disk.",
        )

    return FileResponse(
        path=str(preprocessed_path),
        media_type="image/png",
        filename=f"preprocessed_{document_id}.png",
    )
