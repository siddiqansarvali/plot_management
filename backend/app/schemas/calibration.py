from typing import Optional, List
from pydantic import BaseModel, Field

class CalibrationManualRequest(BaseModel):
    known_distance_m: float = Field(..., description="The actual distance in meters")
    point_1_px: List[float] = Field(..., description="[x, y] in image pixels")
    point_2_px: List[float] = Field(..., description="[x, y] in image pixels")

class CalibrationConfirmRequest(BaseModel):
    is_confirmed: bool = True

class CalibrationResponse(BaseModel):
    id: str
    status: str
    scale_factor_px_per_m: Optional[float]
    confidence: Optional[float]
    supporting_dimensions: Optional[List[dict]]
    residual_error: Optional[float]
    is_manual: bool
