import uuid
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import ManualCorrection

async def add_revision(
    db: AsyncSession,
    analysis_id: str,
    object_id: str,
    object_type: str,
    operation: str,
    previous_state: Optional[Dict[str, Any]],
    new_state: Dict[str, Any],
    note: Optional[str] = None,
    affected_objects: Optional[List[str]] = None,
    correction_source: str = "user"
) -> ManualCorrection:
    # Truncate the redo branch if we are making a new correction while some are undone
    undone = await db.execute(select(ManualCorrection).where(ManualCorrection.analysis_id == analysis_id, ManualCorrection.is_undone == True))
    for u in undone.scalars().all():
        await db.delete(u)

    result = await db.execute(
        select(func.max(ManualCorrection.revision_number)).where(ManualCorrection.analysis_id == analysis_id)
    )
    max_rev = result.scalar()
    next_rev = 1 if max_rev is None else max_rev + 1

    correction = ManualCorrection(
        id=str(uuid.uuid4()),
        plot_id=object_id if object_type == "plot" else None,
        analysis_id=analysis_id,
        object_id=object_id,
        object_type=object_type,
        operation=operation,
        revision_number=next_rev,
        is_undone=False,
        correction_source=correction_source,
        affected_objects_json=json.dumps(affected_objects) if affected_objects else None,
        corrected_at=datetime.now(timezone.utc),
        previous_geometry_json=json.dumps(previous_state) if previous_state else None,
        new_geometry_json=json.dumps(new_state),
        note=note
    )
    
    db.add(correction)
    return correction

async def get_revision_history(db: AsyncSession, analysis_id: str) -> List[ManualCorrection]:
    result = await db.execute(
        select(ManualCorrection)
        .where(ManualCorrection.analysis_id == analysis_id)
        .order_by(ManualCorrection.revision_number.desc())
    )
    return list(result.scalars().all())

async def undo_revision(db: AsyncSession, analysis_id: str) -> Optional[ManualCorrection]:
    # Find the latest revision that is NOT undone
    result = await db.execute(
        select(ManualCorrection)
        .where(ManualCorrection.analysis_id == analysis_id, ManualCorrection.is_undone == False)
        .order_by(ManualCorrection.revision_number.desc())
        .limit(1)
    )
    rev = result.scalar_one_or_none()
    if not rev:
        return None

    # Apply the previous state
    if rev.object_type == "plot":
        from app.database.models import Plot
        plot_res = await db.execute(select(Plot).where(Plot.id == rev.object_id))
        plot = plot_res.scalar_one_or_none()
        if plot and rev.previous_geometry_json:
            prev = json.loads(rev.previous_geometry_json)
            if rev.operation == "geometry_update" or rev.operation == "topology_propagation":
                from app.database.models import Geometry
                if not plot.geometry:
                    plot.geometry = Geometry(id=str(uuid.uuid4()), plot_id=plot.id)
                plot.geometry.pixel_coordinates_json = json.dumps(prev.get("pixel_coordinates"))
                plot.geometry.real_world_coordinates_json = json.dumps(prev.get("real_world_coordinates"))
                plot.geometry.source = prev.get("source")
                # Need to recalculate validation here ideally
            elif rev.operation == "metadata_update":
                plot.plot_number = prev.get("plot_number")
                plot.status = prev.get("status")

    rev.is_undone = True
    await db.flush()

    from app.services.calibration_service import apply_calibration
    await apply_calibration(analysis_id, db)
    
    return rev

async def redo_revision(db: AsyncSession, analysis_id: str) -> Optional[ManualCorrection]:
    # Find the earliest revision that IS undone
    result = await db.execute(
        select(ManualCorrection)
        .where(ManualCorrection.analysis_id == analysis_id, ManualCorrection.is_undone == True)
        .order_by(ManualCorrection.revision_number.asc())
        .limit(1)
    )
    rev = result.scalar_one_or_none()
    if not rev:
        return None

    # Apply the new state
    if rev.object_type == "plot":
        from app.database.models import Plot
        plot_res = await db.execute(select(Plot).where(Plot.id == rev.object_id))
        plot = plot_res.scalar_one_or_none()
        if plot and rev.new_geometry_json:
            new = json.loads(rev.new_geometry_json)
            if rev.operation == "geometry_update" or rev.operation == "topology_propagation":
                from app.database.models import Geometry
                if not plot.geometry:
                    plot.geometry = Geometry(id=str(uuid.uuid4()), plot_id=plot.id)
                plot.geometry.pixel_coordinates_json = json.dumps(new.get("pixel_coordinates"))
                plot.geometry.real_world_coordinates_json = json.dumps(new.get("real_world_coordinates"))
                plot.geometry.source = new.get("source")
            elif rev.operation == "metadata_update":
                plot.plot_number = new.get("plot_number")
                plot.status = new.get("status")

    rev.is_undone = False
    await db.flush()

    from app.services.calibration_service import apply_calibration
    await apply_calibration(analysis_id, db)
    
    return rev
