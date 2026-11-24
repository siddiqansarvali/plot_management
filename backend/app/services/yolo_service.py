"""Optional survey-specific detector adapter. Generic YOLO weights are rejected."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Detection

log = logging.getLogger(__name__)


async def run_yolo_detection(
    image_path: str,
    analysis_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Run only a configured local model with an explicit survey class allowlist."""
    model_path = Path(settings.yolo_model).expanduser() if settings.yolo_model else None
    allowed = {name.strip().casefold() for name in settings.yolo_allowed_classes.split(",") if name.strip()}
    if model_path is None or not model_path.is_file() or not allowed:
        raise RuntimeError("YOLO unavailable: configure a local survey model and YOLO_ALLOWED_CLASSES.")

    def detect():
        from ultralytics import YOLO

        model = YOLO(str(model_path))
        names = model.names
        supported = {int(key): str(value) for key, value in names.items()
                     if str(value).casefold() in allowed}
        if not supported:
            raise RuntimeError("Configured YOLO model has no classes in YOLO_ALLOWED_CLASSES.")
        output: list[dict[str, Any]] = []
        for result in model(image_path, verbose=False):
            if result.boxes is None:
                continue
            for box in result.boxes:
                class_id = int(box.cls[0].item())
                if class_id not in supported:
                    continue
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                output.append({
                    "id": str(uuid.uuid4()),
                    "class_name": supported[class_id],
                    "confidence": float(box.conf[0].item()),
                    "bbox": [x1, y1, x2, y2],
                    "center": [(x1 + x2) / 2, (y1 + y2) / 2],
                    "detector": model_path.name,
                })
        return output

    detections = await asyncio.to_thread(detect)
    for item in detections:
        db.add(Detection(
            id=item["id"], analysis_id=analysis_id,
            class_name=item["class_name"], confidence=item["confidence"],
            detector=item["detector"], bbox_json=json.dumps(item["bbox"]),
            center_json=json.dumps(item["center"]),
        ))
    await db.flush()
    return detections
