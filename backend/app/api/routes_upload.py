"""
Upload API routes.
POST /api/upload — accepts an image file and stores it safely.

Phase 2 implementation: full file validation, storage, DB record creation.
"""

import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.engine import get_db
from app.database.models import Document, Project
from app.schemas.project import DocumentUploadResponse
from app.utils.file_utils import safe_filename, validate_upload_file

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a survey image",
    description=(
        "Upload a survey image (PNG, JPG, JPEG, WEBP). "
        "The original file is preserved unchanged. "
        "Returns a document_id used for subsequent analysis."
    ),
)
async def upload_survey_image(
    file: UploadFile = File(..., description="Survey image file"),
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a survey image.

    - Validates file type and size.
    - Stores the file with a safe, unique filename.
    - Creates a Document record in the database.
    - Returns document_id for subsequent /analyze calls.
    """
    # ── Validate file ──────────────────────────────────────────────────────────
    validation_error = await validate_upload_file(file)
    if validation_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation_error,
        )

    # ── Read file content ──────────────────────────────────────────────────────
    content = await file.read(settings.max_file_size_bytes + 1)

    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_file_size_mb} MB.",
        )

    # ── Decode and verify the actual raster, not only its filename ─────────────
    ext = Path(file.filename).suffix.lower().lstrip(".")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as img:
            actual_format = (img.format or "").upper()
            width_px, height_px = img.size
            if width_px <= 0 or height_px <= 0 or width_px * height_px > 50_000_000:
                raise ValueError("Image dimensions exceed the supported 50 megapixel limit.")
            img.verify()
        expected_formats = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
        if actual_format != expected_formats.get(ext):
            raise ValueError("The file contents do not match the filename extension.")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unsupported image: {exc}",
        ) from exc

    if project_id:
        project = await db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    # ── Generate a safe unique name only after content verification ────────────
    unique_id = str(uuid.uuid4())
    s_filename = safe_filename(file.filename, unique_id)
    upload_dir = settings.resolved_upload_dir
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / s_filename
        file_path.write_bytes(content)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded image.",
        ) from exc

    # ── Create DB record ───────────────────────────────────────────────────────
    mime_type, _ = mimetypes.guess_type(file.filename)
    document = Document(
        id=unique_id,
        project_id=project_id,
        original_filename=file.filename,
        safe_filename=s_filename,
        file_path=str(file_path.absolute()),
        file_type=ext,
        file_size=len(content),
        mime_type=mime_type,
        image_width_px=width_px,
        image_height_px=height_px,
        uploaded_at=datetime.now(timezone.utc),
        status="uploaded",
    )
    db.add(document)
    await db.flush()  # Persist within transaction (commit happens in get_db)

    return DocumentUploadResponse(
        document_id=unique_id,
        message="File uploaded successfully. Call POST /api/analyze/{document_id} to begin analysis.",
        filename=file.filename,
        file_size=len(content),
        status="uploaded",
    )
