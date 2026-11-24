/**
 * Confidence Panel — displays confidence breakdown by component.
 */

import { useAnalysisStore } from '../../store/analysisStore';

function ConfidenceBar({ value, label }: { value: number | null | undefined; label: string }) {
  const pct = value != null ? Math.round(value * 100) : null;
  const color = pct == null ? '#475569'
    : pct >= 75 ? '#10b981'
    : pct >= 50 ? '#f59e0b'
    : '#ef4444';

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
        <span style={{ color }}>{pct != null ? `${pct}%` : 'Unavailable'}</span>
      </div>
      {pct != null && <div className="confidence-bar">
        <div className="confidence-fill transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
      </div>}
    </div>
  );
}

export default function ConfidencePanel() {
  const { analysis, selectedPlot } = useAnalysisStore();
  const conf = analysis?.confidence;
  const hasEvidence = !!conf && [conf.overall, conf.ocr, conf.llm, conf.opencv, conf.geometry, conf.validation]
    .some(value => value != null);

  return (
    <div className="card p-4 space-y-4 animate-fade-in">
      <p className="section-header">Evidence support</p>

      {/* Overall */}
      {conf?.overall != null && (
        <div className="p-4 rounded-xl text-center"
             style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)' }}>
          <div className="text-4xl font-bold value-mono">
            {Math.round(conf.overall * 100)}%
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Rule-based support score</div>
        </div>
      )}

      {!hasEvidence && <p className="null-indicator text-center py-2">There is not enough evidence to calculate a support score.</p>}

      {/* Per-component */}
      {conf && (
        <div className="space-y-3">
          <ConfidenceBar value={conf.ocr}        label="OCR" />
          <ConfidenceBar value={conf.llm}        label="Vision LLM" />
          <ConfidenceBar value={conf.opencv}     label="OpenCV Geometry" />
          <ConfidenceBar value={conf.geometry}   label="Geometry Quality" />
          <ConfidenceBar value={conf.validation} label="Validation" />
        </div>
      )}

      {/* Plot-level */}
      {selectedPlot?.confidence_overall != null && (
        <div>
          <ConfidenceBar
            value={selectedPlot.confidence_overall}
            label="Plot-Level Confidence"
          />
        </div>
      )}

      <div className="divider" />
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        Scores summarize model output or evidence agreement. They are not calibrated probabilities and do not represent professional surveying accuracy.
      </p>
    </div>
  );
}
