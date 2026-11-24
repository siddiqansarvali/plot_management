from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import Optional

from app.database.engine import get_db
from app.database.models import Plot

router = APIRouter()

class PlotUpdate(BaseModel):
    plot_number: Optional[str] = None
    review_status: Optional[str] = None

@router.patch("/plots/{plot_id}", summary="Update a plot")
async def update_plot(
    plot_id: str,
    update: PlotUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Plot).where(Plot.id == plot_id)
    )
    plot = result.scalar_one_or_none()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")
        
    from app.services.revision_service import add_revision
    
    prev_state = {"plot_number": plot.plot_number, "status": plot.status}
    
    if update.plot_number is not None:
        plot.plot_number = update.plot_number
    
    if update.review_status is not None:
        plot.status = update.review_status

    await add_revision(
        db=db,
        analysis_id=plot.analysis_id,
        object_id=plot_id,
        object_type="plot",
        operation="metadata_update",
        previous_state=prev_state,
        new_state={"plot_number": plot.plot_number, "status": plot.status},
        note="Manual plot number correction"
    )
        
    await db.flush()
    return {"id": plot.id, "plot_number": plot.plot_number, "status": plot.status}
