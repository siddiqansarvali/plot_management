"""Manual geometry correction schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.geometry import CoordinateList


class ManualCorrectionCreate(BaseModel):
    real_world_coordinates: Optional[CoordinateList] = Field(None, min_length=3)
    pixel_coordinates: Optional[CoordinateList] = Field(None, min_length=3)
    real_world_unit: Optional[str] = Field(None, max_length=16)
    note: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def require_coordinate_space(self):
        if self.real_world_coordinates is None and self.pixel_coordinates is None:
            raise ValueError("Provide real-world or image-pixel coordinates.")
        if self.real_world_coordinates is not None and self.pixel_coordinates is not None:
            raise ValueError("Submit one coordinate space at a time.")
        return self


class ManualCorrectionResponse(BaseModel):
    id: str
    plot_id: str
    corrected_at: datetime
    note: Optional[str] = None
    message: str = "Correction saved. Geometry source set to 'manual'."

    model_config = {"from_attributes": True}
