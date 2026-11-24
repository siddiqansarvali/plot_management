import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';

export default function OriginalViewer() {
  const { analysis } = useAnalysisStore();
  const [zoom, setZoom] = useState(1);
  const [dimensions, setDimensions] = useState<[number, number] | null>(null);
  const src = analysis?.images?.original_url ?? null;
  if (!src) return null;

  return (
    <section className="card p-4 space-y-3 animate-fade-in">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>Source survey</h2>
          {dimensions && <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{dimensions[0]} × {dimensions[1]} px · original preserved</p>}
        </div>
        <div className="flex items-center gap-1">
          <button className="btn-ghost" aria-label="Zoom out" onClick={() => setZoom(value => Math.max(.25, value / 1.25))}>−</button>
          <span className="value-mono text-xs min-w-10 text-center">{Math.round(zoom * 100)}%</span>
          <button className="btn-ghost" aria-label="Zoom in" onClick={() => setZoom(value => Math.min(4, value * 1.25))}>+</button>
          <button className="btn-ghost text-xs" onClick={() => setZoom(1)}>Fit</button>
        </div>
      </div>
      <div className="source-image-frame">
        <img
          key={src}
          src={src}
          alt="Unmodified uploaded survey"
          draggable={false}
          onLoad={event => setDimensions([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])}
          style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
        />
      </div>
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>The analysis never edits this source image.</p>
    </section>
  );
}
