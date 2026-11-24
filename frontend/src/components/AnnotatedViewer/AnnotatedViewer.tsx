import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';

export default function AnnotatedViewer() {
  const { analysis, selectedPlot } = useAnalysisStore();
  const [zoom, setZoom] = useState(1);
  const [imageSize, setImageSize] = useState<[number, number] | null>(null);
  const src = analysis?.images?.annotated_url ?? null;
  const polygon = selectedPlot?.geometry?.pixel_coordinates;
  const hasPolygon = !!polygon && polygon.length >= 3 && polygon.every(point =>
    point.length >= 2 && point.every(Number.isFinite),
  );
  return (
    <section className="card p-4 space-y-3 animate-fade-in">
      <div className="flex items-center justify-between gap-3">
        <div>
            <h2 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>Annotated preview</h2>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Detected OCR, candidate contours, structured plot boundaries, and observed feature-label anchors on an image copy</p>
        </div>
        {src && <div className="flex items-center gap-1">
          <button className="btn-ghost" aria-label="Zoom out" onClick={() => setZoom(value => Math.max(.25, value / 1.25))}>−</button>
          <span className="value-mono text-xs min-w-10 text-center">{Math.round(zoom * 100)}%</span>
          <button className="btn-ghost" aria-label="Zoom in" onClick={() => setZoom(value => Math.min(4, value * 1.25))}>+</button>
          <button className="btn-ghost text-xs" onClick={() => setZoom(1)}>Fit</button>
        </div>}
      </div>
      {src ? (
        <div className="source-image-frame">
          <div className="annotated-image-stage" style={{ transform: `scale(${zoom})` }}>
            <img src={src} alt="Computational evidence annotations" draggable={false}
                 onLoad={event => setImageSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])} />
            {imageSize && hasPolygon && (
              <svg className="annotated-selected-overlay" viewBox={`0 0 ${imageSize[0]} ${imageSize[1]}`} preserveAspectRatio="none" aria-hidden="true">
                <polygon
                  points={polygon.map(([x, y]) => `${x},${y}`).join(' ')}
                  fill="rgba(34,197,94,0.12)"
                  stroke="#22c55e"
                  strokeWidth={Math.max(imageSize[0], imageSize[1]) / 500}
                  vectorEffect="non-scaling-stroke"
                >
                  <title>{selectedPlot?.plot_number ? `Selected plot ${selectedPlot.plot_number}` : 'Selected plot boundary'}</title>
                </polygon>
              </svg>
            )}
          </div>
        </div>
      ) : (
        <div className="image-empty-state">
          <span aria-hidden="true">◎</span>
          <p>{analysis?.components?.annotation === 'failed' ? 'The evidence overlay could not be generated.' : 'Evidence overlay is not available yet.'}</p>
        </div>
      )}
      <div className="legend-row">
        <span><i className="legend-cyan" /> OCR regions</span>
        <span><i className="legend-amber" /> Geometry candidates</span>
        <span><i className="legend-green" /> Accepted plot boundary</span>
        <span><i className="legend-plot-boundary" /> Active plot highlight</span>
        <span><i className="legend-feature-anchor" /> Feature label anchor</span>
      </div>
    </section>
  );
}
