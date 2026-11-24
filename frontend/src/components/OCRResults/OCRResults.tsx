/**
 * OCR Results — displays all extracted text tokens with positions and confidence.
 */

import { useAnalysisStore } from '../../store/analysisStore';
import VisionEvidencePanel from '../VisionEvidencePanel/VisionEvidencePanel';

const CATEGORY_COLORS: Record<string, string> = {
  plot_number:   '#0ea5e9',
  dimension:     '#10b981',
  area:          '#f59e0b',
  boundary_label:'#6366f1',
  road:          '#94a3b8',
  forest:        '#22c55e',
  note:          '#64748b',
  unknown:       '#475569',
};

export default function OCRResults() {
  const { analysis } = useAnalysisStore();
  const results = analysis?.ocr_results ?? [];

  if (!analysis) return null;

  return (
    <div className="card p-6 space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold" style={{ color: 'var(--text-primary)' }}>
          OCR Extracted Text
        </h3>
        <span className="badge badge-info">{results.length} tokens</span>
      </div>

      <VisionEvidencePanel />

      {results.length === 0 ? (
        <div className="text-center py-8 space-y-2" role="status">
          <p className="null-indicator">
            {analysis.components?.ocr === 'disabled'
              ? 'OCR is disabled in backend configuration.'
              : analysis.components?.ocr === 'failed'
              ? 'OCR unavailable in the current backend environment.'
              : 'No text was recognized in this image.'}
          </p>
          {analysis.component_diagnostics?.ocr && (
            <p className="text-xs max-w-2xl mx-auto" style={{ color: 'var(--text-secondary)' }}>
              {analysis.component_diagnostics.ocr}
            </p>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <div className="min-w-[820px] space-y-2">
            <div className="grid grid-cols-12 gap-2 text-xs font-medium pb-2 border-b"
                 style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}>
              <div className="col-span-4">Text</div>
              <div className="col-span-2">Confidence</div>
              <div className="col-span-2">Category</div>
              <div className="col-span-2">Center · px</div>
              <div className="col-span-2">Bounding box · px</div>
            </div>
            {results.map(r => (
              <div key={r.id} className="grid grid-cols-12 gap-2 py-2 rounded-lg px-2 items-center"
                   style={{ background: 'var(--bg-elevated)' }}>
                <div className="col-span-4 font-mono text-sm truncate" style={{ color: 'var(--accent-hover)' }} title={r.text}>
                  {r.text}
                </div>
                <div className="col-span-2">
                  <div className="confidence-bar w-full">
                    <div className="confidence-fill" style={{ width: `${Math.round(r.confidence * 100)}%` }} />
                  </div>
                  <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                    {Math.round(r.confidence * 100)}%
                  </div>
                </div>
                <div className="col-span-2">
                  {r.category ? (
                    <span className="badge text-xs"
                          style={{
                            background: `${CATEGORY_COLORS[r.category] ?? '#475569'}22`,
                            color: CATEGORY_COLORS[r.category] ?? '#475569'
                          }}>
                      {r.category.replace('_', ' ')}
                    </span>
                  ) : (
                    <span className="null-indicator">unclassified</span>
                  )}
                </div>
                <div className="col-span-2 text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                  ({Math.round(r.center[0])}, {Math.round(r.center[1])})
                </div>
                <div className="col-span-2 text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                  [{r.bbox.map(value => Math.round(value)).join(', ')}]
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
