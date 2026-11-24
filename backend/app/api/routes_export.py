"""
Export routes.

GET /api/export/{analysis_id}/svg  — export as SVG
GET /api/export/{analysis_id}/pdf  — export as PDF
GET /api/export/{analysis_id}/geojson  — export as GeoJSON
GET /api/export/{analysis_id}/dxf  — export as DXF
"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.engine import get_db
from app.services.export_service import fetch_authoritative_survey, validate_export
from app.services.export_generators import generate_svg, generate_pdf, generate_geojson, generate_dxf

router = APIRouter()

@router.get("/export/{analysis_id}/status")
async def export_status(analysis_id: str, db: AsyncSession = Depends(get_db)):
    analysis = await fetch_authoritative_survey(analysis_id, db)
    return validate_export(analysis)

@router.get("/export/{analysis_id}/svg")
async def export_svg(analysis_id: str, db: AsyncSession = Depends(get_db)):
    analysis = await fetch_authoritative_survey(analysis_id, db)
    val = validate_export(analysis)
    if val["status"] == "blocked":
        raise HTTPException(status_code=400, detail="Export blocked: " + "; ".join(val["reasons"]))
        
    svg = generate_svg(analysis)
    return Response(content=svg, media_type="image/svg+xml", headers={"Content-Disposition": f"attachment; filename=survey_{analysis_id}.svg"})

@router.get("/export/{analysis_id}/pdf")
async def export_pdf(analysis_id: str, db: AsyncSession = Depends(get_db)):
    analysis = await fetch_authoritative_survey(analysis_id, db)
    val = validate_export(analysis)
    if val["status"] == "blocked":
        raise HTTPException(status_code=400, detail="Export blocked: " + "; ".join(val["reasons"]))
        
    pdf_bytes = generate_pdf(analysis)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=survey_{analysis_id}.pdf"})

@router.get("/export/{analysis_id}/geojson")
async def export_geojson(analysis_id: str, db: AsyncSession = Depends(get_db)):
    analysis = await fetch_authoritative_survey(analysis_id, db)
    val = validate_export(analysis)
    if val["status"] == "blocked":
        raise HTTPException(status_code=400, detail="Export blocked: " + "; ".join(val["reasons"]))
        
    geojson = generate_geojson(analysis)
    return JSONResponse(content=geojson, headers={"Content-Disposition": f"attachment; filename=survey_{analysis_id}.geojson"})

@router.get("/export/{analysis_id}/dxf")
async def export_dxf(analysis_id: str, db: AsyncSession = Depends(get_db)):
    analysis = await fetch_authoritative_survey(analysis_id, db)
    val = validate_export(analysis)
    if val["status"] == "blocked":
        raise HTTPException(status_code=400, detail="Export blocked: " + "; ".join(val["reasons"]))
        
    dxf_bytes = generate_dxf(analysis)
    return Response(content=dxf_bytes, media_type="application/dxf", headers={"Content-Disposition": f"attachment; filename=survey_{analysis_id}.dxf"})
