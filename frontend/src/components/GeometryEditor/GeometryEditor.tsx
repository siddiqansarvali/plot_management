/** Human boundary trace/edit surface over the preserved source image. */

import { useEffect, useRef, useState } from 'react';
import { getAnalysisResult, submitGeometryCorrection, updateSurveyFeature } from '../../api/client';
import { useAnalysisStore } from '../../store/analysisStore';
import type { GeometryCorrectionRequest } from '../../types';

type Point = [number, number];
type Tool = 'select' | 'add';

export default function GeometryEditor() {
  const { upload, selectedPlot, selectedFeature } = useAnalysisStore();
  const identity = JSON.stringify([
    upload.documentId,
    selectedPlot?.id,
    selectedPlot?.geometry?.pixel_coordinates,
    selectedFeature?.id,
    selectedFeature?.geometry?.coordinates
  ]);
  return <GeometryEditorCanvas key={identity} />;
}

function GeometryEditorCanvas() {
  const store = useAnalysisStore();
  const { upload, analysis, selectedPlot, selectedFeature } = store;
  const svgRef = useRef<SVGSVGElement>(null);
  const draggingIndex = useRef<number | null>(null);
  const isDragging = useRef(false);
  const [size, setSize] = useState<[number, number]>([1200, 800]);

  const [history, setHistory] = useState<Point[][]>(() => {
    let pts: Point[] = [];
    if (selectedPlot?.geometry?.pixel_coordinates) {
      pts = selectedPlot.geometry.pixel_coordinates.map(p => [p[0], p[1]]);
    } else if (selectedFeature?.geometry?.coordinates) {
      const coords = selectedFeature.geometry.coordinates;
      if (selectedFeature.geometry.type === 'Polygon' && coords.length > 0) {
        pts = (coords[0] as number[][]).map(p => [p[0], p[1]]);
      } else if (selectedFeature.geometry.type === 'LineString') {
        pts = (coords as number[][]).map(p => [p[0], p[1]]);
      }
    }
    return [pts];
  });
  const [historyIndex, setHistoryIndex] = useState(0);
  const points = history[historyIndex];

  const updatePoints = (newPoints: Point[]) => {
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push(newPoints);
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
  };
  
  // Need local state for live dragging without committing to history yet
  const [livePoints, setLivePoints] = useState<Point[] | null>(null);
  const currentPoints = livePoints || points;

  const [selected, setSelected] = useState<number | null>(null);
  const [tool, setTool] = useState<Tool>('select');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const sourceUrl = analysis?.images.original_url
    ?? (upload.documentId ? `/api/image/${upload.documentId}/original` : null);

  useEffect(() => {
    if (!sourceUrl) return;
    const image = new Image();
    image.onload = () => setSize([image.naturalWidth, image.naturalHeight]);
    image.src = sourceUrl;
  }, [sourceUrl]);

  const pointFromEvent = (event: React.PointerEvent<SVGSVGElement>): Point | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const transformed = point.matrixTransform(matrix.inverse());
    return [transformed.x, transformed.y];
  };

  const onCanvasPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (tool !== 'add') return;
    const pt = pointFromEvent(event);
    if (!pt) return;

    if (points.length < 3) {
      updatePoints([...points, pt]);
      setSelected(points.length);
    } else {
      let minD = Infinity;
      let bestIdx = points.length;
      for (let i = 0; i < points.length; i++) {
        const p1 = points[i];
        const p2 = points[(i + 1) % points.length];
        const l2 = Math.pow(p2[0] - p1[0], 2) + Math.pow(p2[1] - p1[1], 2);
        let t = l2 === 0 ? 0 : ((pt[0] - p1[0]) * (p2[0] - p1[0]) + (pt[1] - p1[1]) * (p2[1] - p1[1])) / l2;
        t = Math.max(0, Math.min(1, t));
        const proj = [p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])];
        const dist = Math.hypot(pt[0] - proj[0], pt[1] - proj[1]);
        if (dist < minD) {
          minD = dist;
          bestIdx = i + 1;
        }
      }
      const newPoints = [...points];
      newPoints.splice(bestIdx, 0, pt);
      updatePoints(newPoints);
      setSelected(bestIdx);
    }
    setNotice(null);
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (draggingIndex.current === null) return;
    const pt = pointFromEvent(event);
    if (!pt) return;
    isDragging.current = true;
    const index = draggingIndex.current;
    setLivePoints(currentPoints.map((value, i) => i === index ? pt : value));
  };

  const onPointerUp = () => {
    if (draggingIndex.current !== null && isDragging.current && livePoints) {
      updatePoints(livePoints);
    }
    draggingIndex.current = null;
    isDragging.current = false;
    setLivePoints(null);
  };

  const deleteSelected = () => {
    if (selected === null) return;
    updatePoints(points.filter((_, index) => index !== selected));
    setSelected(null);
  };

  const undo = () => {
    if (historyIndex > 0) {
      setHistoryIndex(historyIndex - 1);
      setSelected(null);
    }
  };
  
  const redo = () => {
    if (historyIndex < history.length - 1) {
      setHistoryIndex(historyIndex + 1);
      setSelected(null);
    }
  };

  const saveCorrection = async () => {
    if ((!selectedPlot && !selectedFeature) || points.length < 3) {
      setError('Add at least three boundary points before saving.');
      return;
    }
    if (new Set(points.map(([x, y]) => `${x.toFixed(2)}:${y.toFixed(2)}`)).size < 3) {
      setError('The boundary needs three distinct points.');
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      if (selectedPlot) {
        const correction: GeometryCorrectionRequest = {
          pixel_coordinates: points,
          note: 'Manually traced in the source image.',
        };
        await submitGeometryCorrection(selectedPlot.id, correction);
      } else if (selectedFeature) {
        await updateSurveyFeature(selectedFeature.id, {
          geometry: {
            type: 'Polygon',
            coordinates: [points],
            coordinate_space: 'image_pixels',
          }
        });
      }
      
      if (upload.documentId) {
        const updated = await getAnalysisResult(upload.documentId);
        store.setAnalysis(updated);
      }
      store.setEditingGeometry(false);
      setNotice('Boundary saved. Real-world scale remains unknown until a measurement is calibrated.');
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Could not save the boundary.';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  if (!sourceUrl || !analysis) {
    return <div className="card p-6 text-sm" style={{ color: 'var(--text-muted)' }}>Upload and analyze a survey before editing a boundary.</div>;
  }

  return (
    <section className="card p-4 md:p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>Boundary editor</h2>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Trace the visible boundary on the source image. These points stay in image pixels; no scale is assumed.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={tool === 'select' ? 'btn-primary' : 'btn-secondary'} onClick={() => setTool('select')}>Select / drag</button>
          <button className={tool === 'add' ? 'btn-primary' : 'btn-secondary'} onClick={() => setTool('add')}>Add points</button>
          <button className="btn-secondary" onClick={undo} disabled={historyIndex === 0}>Undo</button>
          <button className="btn-secondary" onClick={redo} disabled={historyIndex === history.length - 1}>Redo</button>
          <button className="btn-secondary" onClick={deleteSelected} disabled={selected === null}>Delete selected</button>
          <button className="btn-ghost" onClick={() => { updatePoints([]); setSelected(null); setTool('add'); }}>Start over</button>
        </div>
      </div>

      <div className="geometry-editor-canvas">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${size[0]} ${size[1]}`}
          preserveAspectRatio="xMidYMid meet"
          onPointerDown={onCanvasPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
          className={tool === 'add' ? 'cursor-crosshair touch-none' : 'cursor-default touch-none'}
          aria-label="Boundary editor over the original survey image"
        >
          <image
            href={sourceUrl}
            x="0" y="0" width={size[0]} height={size[1]}
            preserveAspectRatio="none"
          />
          {history.length > 1 && history[0].length >= 3 && (
            <polygon points={history[0].map(([x, y]) => `${x},${y}`).join(' ')}
                     fill="none" stroke="rgba(248,113,113,0.5)" strokeWidth={Math.max(size[0] / 500, 1)} strokeDasharray="5,5" />
          )}
          {currentPoints.length >= 3 && (
            <polygon points={currentPoints.map(([x, y]) => `${x},${y}`).join(' ')}
                     fill="rgba(56,189,248,.13)" stroke="#38bdf8" strokeWidth={Math.max(size[0] / 500, 2)} />
          )}
          {currentPoints.length === 2 && (
            <polyline points={currentPoints.map(([x, y]) => `${x},${y}`).join(' ')}
                      fill="none" stroke="#38bdf8" strokeWidth={Math.max(size[0] / 500, 2)} />
          )}
          {currentPoints.map(([x, y], index) => (
            <g key={`${index}-${x.toFixed(1)}-${y.toFixed(1)}`}>
              <circle
                cx={x} cy={y} r={Math.max(Math.min(size[0], size[1]) / 90, 9)}
                fill={selected === index ? '#fbbf24' : '#e0f2fe'}
                stroke="#0369a1" strokeWidth={Math.max(size[0] / 700, 2)}
                onPointerDown={event => {
                  event.stopPropagation();
                  setSelected(index);
                  if (tool === 'select') {
                    draggingIndex.current = index;
                    event.currentTarget.ownerSVGElement?.setPointerCapture(event.pointerId);
                  }
                }}
                style={{ cursor: tool === 'select' ? 'move' : 'pointer' }}
              />
              <text x={x} y={y} textAnchor="middle" dominantBaseline="central"
                    fontSize={Math.max(Math.min(size[0], size[1]) / 180, 8)} fontWeight="700" fill="#082f49" pointerEvents="none">
                {index + 1}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {points.length} vertices · image-space area only · {selectedPlot ? `Plot ${selectedPlot.plot_number || 'unknown'}` : selectedFeature ? `${selectedFeature.feature_type}: ${selectedFeature.label || 'unlabeled'}` : 'unknown item'}
        </span>
        <button className="btn-primary" onClick={saveCorrection} disabled={saving || points.length < 3}>
          {saving ? 'Saving…' : 'Save manual boundary'}
        </button>
      </div>
      {error && <p role="alert" className="notice-error">{error}</p>}
      {notice && <p role="status" className="notice-success">{notice}</p>}
    </section>
  );
}
