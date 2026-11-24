/**
 * Analysis Progress — shown while the pipeline is running.
 * Displays component-level status as they become available.
 */

import { useAnalysisStore } from '../../store/analysisStore';
import type { ComponentStatus } from '../../types';

function StatusIcon({ status }: { status: ComponentStatus | null | undefined }) {
  if (!status) return <span className="status-dot" style={{ background: 'var(--text-muted)' }} />;
  if (status === 'ok') return <span className="status-dot status-dot-ok" />;
  if (status === 'failed' || status === 'unavailable') return <span className="status-dot status-dot-failed" />;
  if (status === 'disabled' || status === 'not_configured') return <span className="status-dot status-dot-disabled" />;
  return <span className="status-dot status-dot-pending" />;
}

function StatusLabel({ status }: { status: ComponentStatus | null | undefined }) {
  const map: Record<string, string> = {
    ok: 'Complete',
    failed: 'Failed (non-fatal)',
    disabled: 'Disabled',
    unavailable: 'Unavailable',
    not_configured: 'Not configured',
    not_implemented: 'Pending',
  };
  return <span>{status ? (map[status] ?? status) : '—'}</span>;
}

const PIPELINE_STEPS = [
  { key: 'preprocessing', label: 'Prepare image copy', phase: 'Image' },
  { key: 'ocr',           label: 'Read visible text', phase: 'OCR' },
  { key: 'llm',           label: 'Interpret semantics', phase: 'Vision' },
  { key: 'opencv',        label: 'Find boundary candidates', phase: 'Geometry' },
  { key: 'yolo',          label: 'Survey object model', phase: 'Optional' },
  { key: 'fusion',        label: 'Compare evidence', phase: 'Fusion' },
  { key: 'annotation',    label: 'Create evidence preview', phase: 'Output' },
];

export default function AnalysisProgress() {
  const { phase, analysis } = useAnalysisStore();
  const components = analysis?.components;

  return (
    <div className="card p-6 space-y-6 animate-fade-in max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full flex items-center justify-center"
             style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.3)' }}>
          <svg className="animate-spin-slow" width="20" height="20" viewBox="0 0 24 24"
               fill="none" stroke="#0ea5e9" strokeWidth="2">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4"
                  strokeLinecap="round"/>
          </svg>
        </div>
        <div>
          <h3 className="font-semibold" style={{ color: 'var(--text-primary)' }}>
            {phase === 'uploading' ? 'Uploading Image…' : 'Analyzing Survey…'}
          </h3>
          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {phase === 'uploading'
              ? 'Saving your survey image securely'
              : 'Running OCR, computer vision, and AI analysis'}
          </p>
        </div>
      </div>

      {/* Pipeline steps */}
      {phase === 'analyzing' && (
        <div className="space-y-2">
          <p className="section-header">Pipeline Status</p>
          {PIPELINE_STEPS.map(step => {
            const status = components?.[step.key as keyof typeof components];
            return (
              <div key={step.key}
                   className="flex items-center justify-between py-2 px-3 rounded-lg"
                   style={{ background: 'var(--bg-elevated)' }}>
                <div className="flex items-center gap-2">
                  <StatusIcon status={status} />
                  <span className="text-sm" style={{ color: 'var(--text-primary)' }}>
                    {step.label}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {step.phase}
                  </span>
                </div>
                <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  <StatusLabel status={status} />
                </span>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-center" style={{ color: 'var(--text-muted)' }}>
        OCR model startup may take longer on the first analysis. Optional services can be unavailable without stopping other stages.
      </p>
    </div>
  );
}
