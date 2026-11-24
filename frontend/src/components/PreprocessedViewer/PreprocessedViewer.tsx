import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';

export default function PreprocessedViewer() {
  const { analysis } = useAnalysisStore();
  const src = analysis?.images?.preprocessed_url ?? null;
  const [zoom, setZoom] = useState(1);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const loadError = src !== null && failedSrc === src;

  return (
    <section className="card p-4 space-y-3 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>Preprocessed analysis image</h2>
            <span className="badge badge-neutral">Debug view</span>
          </div>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Contrast-normalized input used by OCR and computer vision. This is not the annotated preview or the final digital redraw.
          </p>
        </div>
        {src && !loadError && (
          <div className="flex items-center gap-1">
            <button className="btn-ghost" aria-label="Zoom out" onClick={() => setZoom(value => Math.max(.25, value / 1.25))}>−</button>
            <span className="value-mono text-xs min-w-10 text-center">{Math.round(zoom * 100)}%</span>
            <button className="btn-ghost" aria-label="Zoom in" onClick={() => setZoom(value => Math.min(4, value * 1.25))}>+</button>
            <button className="btn-ghost text-xs" onClick={() => setZoom(1)}>Fit</button>
          </div>
        )}
      </div>
      {src && !loadError ? (
        <div className="source-image-frame">
          <img
            key={src}
            src={src}
            alt="Preprocessed survey image used for OCR and computer-vision analysis"
            draggable={false}
            onError={() => setFailedSrc(src)}
            style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
          />
        </div>
      ) : (
        <div className="image-empty-state" role="status">
          <span aria-hidden="true">◧</span>
          <p>{loadError ? 'The preprocessed analysis image could not be loaded.' : 'No preprocessing output was returned for this analysis.'}</p>
        </div>
      )}
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        The Digital Redraw is a separate SVG built from the returned plot geometry and feature observations.
      </p>
    </section>
  );
}
