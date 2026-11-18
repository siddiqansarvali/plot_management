import asyncio
import json
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database.engine import AsyncSessionLocal
from app.database.models import AnalysisResult, CVCandidate, Plot, Validation

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AnalysisResult)
            .where(AnalysisResult.document_id == 'ce465531-b0fb-4185-ba41-e85cd468cb13')
            .options(
                selectinload(AnalysisResult.cv_candidates), 
                selectinload(AnalysisResult.plots).selectinload(Plot.validation)
            )
        )
        analysis = result.scalar_one_or_none()
        if not analysis:
            print('Analysis not found')
            return
        print(f'Analysis ID: {analysis.id}')
        print(f'CV Candidates: {len(analysis.cv_candidates)}')
        print(f'Plots: {len(analysis.plots)}')
        
        # Look at the evidence_log of the latest plot candidates
        for plot in analysis.plots:
            val_details = json.loads(plot.validation.details_json) if plot.validation and plot.validation.details_json else {}
            evidence_log = val_details.get("evidence_log", [])
            print(f"Plot {plot.plot_number}: status={plot.status}")
            print(f"  Evidence Log: {evidence_log}")

asyncio.run(main())
