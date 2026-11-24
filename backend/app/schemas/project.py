"""
Project and Document Pydantic schemas.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ── Document ───────────────────────────────────────────────────────────────────
class DocumentBase(BaseModel):
    original_filename: str
    file_type: str
    file_size: int
    mime_type: Optional[str] = None


class DocumentCreate(DocumentBase):
    project_id: Optional[str] = None


class DocumentResponse(DocumentBase):
    id: str
    project_id: Optional[str] = None
    safe_filename: str
    uploaded_at: datetime
    status: str
    image_width_px: Optional[int] = None
    image_height_px: Optional[int] = None

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    document_id: str
    message: str
    filename: str
    file_size: int
    status: str = "uploaded"


# ── Project ────────────────────────────────────────────────────────────────────
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    documents: List[DocumentResponse] = []
