import { useAnalysisStore } from '../../store/analysisStore';
import type { ComponentStatus, ComponentStatuses } from '../../types';

const COMPONENTS: { id: keyof ComponentStatuses; label: string; kind: 'core' | 'optional' }[] = [
  { id: 'preprocessing', label: 'Preprocessing', kind: 'core' },
  { id: 'ocr', label: 'OCR and plot labels', kind: 'core' },
  { id: 'opencv', label: 'OpenCV geometry candidates', kind: 'core' },
  { id: 'fusion', label: 'Evidence fusion', kind: 'core' },
  { id: 'annotation', label: 'Annotated preview', kind: 'core' },
  { id: 'llm', label: 'Vision AI', kind: 'optional' },
  { id: 'yolo', label: 'YOLO detector', kind: 'optional' },
];

function statusLabel(status: ComponentStatus | null | undefined): string {
  if (!status) return 'Not reported';
  const labels: Record<ComponentStatus, string> = {
    ok: 'Available',
    running: 'Running',
    failed: 'Failed',
    disabled: 'Disabled',
    not_implemented: 'Not implemented',
    unavailable: 'Unavailable',
    not_configured: 'Not configured',
    no_result: 'No result',
  };
  return labels[status] ?? status.replaceAll('_', ' ');
}

function statusColor(status: ComponentStatus | null | undefined): string {
  if (status === 'ok') return 'var(--success, #10b981)';
  if (status === 'running') return 'var(--accent, #0ea5e9)';
  if (status === 'failed' || status === 'unavailable') return 'var(--error, #ef4444)';
  if (status === 'disabled' || status === 'not_configured' || status === 'no_result') return 'var(--warning, #f59e0b)';
  return 'var(--text-muted)';
}

export default function AnalysisHealthPanel() {
  const { analysis, selectedPlot } = useAnalysisStore();
  if (!analysis) return null;

  const statuses = analysis.components;
  const diagnostics = analysis.component_diagnostics ?? {};
  const knownKeys = new Set(COMPONENTS.map(component => component.id));
  const extraDiagnostics = Object.entries(diagnostics).filter(([key]) => !knownKeys.has(key as keyof ComponentStatuses));
  const identifiedPlots = analysis.plots.filter(plot => !!plot.plot_number).length;
  const geometryCount = analysis.plots.filter(plot => !!plot.geometry?.pixel_coordinates?.length).length;
  const reviewRequired = analysis.plots.filter(plot => plot.status === 'uncertain').length
    + analysis.features.filter(feature => feature.review_required || !!feature.warning).length;
  const targetPlot = analysis.plots.find(plot => plot.is_target);

  return (
    <section className="card p-4 md:p-5 mb-4 space-y-4" aria-label="Analysis run status">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>
              {analysis.status === 'partial' ? 'Analysis completed with required capability gaps' : 'Analysis status'}
            </h2>
            <span className={`badge ${analysis.status === 'partial' ? 'badge-warning' : analysis.status === 'failed' ? 'badge-error' : 'badge-success'}`}>
              {analysis.status}
            </span>
          </div>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            {analysis.document_name || 'Document name unavailable'} · {identifiedPlots} identified plot labels · {analysis.plots.length} plot records · {analysis.features.length} feature records · {analysis.ocr_results.length} OCR tokens
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            {geometryCount} plot boundaries associated · {reviewRequired} item{reviewRequired === 1 ? '' : 's'} need review
          </p>
        </div>
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          Target: {targetPlot?.plot_number ? `Plot ${targetPlot.plot_number}` : 'Target plot not identified'}
          {selectedPlot && !selectedPlot.is_target && selectedPlot.plot_number && ` · active plot: ${selectedPlot.plot_number}`}
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {COMPONENTS.map(component => {
          const status = statuses?.[component.id];
          const detail = diagnostics[component.id];
          return (
            <div key={component.id} className="rounded-lg p-3 min-w-0" style={{ background: 'var(--bg-elevated)' }}>
              <div className="flex items-start justify-between gap-2">
                <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{component.label}</span>
                <span className="text-xs capitalize whitespace-nowrap" style={{ color: statusColor(status) }}>{statusLabel(status)}</span>
              </div>
              <div className="text-[10px] mt-1 uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                {component.kind === 'core' ? 'Core analysis capability' : 'Optional component'}
              </div>
              {detail && <p className="text-xs mt-2 break-words" style={{ color: 'var(--text-secondary)' }}>{detail}</p>}
            </div>
          );
        })}
      </div>

      {extraDiagnostics.length > 0 && (
        <div className="space-y-2" role="status">
          {extraDiagnostics.map(([key, detail]) => (
            <p key={key} className="text-xs" style={{ color: 'var(--warning, #f59e0b)' }}>
              {key.replaceAll('_', ' ')}: {detail}
            </p>
          ))}
        </div>
      )}

      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        Missing geometry or measurements remain unknown; optional service gaps do not prevent the other analysis stages from running.
      </p>
    </section>
  );
}
