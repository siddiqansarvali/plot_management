import json
import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.engine import get_db
from app.database.models import AnalysisResult, Calibration
from app.schemas.calibration import CalibrationManualRequest, CalibrationConfirmRequest, CalibrationResponse
from app.services.calibration_service import apply_calibration

router = APIRouter()

@router.get("/analysis/{analysis_id}/calibration", response_model=CalibrationResponse, summary="Get calibration")
async def get_calibration(analysis_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Calibration).where(Calibration.analysis_id == analysis_id)
    )
    calib = result.scalar_one_or_none()
    if not calib:
        raise HTTPException(status_code=404, detail="Calibration not found")
        
    return CalibrationResponse(
        id=calib.id,
        status=calib.status,
        scale_factor_px_per_m=calib.scale_factor_px_per_m,
        confidence=calib.confidence,
        supporting_dimensions=json.loads(calib.supporting_dimensions_json or "[]"),
        residual_error=calib.residual_error,
        is_manual=calib.is_manual
    )

@router.post("/analysis/{analysis_id}/calibration/manual", response_model=CalibrationResponse, summary="Manual calibration")
async def manual_calibration(analysis_id: str, req: CalibrationManualRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.id == analysis_id)
        .options(selectinload(AnalysisResult.calibration))
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    if not analysis.calibration:
        analysis.calibration = Calibration(id=str(uuid.uuid4()), analysis_id=analysis_id)
        db.add(analysis.calibration)
        
    calib = analysis.calibration
    
    px_dist = math.hypot(req.point_1_px[0] - req.point_2_px[0], req.point_1_px[1] - req.point_2_px[1])
    if px_dist < 1:
        raise HTTPException(status_code=400, detail="Points are too close")
        
    scale = px_dist / req.known_distance_m
    
    calib.scale_factor_px_per_m = scale
    calib.status = "manual"
    calib.is_manual = True
    calib.confidence = 1.0
    calib.residual_error = 0.0
    calib.supporting_dimensions_json = json.dumps([{
        "scale_px_per_m": scale,
        "dimension_m": req.known_distance_m,
        "dimension_px": px_dist,
        "source": "Manual Calibration"
    }])
    
    await db.flush()
    await apply_calibration(analysis_id, db)
    await db.commit()
    
    return CalibrationResponse(
        id=calib.id,
        status=calib.status,
        scale_factor_px_per_m=calib.scale_factor_px_per_m,
        confidence=calib.confidence,
        supporting_dimensions=json.loads(calib.supporting_dimensions_json or "[]"),
        residual_error=calib.residual_error,
        is_manual=calib.is_manual
    )

@router.post("/analysis/{analysis_id}/calibration/confirm", response_model=CalibrationResponse, summary="Confirm auto calibration")
async def confirm_calibration(analysis_id: str, req: CalibrationConfirmRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Calibration).where(Calibration.analysis_id == analysis_id)
    )
    calib = result.scalar_one_or_none()
    if not calib:
        raise HTTPException(status_code=404, detail="Calibration not found")
        
    calib.is_manual = True # Treat confirmation as manual override to prevent recalculation
    calib.status = "manual"
    await db.commit()
    
    return CalibrationResponse(
        id=calib.id,
        status=calib.status,
        scale_factor_px_per_m=calib.scale_factor_px_per_m,
        confidence=calib.confidence,
        supporting_dimensions=json.loads(calib.supporting_dimensions_json or "[]"),
        residual_error=calib.residual_error,
        is_manual=calib.is_manual
    )
