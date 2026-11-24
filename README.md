# AI Plot Layout v2

AI Plot Layout v2 is a local-first survey drawing review app. It keeps the uploaded raster unchanged, records OCR and computer-vision evidence, shows uncertain results for review, and lets a user trace or correct a plot boundary. Pixel coordinates stay in pixels; real-world coordinates and area are reported only when supported by explicit dimensions and a compatible boundary shape, or entered as a manual real-world correction with units.

The separate **Digital redraw** view uses detected plot polygons and explicit feature labels from that analysis. Feature symbols are reusable SVG patterns; a recognized OCR label is positioned at its source-image anchor and does not create a road, canal, forest, or other feature footprint. Reviewers can correct a feature label/classification, move a point anchor, confirm it, or reject it. The original survey and Annotated Preview remain separate views.

Automated boundary extraction is a candidate for human review, not a cadastral survey or a guarantee of zero errors. Verify all measurements and boundaries against the source survey before relying on them.

## Run locally

Requirements: Node.js 20.19+ (or 22.12+) and Python 3.10–3.12. Start the backend and frontend in separate terminals.

### Backend

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python run.py
```

The API starts at `http://localhost:8000`; interactive API docs are at `/docs`. The default database is a local SQLite file. Keep `.env` private.
Relative upload/output directories resolve from the backend directory, independent of the shell's current working directory. Absolute paths configured in `.env` are used as given.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to the backend on port 8000.

## Optional analysis components

- **OCR:** install `backend/requirements-ocr.txt` in a Python environment supported by the pinned PaddlePaddle release. The core application still starts if PaddleOCR is unavailable; the UI reports the stage as unavailable or failed. PaddleOCR may download model weights on first use.
- **Vision model:** set the backend-only `OPENROUTER_API_KEY` and `VISION_MODEL=openrouter/free` in `backend/.env`. Named provider/model slugs are checked against OpenRouter's image-input metadata before the uploaded image is sent. Vision returns structured semantic observations only; uncertain or unlocated features remain subject to review and do not create geometry.
- **YOLO:** optional and disabled by default. Install `backend/requirements-yolo.txt`, then configure a survey-specific weights file and its class names. Generic pretrained object-detection classes are rejected for plot-boundary selection.

## Evidence and coordinate rules

- The original uploaded image is preserved. Preprocessing and annotations are separate files.
- OCR text and confidence are displayed as observations. OCR and vision disagreements remain visible for review.
- OpenCV contours are candidates. A contour is not treated as a plot boundary without corroborating plot-label evidence.
- Image-space geometry is labeled in pixels. Pixel area is never presented as square metres.
- Dimension-based world coordinates are generated only for a corroborated rectangular candidate whose image aspect ratio agrees with the observed dimensions.
- Manual pixel tracing records a boundary but does not invent scale. A separate manual real-world correction must specify units.

## Verify changes

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm run build
```

OCR weights, external vision-provider behavior, and accuracy across real survey plans depend on installed models, provider availability, drawing quality, and human verification. The included tests and build do not establish a zero-error rate.
