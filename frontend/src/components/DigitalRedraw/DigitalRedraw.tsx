import { useMemo, useRef, useState } from 'react';
import { getAnalysisResult, getExportUrl, updateSurveyFeature } from '../../api/client';
import { useAnalysisStore } from '../../store/analysisStore';
import type { FeatureGeometry, Plot, SurveyFeature, SurveyFeatureType } from '../../types';
import FeatureRenderer, { FeaturePatterns } from './FeatureRenderer';
import { featureTypeLabel } from './featureTypes';

type Point = [number, number];
type ViewBounds = { x: number; y: number; width: number; height: number };

const FEATURE_TYPES: SurveyFeatureType[] = [
  'plot', 'road', 'canal', 'river_stream', 'railway', 'forest',
  'agricultural_land', 'open_land', 'park_green_area', 'building',
  'boundary_wall', 'drainage', 'water_body', 'utility_corridor',
  'pathway', 'layout_boundary', 'north_arrow', 'dimension_line',
  'survey_reference', 'unknown_feature',
];

function geometryPoints(geometry: FeatureGeometry | null): Point[] {
  if (!geometry) return [];
  if (geometry.type === 'Point') return [geometry.coordinates as Point];
  if (geometry.type === 'LineString') return geometry.coordinates as Point[];
  return (geometry.coordinates as Point[][]).flat();
}

function pointGeometry(point: Point): FeatureGeometry {
  return { type: 'Point', coordinates: point, coordinate_space: 'image_pixels' };
}

export default function DigitalRedraw() {
  const { analysis } = useAnalysisStore();
  return <DigitalRedrawWorkspace key={analysis?.analysis_id ?? analysis?.document_id ?? 'empty'} />;
}

function DigitalRedrawWorkspace() {
  const store = useAnalysisStore();
  const { analysis, selectedPlot, upload } = store;
  const svgRef = useRef<SVGSVGElement>(null);
  const panRef = useRef<Point | null>(null);
  const draggingFeatureId = useRef<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>([0, 0]);
  const [coordinateMode, setCoordinateMode] = useState<'image' | 'survey'>('image');
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [geometryDrafts, setGeometryDrafts] = useState<Record<string, FeatureGeometry>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'detected' | 'manual' | 'uncertain'>('all');
  const [hoveredPlotId, setHoveredPlotId] = useState<string | null>(null);

  const features = analysis?.features ?? [];
  const visibleFeatures = features.filter(feature => feature.review_status !== 'rejected');
  const plotRecords = analysis?.plots ?? [];
  const pixelPlots = plotRecords.filter(plot => (plot.geometry?.pixel_coordinates?.length ?? 0) >= 3);
  
  // Filtered plots based on search & status
  const filteredPlots = useMemo(() => {
    return pixelPlots.filter(plot => {
      if (statusFilter !== 'all' && plot.status !== statusFilter) return false;
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase().trim();
      const numMatch = (plot.plot_number ?? '').toLowerCase().includes(q);
      const statedAreaMatch = String(plot.measurements?.stated_area_m2?.value ?? '').includes(q);
      const calcAreaMatch = String(Math.round(plot.measurements?.calculated_area_m2 ?? 0)).includes(q);
      return numMatch || statedAreaMatch || calcAreaMatch;
    });
  }, [pixelPlots, searchQuery, statusFilter]);

  const boundaryNotes = (['north', 'east', 'south', 'west'] as const).flatMap(direction => {
    const value = selectedPlot?.boundaries?.[direction]?.value;
    return typeof value === 'string' && value.trim() ? [{ direction, value }] : [];
  });

  const bounds = useMemo<ViewBounds | null>(() => {
    const points: Point[] = [];
    for (const plot of pixelPlots) {
      if (coordinateMode === 'survey' && plot.geometry?.real_world_coordinates) {
        points.push(...plot.geometry.real_world_coordinates);
      } else {
        points.push(...(plot.geometry?.pixel_coordinates ?? []));
      }
    }
    for (const feature of visibleFeatures) {
      if (coordinateMode === 'image') {
        points.push(...geometryPoints(geometryDrafts[feature.id] ?? feature.geometry));
      }
    }
    const valid = points.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    if (!valid.length) return null;
    const xs = valid.map(([x]) => x);
    const ys = valid.map(([, y]) => y);
    const rawWidth = Math.max(...xs) - Math.min(...xs);
    const rawHeight = Math.max(...ys) - Math.min(...ys);
    const padding = Math.max(rawWidth, rawHeight, 1) * 0.11;
    const width = Math.max(rawWidth + padding * 2, 2);
    const height = Math.max(rawHeight + padding * 2, 2);
    return { x: Math.min(...xs) - padding, y: Math.min(...ys) - padding, width, height };
  }, [pixelPlots, visibleFeatures, geometryDrafts, coordinateMode]);

  const viewBox = bounds
    ? `${bounds.x + pan[0] + bounds.width * (1 - 1 / zoom) / 2} ${bounds.y + pan[1] + bounds.height * (1 - 1 / zoom) / 2} ${bounds.width / zoom} ${bounds.height / zoom}`
    : '0 0 100 100';
  const markerSize = bounds ? Math.max(Math.max(bounds.width, bounds.height) * 0.018, 5) : 8;
  const selectedFeature = visibleFeatures.find(feature => feature.id === selectedFeatureId) ?? null;

  const pointFromEvent = (event: React.PointerEvent<SVGSVGElement>): Point | null => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const imagePoint = point.matrixTransform(matrix.inverse());
    return [imagePoint.x, imagePoint.y];
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (draggingFeatureId.current) {
      const point = pointFromEvent(event);
      if (!point) return;
      const id = draggingFeatureId.current;
      setGeometryDrafts(current => ({ ...current, [id]: pointGeometry(point) }));
      return;
    }
    if (!panRef.current || !bounds || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const current: Point = [event.clientX, event.clientY];
    const dx = current[0] - panRef.current[0];
    const dy = current[1] - panRef.current[1];
    setPan(([x, y]) => [x - dx * (bounds.width / zoom) / rect.width, y - dy * (bounds.height / zoom) / rect.height]);
    panRef.current = current;
  };

  const centerOnPlot = (plot: Plot) => {
    store.setSelectedPlot(plot);
    if (!bounds) return;
    const coordinates = coordinateMode === 'survey' && plot.geometry?.real_world_coordinates
      ? plot.geometry.real_world_coordinates
      : plot.geometry?.pixel_coordinates ?? [];
    if (!coordinates.length) return;
    const cx = coordinates.reduce((sum, [x]) => sum + x, 0) / coordinates.length;
    const cy = coordinates.reduce((sum, [, y]) => sum + y, 0) / coordinates.length;
    const centerX = bounds.x + bounds.width / 2;
    const centerY = bounds.y + bounds.height / 2;
    setPan([cx - centerX, cy - centerY]);
    setZoom(1.4);
  };

  const saveFeature = async (
    feature: SurveyFeature,
    patch: Partial<Pick<SurveyFeature, 'feature_type' | 'label' | 'geometry' | 'review_status'>>,
  ) => {
    if (!upload.documentId) return;
    setSavingId(feature.id);
    setError(null);
    try {
      const geometry = geometryDrafts[feature.id];
      await updateSurveyFeature(feature.id, geometry ? { ...patch, geometry } : patch);
      const refreshed = await getAnalysisResult(upload.documentId);
      store.setAnalysis(refreshed);
      setGeometryDrafts(current => {
        const next = { ...current };
        delete next[feature.id];
        return next;
      });
      if (patch.review_status === 'rejected') setSelectedFeatureId(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Feature correction could not be saved.');
    } finally {
      setSavingId(null);
    }
  };

  const analysisId = analysis?.analysis_id ?? analysis?.document_id;

  return (
    <section className="card digital-redraw-card animate-fade-in flex flex-col gap-3">
      {/* ── Top Header Toolbar ────────────────────────────────────────── */}
      <header className="redraw-header flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-bold text-lg text-slate-800">Digital Vector Plan</h2>
            <span className={`badge ${coordinateMode === 'survey' ? 'badge-primary' : 'badge-neutral'}`}>
              {coordinateMode === 'survey' ? '📐 Metric Survey Space (Meters)' : '🖼️ Image Pixel Space'}
            </span>
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-800">
              {pixelPlots.length} Plots Vectorized
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Interactive CAD & GIS plan with real-time selection, boundary metrics, and direct export.
          </p>
        </div>

        {/* ── One-Click Direct Export Actions ─────────────────────────── */}
        <div className="flex items-center gap-2">
          {analysisId && (
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg border border-slate-200">
              <span className="text-[11px] font-semibold text-slate-500 px-1 uppercase tracking-wider">Export:</span>
              <a
                href={getExportUrl(analysisId, 'svg')}
                download={`plot_plan_${analysisId}.svg`}
                className="px-2 py-1 text-xs font-medium rounded bg-white text-slate-700 shadow-sm hover:bg-blue-50 hover:text-blue-700 transition"
                title="Download Scalable Vector Graphics"
              >
                SVG
              </a>
              <a
                href={getExportUrl(analysisId, 'dxf')}
                download={`plot_plan_${analysisId}.dxf`}
                className="px-2 py-1 text-xs font-medium rounded bg-white text-slate-700 shadow-sm hover:bg-emerald-50 hover:text-emerald-700 transition"
                title="Download AutoCAD DXF format"
              >
                DXF
              </a>
              <a
                href={getExportUrl(analysisId, 'geojson')}
                download={`plot_plan_${analysisId}.geojson`}
                className="px-2 py-1 text-xs font-medium rounded bg-white text-slate-700 shadow-sm hover:bg-purple-50 hover:text-purple-700 transition"
                title="Download GIS GeoJSON layer"
              >
                GeoJSON
              </a>
              <a
                href={getExportUrl(analysisId, 'pdf')}
                download={`plot_plan_${analysisId}.pdf`}
                className="px-2 py-1 text-xs font-medium rounded bg-white text-slate-700 shadow-sm hover:bg-rose-50 hover:text-rose-700 transition"
                title="Download Architectural PDF Report"
              >
                PDF
              </a>
            </div>
          )}

          {/* Coordinate Space Toggle */}
          {analysis?.calibration?.status !== 'uncalibrated' && analysis?.calibration?.status !== undefined && (
            <div className="flex bg-slate-100 rounded-md p-1">
              <button 
                className={`px-2.5 py-1 text-xs rounded-sm transition ${coordinateMode === 'image' ? 'bg-white shadow text-slate-800 font-medium' : 'text-slate-500 hover:text-slate-800'}`}
                onClick={() => setCoordinateMode('image')}
              >
                Pixels
              </button>
              <button 
                className={`px-2.5 py-1 text-xs rounded-sm transition ${coordinateMode === 'survey' ? 'bg-white shadow text-blue-700 font-medium' : 'text-slate-500 hover:text-slate-800'}`}
                onClick={() => setCoordinateMode('survey')}
              >
                Meters (m)
              </button>
            </div>
          )}

          {/* Zoom controls */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-md border border-slate-200">
            <button className="btn-secondary px-2 py-0.5 text-xs font-bold" aria-label="Zoom out" onClick={() => setZoom(v => Math.max(0.5, v / 1.25))}>−</button>
            <span className="value-mono text-xs min-w-10 text-center font-medium text-slate-700">{Math.round(zoom * 100)}%</span>
            <button className="btn-secondary px-2 py-0.5 text-xs font-bold" aria-label="Zoom in" onClick={() => setZoom(v => Math.min(8, v * 1.25))}>+</button>
            <button className="btn-ghost text-xs px-2 py-0.5 font-medium text-slate-600 hover:text-slate-900" onClick={() => { setZoom(1); setPan([0, 0]); }}>Fit</button>
          </div>
        </div>
      </header>

      {/* ── Search & Filter Controls ──────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-50 p-2 rounded-lg border border-slate-200">
        <div className="flex items-center gap-2 flex-1 min-w-[240px]">
          <div className="relative flex-1">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-xs">🔍</span>
            <input
              type="text"
              placeholder="Search by plot number (e.g. 101, 106) or area..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full pl-7 pr-3 py-1 text-xs rounded border border-slate-300 bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-xs"
              >
                ✕
              </button>
            )}
          </div>

          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as any)}
            className="text-xs py-1 px-2.5 rounded border border-slate-300 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All Statuses ({pixelPlots.length})</option>
            <option value="detected">Detected</option>
            <option value="manual">Manual / Verified</option>
            <option value="uncertain">Needs Review</option>
          </select>
        </div>

        <div className="text-[11px] text-slate-500 font-medium">
          Showing <strong>{filteredPlots.length}</strong> of {pixelPlots.length} plots
        </div>
      </div>

      {/* ── Interactive Plot Quick-Cards Ribbon ──────────────────────── */}
      {pixelPlots.length > 0 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1 pt-0.5 scrollbar-thin">
          {filteredPlots.map(plot => {
            const isSelected = selectedPlot?.id === plot.id;
            const isHovered = hoveredPlotId === plot.id;
            const statedArea = plot.measurements?.stated_area_m2?.value;
            const calcArea = plot.measurements?.calculated_area_m2 ? Math.round(plot.measurements.calculated_area_m2) : null;
            const displayArea = statedArea != null ? `${statedArea} m²` : calcArea != null ? `${calcArea} m²` : 'Area pending';
            return (
              <button
                key={plot.id}
                type="button"
                onClick={() => centerOnPlot(plot)}
                onMouseEnter={() => setHoveredPlotId(plot.id)}
                onMouseLeave={() => setHoveredPlotId(null)}
                className={`flex-shrink-0 text-left px-3 py-1.5 rounded-lg border text-xs transition cursor-pointer ${
                  isSelected
                    ? 'bg-blue-50 border-blue-600 text-blue-900 shadow-sm ring-1 ring-blue-500'
                    : isHovered
                    ? 'bg-slate-50 border-slate-400 text-slate-900'
                    : 'bg-white border-slate-200 text-slate-700 hover:border-slate-300 shadow-2xs'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-900">
                    {plot.plot_number ? `Plot ${plot.plot_number}` : 'Plot ?'}
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.2 rounded font-semibold ${
                    plot.status === 'manual'
                      ? 'bg-emerald-100 text-emerald-800'
                      : plot.status === 'uncertain'
                      ? 'bg-amber-100 text-amber-800'
                      : 'bg-blue-100 text-blue-800'
                  }`}>
                    {plot.status}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  {displayArea}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* ── Main Layout Canvas & Side Inspector ──────────────────────── */}
      <div className="redraw-layout">
        <div className="redraw-main-column">
          <div className="redraw-paper relative rounded-lg border border-slate-200 shadow-inner overflow-hidden">
            {bounds ? (
              <svg
                ref={svgRef}
                className="redraw-svg w-full h-full min-h-[520px] cursor-grab active:cursor-grabbing"
                viewBox={viewBox}
                preserveAspectRatio="xMidYMid meet"
                onPointerDown={event => { if (event.button === 0 && !draggingFeatureId.current) panRef.current = [event.clientX, event.clientY]; }}
                onPointerMove={onPointerMove}
                onPointerUp={() => { panRef.current = null; draggingFeatureId.current = null; }}
                onPointerLeave={() => { panRef.current = null; draggingFeatureId.current = null; }}
                onWheel={event => { event.preventDefault(); setZoom(v => Math.max(0.5, Math.min(8, v * (event.deltaY < 0 ? 1.12 : 0.89)))); }}
                aria-label="Interactive digital survey canvas"
              >
                <FeaturePatterns />
                <rect x={bounds.x} y={bounds.y} width={bounds.width} height={bounds.height} fill="#fffefa" />
                
                {pixelPlots.map(plot => {
                  const coordinates = coordinateMode === 'survey' && plot.geometry?.real_world_coordinates 
                    ? plot.geometry.real_world_coordinates 
                    : plot.geometry?.pixel_coordinates ?? [];
                  const points = coordinates.map(([x, y]) => `${x},${y}`).join(' ');
                  const centroid: Point = [
                    coordinates.reduce((sum, [x]) => sum + x, 0) / (coordinates.length || 1),
                    coordinates.reduce((sum, [, y]) => sum + y, 0) / (coordinates.length || 1),
                  ];
                  const area = plot.measurements?.stated_area_m2;
                  const length = plot.measurements?.length_m;
                  const width = plot.measurements?.width_m;
                  const dimensionParts = [
                    length?.value != null ? String(length.value) : null,
                    width?.value != null ? String(width.value) : null,
                  ].filter((value): value is string => value !== null);
                  const dimensionsLabel = dimensionParts.length
                    ? `${dimensionParts.join(' × ')} ${length?.unit || width?.unit || 'm'}`
                    : null;
                  
                  const isSelected = selectedPlot?.id === plot.id;
                  const isHovered = hoveredPlotId === plot.id;

                  // Highlighting styles
                  const fillColor = isSelected
                    ? '#dbeafe'
                    : isHovered
                    ? '#eff6ff'
                    : plot.status === 'manual'
                    ? '#f0fdf4'
                    : '#fafcff';

                  const strokeColor = isSelected
                    ? '#2563eb'
                    : isHovered
                    ? '#3b82f6'
                    : plot.status === 'manual'
                    ? '#15803d'
                    : '#1d4ed8';

                  const strokeW = isSelected
                    ? markerSize * 0.35
                    : isHovered
                    ? markerSize * 0.28
                    : markerSize * 0.2;

                  return (
                    <g
                      key={plot.id}
                      className="cursor-pointer transition-all"
                      onClick={() => centerOnPlot(plot)}
                      onMouseEnter={() => setHoveredPlotId(plot.id)}
                      onMouseLeave={() => setHoveredPlotId(null)}
                    >
                      <title>{`${plot.plot_number ? `Plot ${plot.plot_number}` : 'Plot'} · ${plot.status} · Click to inspect`}</title>
                      <polygon
                        points={points}
                        fill={fillColor}
                        stroke={strokeColor}
                        strokeWidth={strokeW}
                        strokeDasharray={plot.status === 'uncertain' ? `${markerSize} ${markerSize * 0.55}` : undefined}
                      />
                      {plot.plot_number && (
                        <text
                          x={centroid[0]}
                          y={centroid[1] - markerSize * 0.12}
                          textAnchor="middle"
                          fontSize={markerSize * 1.08}
                          fontWeight="700"
                          fill={isSelected ? '#1e3a8a' : '#0f172a'}
                          stroke="#fffefa"
                          strokeWidth={markerSize * 0.2}
                          paintOrder="stroke"
                        >
                          PLOT {plot.plot_number}
                        </text>
                      )}
                      {dimensionsLabel && (
                        <text
                          x={centroid[0]}
                          y={centroid[1] + markerSize * 1.05}
                          textAnchor="middle"
                          fontSize={markerSize * 0.72}
                          fontWeight="500"
                          fill="#334155"
                          stroke="#fffefa"
                          strokeWidth={markerSize * 0.18}
                          paintOrder="stroke"
                        >
                          {dimensionsLabel}
                        </text>
                      )}
                      {area?.value != null && (
                        <text
                          x={centroid[0]}
                          y={centroid[1] + markerSize * (dimensionsLabel ? 1.9 : 1.05)}
                          textAnchor="middle"
                          fontSize={markerSize * 0.72}
                          fontWeight="600"
                          fill={isSelected ? '#2563eb' : '#475569'}
                          stroke="#fffefa"
                          strokeWidth={markerSize * 0.18}
                          paintOrder="stroke"
                        >
                          {area.value} {area.unit || 'm²'}
                        </text>
                      )}
                    </g>
                  );
                })}

                {visibleFeatures.map(feature => {
                  const renderedFeature = geometryDrafts[feature.id] ? { ...feature, geometry: geometryDrafts[feature.id] } : feature;
                  return (
                    <FeatureRenderer
                      key={feature.id}
                      feature={renderedFeature}
                      markerSize={markerSize}
                      selected={selectedFeatureId === feature.id}
                      onSelect={setSelectedFeatureId}
                      onDragStart={(id, event) => {
                        if (selectedFeatureId !== id || event.button !== 0) return;
                        draggingFeatureId.current = id;
                      }}
                    />
                  );
                })}

                <text
                  x={bounds.x + markerSize * 1.5}
                  y={bounds.y + markerSize * 2.8}
                  fontSize={markerSize * 0.68}
                  letterSpacing={markerSize * 0.1}
                  fill="#64748b"
                  fontWeight="600"
                >
                  DIGITAL REDRAW · {coordinateMode === 'survey' ? 'CALIBRATED METRIC SURVEY SPACE' : 'IMAGE-SPACE EVIDENCE'}
                </text>
              </svg>
            ) : (
              <div className="redraw-empty p-8 text-center text-slate-500">
                <div className="empty-geometry-mark text-3xl mb-2" aria-hidden="true">📐</div>
                <strong className="block text-slate-800 text-sm">No vector geometry available yet</strong>
                <span className="text-xs text-slate-500">Run analysis or upload a layout to view vectorized plots.</span>
              </div>
            )}
          </div>

          {/* Legend and stats */}
          <div className="redraw-legend flex flex-wrap items-center justify-between text-xs text-slate-600 pt-2 border-t mt-2">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5"><i className="legend-plot inline-block w-3 h-3 rounded bg-blue-100 border border-blue-700" /> Plot boundary</span>
              <span className="flex items-center gap-1.5"><i className="legend-anchor inline-block w-3 h-3 rounded bg-amber-100 border border-amber-700" /> Feature label anchor</span>
              <span className="flex items-center gap-1.5"><i className="legend-uncertain inline-block w-3 h-3 rounded border border-dashed border-amber-600" /> Needs review</span>
            </div>
            <div className="text-[11px] text-slate-500 font-medium">
              Click any plot polygon or top card to focus and view boundary specs
            </div>
          </div>
        </div>

        {/* ── Side Inspector ─────────────────────────────────────────── */}
        <aside className="redraw-inspector flex flex-col gap-3">
          <div className="redraw-panel-heading flex items-center justify-between border-b pb-2">
            <div>
              <strong className="text-sm text-slate-800">Observed features</strong>
              <span className="text-xs text-slate-500 block">{visibleFeatures.length} from this survey</span>
            </div>
          </div>

          {visibleFeatures.length ? (
            <div className="redraw-feature-list flex flex-col gap-1 max-h-56 overflow-y-auto">
              {visibleFeatures.map(feature => (
                <button
                  type="button"
                  key={feature.id}
                  className={`redraw-feature-row flex items-center gap-2 p-1.5 rounded text-left transition ${
                    selectedFeatureId === feature.id ? 'bg-blue-50 border border-blue-400' : 'hover:bg-slate-50 border border-transparent'
                  }`}
                  onClick={() => setSelectedFeatureId(feature.id)}
                >
                  <span className={`feature-row-symbol w-6 h-6 flex items-center justify-center rounded text-xs font-bold ${
                    feature.review_required ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'
                  }`}>
                    {featureTypeLabel(feature.feature_type).slice(0, 1)}
                  </span>
                  <span className="feature-row-copy flex-1 text-xs">
                    <strong className="block text-slate-800">{feature.label || featureTypeLabel(feature.feature_type)}</strong>
                    <small className="text-slate-500">{featureTypeLabel(feature.feature_type)} · {feature.source.replaceAll('_', ' ')}</small>
                  </span>
                  <span className={`feature-review-pill text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                    feature.review_status === 'confirmed' ? 'bg-emerald-100 text-emerald-800' : feature.review_required ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'
                  }`}>
                    {feature.review_status === 'confirmed' ? 'confirmed' : feature.review_required ? 'review' : 'observed'}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="redraw-empty-list text-xs text-slate-500 italic">No surrounding-feature labels detected.</p>
          )}

          {/* Selected plot boundary notes */}
          {boundaryNotes.length > 0 && (
            <section className="redraw-boundaries bg-slate-50 p-2.5 rounded-lg border border-slate-200" aria-label="Observed plot boundaries">
              <div className="redraw-boundary-heading text-xs font-bold text-slate-800 mb-1.5 flex items-center justify-between">
                <span>Boundary directions</span>
                <span className="text-[10px] font-normal text-slate-500">for {selectedPlot?.plot_number ? `Plot ${selectedPlot.plot_number}` : 'selected plot'}</span>
              </div>
              <dl className="grid grid-cols-2 gap-1 text-xs">
                {boundaryNotes.map(note => (
                  <div key={note.direction} className="bg-white p-1 rounded border border-slate-200">
                    <dt className="text-[10px] uppercase font-semibold text-slate-400">{note.direction}</dt>
                    <dd className="font-medium text-slate-800">{note.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          {selectedFeature && (
            <FeatureInspector
              key={selectedFeature.id}
              feature={selectedFeature}
              saving={savingId === selectedFeature.id}
              hasGeometryDraft={Boolean(geometryDrafts[selectedFeature.id])}
              onSave={patch => saveFeature(selectedFeature, patch)}
              onReject={() => saveFeature(selectedFeature, { review_status: 'rejected' })}
            />
          )}
          {error && <p className="sidebar-error text-xs text-rose-600 bg-rose-50 p-2 rounded border border-rose-200" role="alert">{error}</p>}
        </aside>
      </div>

      {selectedPlot && (
        <div className="redraw-selected-plot bg-blue-50 border border-blue-200 p-2 rounded-lg text-xs text-blue-900 flex items-center justify-between">
          <div>
            Active Focus: <strong>{selectedPlot.plot_number ? `Plot ${selectedPlot.plot_number}` : selectedPlot.is_target ? 'Target plot' : 'Plot (unidentified)'}</strong>
            {selectedPlot.measurements?.stated_area_m2?.value && (
              <span className="ml-2 font-medium text-blue-700">· Stated Area: {selectedPlot.measurements.stated_area_m2.value} m²</span>
            )}
            {selectedPlot.measurements?.calculated_area_m2 && (
              <span className="ml-2 text-slate-600">· Calculated: {Math.round(selectedPlot.measurements.calculated_area_m2)} m²</span>
            )}
          </div>
          <span className="text-[11px] font-semibold text-blue-700 uppercase tracking-wide">
            Status: {selectedPlot.status}
          </span>
        </div>
      )}
    </section>
  );
}

function FeatureInspector({
  feature,
  saving,
  hasGeometryDraft,
  onSave,
  onReject,
}: {
  feature: SurveyFeature;
  saving: boolean;
  hasGeometryDraft: boolean;
  onSave: (patch: Partial<Pick<SurveyFeature, 'feature_type' | 'label' | 'review_status'>>) => void;
  onReject: () => void;
}) {
  const [featureType, setFeatureType] = useState<SurveyFeatureType>(feature.feature_type);
  const [label, setLabel] = useState(feature.label ?? '');
  return (
    <form className="feature-editor flex flex-col gap-2 bg-slate-50 p-2.5 rounded-lg border border-slate-200" onSubmit={event => {
      event.preventDefault();
      onSave({ feature_type: featureType, label: label.trim() || null, review_status: 'confirmed' });
    }}>
      <div className="feature-editor-title flex items-center justify-between">
        <strong className="text-xs text-slate-800">Review feature</strong>
        <span className="text-[10px] text-slate-500">{feature.review_required ? 'Review required' : 'Evidence recorded'}</span>
      </div>
      <label className="feature-field-label text-[11px] font-medium text-slate-600" htmlFor="redraw-feature-type">Classification</label>
      <select id="redraw-feature-type" className="input text-xs py-1 px-2 rounded border border-slate-300 bg-white" value={featureType} onChange={event => setFeatureType(event.target.value as SurveyFeatureType)}>
        {FEATURE_TYPES.map(type => <option key={type} value={type}>{featureTypeLabel(type)}</option>)}
      </select>
      <label className="feature-field-label text-[11px] font-medium text-slate-600" htmlFor="redraw-feature-label">Survey label</label>
      <input id="redraw-feature-label" className="input text-xs py-1 px-2 rounded border border-slate-300 bg-white" maxLength={1024} value={label} onChange={event => setLabel(event.target.value)} />
      <p className="feature-evidence text-[11px] text-slate-500">Source text: “{feature.evidence_text || 'not available'}”</p>
      <p className="feature-evidence text-[11px] text-slate-500">{feature.geometry?.type === 'Point' ? 'Drag the selected marker on the sheet to correct its image position.' : 'Only explicitly stored geometry is rendered.'}</p>
      {feature.warning && <p className="feature-warning text-xs text-amber-700 bg-amber-50 p-1 rounded" role="status">{feature.warning}</p>}
      {feature.original_type && feature.original_type !== feature.feature_type && <p className="feature-evidence text-[11px] text-slate-500">Original: {featureTypeLabel(feature.original_type as SurveyFeatureType)}</p>}
      {hasGeometryDraft && <p className="feature-warning text-xs text-blue-700 font-medium">Position changed · save to commit.</p>}
      <div className="feature-editor-actions flex items-center gap-2 pt-1">
        <button className="btn-primary text-xs py-1 px-3 rounded bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50" type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save & confirm'}
        </button>
        <button className="btn-ghost text-xs py-1 px-2 text-slate-600 hover:text-slate-800" type="button" onClick={onReject} disabled={saving}>
          Reject feature
        </button>
      </div>
    </form>
  );
}
