"""
Entry point for the AI Plot Layout Management backend server.

Run with:
    python run.py
    or
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import uvicorn
from app.config import settings


if __name__ == "__main__":
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="debug" if settings.debug else "info",
    )
