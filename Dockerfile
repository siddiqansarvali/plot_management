# ==============================================================================
# AI Plot Layout Management System - Multi-Stage Production Dockerfile
# Stage 1: Build the React 19 Frontend with Vite
# Stage 2: Production Python Backend with OpenCV & Static SPA Serving
# ==============================================================================

# --- Stage 1: Frontend Build ---
FROM node:20-alpine AS frontend-builder
WORKDIR /build

# Install dependencies with clean cache
COPY frontend/package*.json ./
RUN npm ci --silent

# Copy frontend source and build optimized production bundle
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Production Runtime ---
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

# Install essential system libraries for OpenCV headless and font rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/app ./app
COPY backend/run.py ./run.py
COPY backend/.env.example ./.env.example

# Copy compiled frontend from Stage 1 into the location expected by FastAPI SPA serving
COPY --from=frontend-builder /build/dist /app/frontend/dist

# Create upload and output directories with write permissions
RUN mkdir -p /app/uploads /app/outputs && chmod -R 777 /app/uploads /app/outputs

# Health check to ensure the container is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
