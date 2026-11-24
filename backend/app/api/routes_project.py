"""
Project management routes.

GET    /api/project          — list all projects
POST   /api/project          — create a project
GET    /api/project/{id}     — get project details with documents
PUT    /api/project/{id}     — update project
DELETE /api/project/{id}     — delete project
"""

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.engine import get_db
from app.database.models import Document, Project
from app.schemas.project import (
    DocumentResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter()


@router.get(
    "/project",
    response_model=List[ProjectResponse],
    summary="List all projects",
)
async def list_projects(db: AsyncSession = Depends(get_db)) -> List[ProjectResponse]:
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()

    responses = []
    for p in projects:
        count_result = await db.execute(
            select(func.count()).where(Document.project_id == p.id)
        )
        doc_count = count_result.scalar() or 0
        responses.append(ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            created_at=p.created_at,
            updated_at=p.updated_at,
            document_count=doc_count,
        ))
    return responses


@router.post(
    "/project",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    now = datetime.now(timezone.utc)
    project = Project(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        updated_at=project.updated_at,
        document_count=0,
    )


@router.get(
    "/project/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get project details with documents",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectDetailResponse:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.documents))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        updated_at=project.updated_at,
        document_count=len(project.documents),
        documents=[DocumentResponse.model_validate(d) for d in project.documents],
    )


@router.put(
    "/project/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    project.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        created_at=project.created_at, updated_at=project.updated_at, document_count=0,
    )


@router.delete(
    "/project/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project",
)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    await db.delete(project)
