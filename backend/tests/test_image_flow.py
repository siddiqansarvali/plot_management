from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.api import routes_analysis
from app.config import settings
from app.database.engine import Base, get_db


@pytest.mark.asyncio
async def test_upload_analysis_exposes_original_preprocessed_and_annotated_images(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    database_path = tmp_path / "flow.sqlite"
    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "output_dir", output_dir)
    monkeypatch.setattr(settings, "enable_ocr", False)
    monkeypatch.setattr(settings, "enable_llm", False)
    monkeypatch.setattr(settings, "enable_yolo", False)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(routes_analysis, "AsyncSessionLocal", session_factory)

    async def override_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setitem(main.app.dependency_overrides, get_db, override_db)

    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 25, 210, 135), outline="black", width=4)
    source = BytesIO()
    image.save(source, format="PNG")

    try:
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://localhost:8000") as client:
            upload_response = await client.post(
                "/api/upload",
                files={"file": ("survey.png", source.getvalue(), "image/png")},
            )
            assert upload_response.status_code == 201
            document_id = upload_response.json()["document_id"]

            trigger_response = await client.post(f"/api/analyze/{document_id}", json={})
            assert trigger_response.status_code == 202

            analysis_response = await client.get(f"/api/analysis/{document_id}")
            assert analysis_response.status_code == 200
            result = analysis_response.json()
            assert result["document_name"] == "survey.png"
            assert result["status"] == "partial"
            assert result["components"]["preprocessing"] == "ok"
            assert result["components"]["ocr"] == "disabled"
            assert "disabled by backend configuration" in result["component_diagnostics"]["ocr"]
            assert "optional" in result["component_diagnostics"]["llm"]
            assert "optional" in result["component_diagnostics"]["yolo"]
            assert result["images"]["original_url"] == f"/api/image/{document_id}/original"
            assert result["images"]["preprocessed_url"] == f"/api/image/{document_id}/preprocessed"
            assert result["images"]["annotated_url"] == f"/api/image/{document_id}/annotated"
            assert "plots" in result and "features" in result
            assert result["plots"][0]["plot_number"] is None
            assert result["plots"][0]["geometry"] is None

            for key in ("original_url", "preprocessed_url", "annotated_url"):
                image_response = await client.get(result["images"][key])
                assert image_response.status_code == 200
                assert image_response.headers["content-type"].startswith("image/")
                assert image_response.content

            preflight = await client.options(
                "/api/features/example-feature",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "PATCH",
                },
            )
            assert preflight.status_code == 200
            assert "PATCH" in preflight.headers["access-control-allow-methods"]
    finally:
        await engine.dispose()
