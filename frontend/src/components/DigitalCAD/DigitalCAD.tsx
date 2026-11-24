/** Coordinate view for returned plots and explicit image-space feature geometry. */

import { useRef, useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';
import type { FeatureGeometry, Plot } from '../../types';
import FeatureRenderer, { FeaturePatterns } from '../DigitalRedraw/FeatureRenderer';

type Point = [number, number];

function featurePoints(geometry: FeatureGeometry | null | undefined): Point[] {
  if (!geometry || geometry.coordinate_space !== 'image_pixels') return [];
  if (geometry.type === 'Point') return [geometry.coordinates as Point];
  if (geometry.type === 'LineString') return geometry.coordinates as Point[];
  return (geometry.coordinates as Point[][]).flat();
}

function plotCentroid(points: Point[]): Point {
  return [
    points.reduce((sum, [x]) => sum + x, 0) / points.length,
    points.reduce((sum, [, y]) => sum + y, 0) / points.length,
  ];
}

function PlotLabel({ plot, coordinates, markerSize }: { plot: Plot; coordinates: Point[]; markerSize: number }) {
  if (coordinates.length < 3) return null;
  const [x, y] = plotCentroid(coordinates);
  const dimensions = [plot.measurements?.length_m, plot.measurements?.width_m]
    .filter(value => value?.value != null)
    .map(value => String(value!.value));
  const area = plot.measurements?.stated_area_m2;
  return (
    <g pointerEvents="none">
      {plot.plot_number && (
        <text x={x} y={y - markerSize * 0.25} textAnchor="middle" fontSize={markerSize * 1.05} fontWeight="700" fill="#0f172a" stroke="#fffefa" strokeWidth={markerSize * 0.2} paintOrder="stroke">
          PLOT {plot.plot_number}
        </text>
      )}
      {dimensions.length > 0 && (
        <text x={x} y={y + markerSize * 0.8} textAnchor="middle" fontSize={markerSize * 0.62} fill="#334155" stroke="#fffefa" strokeWidth={markerSize * 0.18} paintOrder="stroke">
          {dimensions.join(' × ')} {plot.measurements?.length_m?.unit || plot.measurements?.width_m?.unit || 'm'}
        </text>
      )}
      {area?.value != null && (
        <text x={x} y={y + markerSize * (dimensions.length > 0 ? 1.55 : 0.8)} textAnchor="middle" fontSize={markerSize * 0.62} fill="#334155" stroke="#fffefa" strokeWidth={markerSize * 0.18} paintOrder="stroke">
          Stated area {area.value} {area.unit || 'm²'}
        </text>
      )}
    </g>
  );
}

export default function DigitalCAD() {
  const { analysis, selectedPlot } = useAnalysisStore();
  const viewIdentity = JSON.stringify([
    analysis?.analysis_id,
    analysis?.plots.map(plot => [plot.id, plot.geometry?.pixel_coordinates, plot.geometry?.real_world_coordinates]),
    analysis?.features.map(feature => [feature.id, feature.geometry, feature.review_status]),
    selectedPlot?.id,
  ]);
  return <DigitalCADCanvas key={viewIdentity} />;
}

function DigitalCADCanvas() {
  const { analysis, selectedPlot, setActiveTab } = useAnalysisStore();
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>([0, 0]);
  const plots = analysis?.plots ?? [];
  const features = (analysis?.features ?? []).filter(feature => feature.review_status !== 'rejected');
  const pixelPlots = plots.filter(plot => (plot.geometry?.pixel_coordinates?.length ?? 0) >= 3);
  const pixelFeatures = features.filter(feature => feature.geometry?.coordinate_space === 'image_pixels');
  const pageSpace = pixelPlots.length > 0 || pixelFeatures.some(feature => featurePoints(feature.geometry).length > 0);
  const geometry = selectedPlot?.geometry ?? null;
  const world = !pageSpace && (geometry?.real_world_coordinates?.length ?? 0) >= 3;
  const worldCoords = world ? geometry?.real_world_coordinates ?? [] : [];
  const viewPlots = pageSpace ? pixelPlots : world ? [] : pixelPlots.filter(plot => plot.id === selectedPlot?.id);
  const viewFeatures = pageSpace ? pixelFeatures : [];
  const selectedPixelCoords = selectedPlot?.geometry?.pixel_coordinates ?? [];
  const localCoords = worldCoords.length ? worldCoords : selectedPixelCoords;
  const coordinateGroups = pageSpace
    ? [
        ...viewPlots.map(plot => plot.geometry?.pixel_coordinates ?? []),
        ...viewFeatures.map(feature => featurePoints(feature.geometry)),
      ]
    : [localCoords];
  const allPoints = coordinateGroups.flat().filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));

  const bounds = (() => {
    if (!allPoints.length) return null;
    const xs = allPoints.map(([x]) => x);
    const ys = allPoints.map(([, y]) => y);
    const width = Math.max(...xs) - Math.min(...xs) || 1;
    const height = Math.max(...ys) - Math.min(...ys) || 1;
    const pad = Math.max(width, height) * 0.14;
    return { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, width: width + pad * 2, height: height + pad * 2 };
  })();

  const viewBox = bounds
    ? `${bounds.x + pan[0] + bounds.width * (1 - 1 / zoom) / 2} ${bounds.y + pan[1] + bounds.height * (1 - 1 / zoom) / 2} ${bounds.width / zoom} ${bounds.height / zoom}`
    : '0 0 100 100';
  const markerSize = bounds ? Math.max(Math.max(bounds.width, bounds.height) * 0.018, 5) : 8;
  const boundaries = selectedPlot?.boundaries;
  const northAngle = boundaries?.north_arrow_detected && boundaries.north_arrow_angle_deg != null
    ? boundaries.north_arrow_angle_deg : null;
  const northLength = bounds ? Math.min(bounds.width, bounds.height) * 0.08 : 0;
  const northOrigin: Point = bounds ? [bounds.x + bounds.width * 0.9, bounds.y + bounds.height * 0.15] : [0, 0];
  const northRadians = northAngle == null ? 0 : northAngle * Math.PI / 180;
  const northTip: Point = [northOrigin[0] + Math.sin(northRadians) * northLength, northOrigin[1] - Math.cos(northRadians) * northLength];

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current || !bounds || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const current = { x: event.clientX, y: event.clientY };
    const dx = current.x - dragRef.current.x;
    const dy = current.y - dragRef.current.y;
    setPan(([x, y]) => [x - dx * (bounds.width / zoom) / rect.width, y - dy * (bounds.height / zoom) / rect.height]);
    dragRef.current = current;
  };

  return (
    <section className="card p-4 md:p-5 space-y-4 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>CAD layout</h2>
            <span className={`badge ${world ? 'badge-primary' : 'badge-neutral'}`}>
              Coordinate mode: {world ? 'LOCAL SURVEY SPACE - METERS' : 'IMAGE SPACE'}
            </span>
            {pageSpace && <span className="badge badge-info">Shared survey coordinates</span>}
          </div>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            {pageSpace
              ? 'Plots and explicit feature geometry retain their observed relative positions in the source image.'
              : world
              ? 'This is a single-plot dimension-based view; neighboring plot positions are not established.'
              : 'Image-space plot geometry is shown when available. Unobserved roads, features and north direction are not added.'}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button className="btn-secondary px-2 py-1" aria-label="Zoom out" onClick={() => setZoom(z => Math.max(0.5, z / 1.25))}>−</button>
          <span className="value-mono text-xs min-w-12 text-center">{Math.round(zoom * 100)}%</span>
          <button className="btn-secondary px-2 py-1" aria-label="Zoom in" onClick={() => setZoom(z => Math.min(8, z * 1.25))}>+</button>
          <button className="btn-ghost text-xs" onClick={() => { setZoom(1); setPan([0, 0]); }}>Fit</button>
        </div>
      </div>

      <div className="cad-canvas relative overflow-hidden rounded-xl">
        {bounds ? (
          <svg
            ref={svgRef}
            className="w-full h-full touch-none"
            viewBox={viewBox}
            preserveAspectRatio="xMidYMid meet"
            onPointerDown={event => { if (event.button === 0) dragRef.current = { x: event.clientX, y: event.clientY }; }}
            onPointerMove={onPointerMove}
            onPointerUp={() => { dragRef.current = null; }}
            onPointerLeave={() => { dragRef.current = null; }}
            onWheel={event => { event.preventDefault(); setZoom(z => Math.max(0.5, Math.min(8, z * (event.deltaY < 0 ? 1.12 : 0.89)))); }}
            aria-label="CAD coordinate view; drag to pan and use the wheel to zoom"
          >
            <defs>
              <pattern id="cad-grid" width={Math.max(bounds.width / 24, 1)} height={Math.max(bounds.height / 18, 1)} patternUnits="userSpaceOnUse">
                <path d={`M ${Math.max(bounds.width / 24, 1)} 0 L 0 0 0 ${Math.max(bounds.height / 18, 1)}`} fill="none" stroke="rgba(148,163,184,.2)" strokeWidth={Math.max(bounds.width / 1000, 0.25)} />
              </pattern>
              <linearGradient id="cad-plot-fill" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0" stopColor="#38bdf8" stopOpacity=".16" />
                <stop offset="1" stopColor="#818cf8" stopOpacity=".06" />
              </linearGradient>
              <marker id="cad-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth={markerSize} markerHeight={markerSize} markerUnits="userSpaceOnUse" orient="auto">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a" />
              </marker>
            </defs>
            {pageSpace && <FeaturePatterns />}
            <rect x={bounds.x} y={bounds.y} width={bounds.width} height={bounds.height} fill="url(#cad-grid)" />
            {pageSpace ? viewPlots.map(plot => {
              const points = plot.geometry?.pixel_coordinates ?? [];
              const selected = plot.id === selectedPlot?.id;
              return <g key={plot.id}>
                <title>{plot.plot_number ? `Plot ${plot.plot_number}` : plot.is_target ? 'Target plot not identified' : 'Plot identity not detected'} · {plot.status}</title>
                <polygon points={points.map(([x, y]) => `${x},${y}`).join(' ')} fill="url(#cad-plot-fill)" stroke={selected ? '#f97316' : '#2563eb'} strokeWidth={markerSize * (selected ? 0.27 : 0.19)} strokeDasharray={plot.status === 'uncertain' ? `${markerSize} ${markerSize * 0.55}` : undefined} strokeLinejoin="round" />
                <PlotLabel plot={plot} coordinates={points} markerSize={markerSize} />
              </g>;
            }) : localCoords.length >= 3 && (
              <g>
                <polygon points={localCoords.map(([x, y]) => `${x},${y}`).join(' ')} fill="url(#cad-plot-fill)" stroke="#38bdf8" strokeWidth={markerSize * 0.22} strokeLinejoin="round" />
                {selectedPlot?.plot_number && <PlotLabel plot={selectedPlot} coordinates={localCoords} markerSize={markerSize} />}
              </g>
            )}
            {pageSpace && viewFeatures.map(feature => (
              <FeatureRenderer key={feature.id} feature={feature} markerSize={markerSize} selected={false} onSelect={() => undefined} />
            ))}
            {pageSpace && northAngle != null && (
              <g aria-label="Detected north direction">
                <path d={`M ${northOrigin[0]} ${northOrigin[1]} L ${northTip[0]} ${northTip[1]}`} stroke="#0f172a" strokeWidth={markerSize * 0.18} markerEnd="url(#cad-arrow)" />
                <text x={northTip[0]} y={northTip[1] - markerSize * 0.4} textAnchor="middle" fontSize={markerSize} fontWeight="700" fill="#0f172a">N</text>
              </g>
            )}
          </svg>
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-5 text-center">
            <div className="empty-geometry-mark" aria-hidden="true">⌁</div>
            <div>
              <p className="font-medium text-sm" style={{ color: 'var(--text-primary)' }}>No reliable plot geometry or positioned features</p>
              <p className="text-xs mt-1 max-w-sm" style={{ color: 'var(--text-muted)' }}>
                No boundary or feature extent is drawn. Trace and save a boundary from the original survey when appropriate.
              </p>
            </div>
            <button className="btn-primary" onClick={() => setActiveTab('correction')}>Edit boundary</button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        <span>{pageSpace ? `${viewPlots.length} plot polygon${viewPlots.length === 1 ? '' : 's'} · ${viewFeatures.length} feature observations` : bounds ? `${localCoords.length} vertices · ${world ? 'single-plot real-world coordinates' : 'image coordinates'}` : 'No coordinates available'}</span>
        <span>{pageSpace ? 'Patterns fill only explicitly stored feature extents.' : geometry?.confidence != null ? `Evidence support ${Math.round(geometry.confidence * 100)}%` : 'No geometry confidence score'}</span>
      </div>
      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
        North direction: {northAngle == null ? 'not identified' : pageSpace ? `observed at ${northAngle}° from the survey data` : `angle observed (${northAngle}°), but no shared page coordinates are available to draw it`} · Feature markers may be text anchors; they do not imply a full feature footprint.
      </div>

      {boundaries && Object.values(boundaries).some(value => value && typeof value === 'object' && 'value' in value && value.value) && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {(['north', 'south', 'east', 'west'] as const).map(direction => {
            const item = boundaries[direction];
            return item?.value ? <div key={direction} className="boundary-chip"><span>{direction}</span><strong>{item.value}</strong></div> : null;
          })}
        </div>
      )}
      {selectedPlot?.id && (
        <div className="flex flex-wrap gap-2 border-t pt-3" style={{ borderColor: 'var(--border-subtle)' }}>
          <a className="btn-ghost text-xs" href={`/api/export/${selectedPlot.id}/geojson`}>Export GeoJSON</a>
          <a className="btn-ghost text-xs" href={`/api/export/${selectedPlot.id}/svg`}>Export SVG</a>
          <a className="btn-ghost text-xs" href={`/api/export/${selectedPlot.id}/report`}>Download report</a>
        </div>
      )}
    </section>
  );
}
