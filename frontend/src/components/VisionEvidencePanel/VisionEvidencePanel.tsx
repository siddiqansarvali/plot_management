import { useAnalysisStore } from '../../store/analysisStore';

type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonObject
    : null;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function display(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
}

export default function VisionEvidencePanel() {
  const { analysis } = useAnalysisStore();
  if (!analysis) return null;

  let vision: JsonObject | null = null;
  try {
    vision = analysis.llm_raw_response ? asObject(JSON.parse(analysis.llm_raw_response)) : null;
  } catch {
    vision = null;
  }

  const plots = asList(vision?.plots);
  const features = asList(vision?.features);
  const dimensionSummary = asObject(vision?.dimensions);
  const dimensions = asList(dimensionSummary?.observations);
  const uncertainty = asList(vision?.uncertain_items).filter((item): item is string => typeof item === 'string');
  const target = asObject(vision?.target_plot);
  const northArrow = asObject(vision?.north_arrow);
  const model = display(vision?.model);
  const status = analysis.components?.llm;
  const diagnostic = analysis.component_diagnostics?.llm;

  return (
    <section className="space-y-3 border-t pt-4" style={{ borderColor: 'var(--border-subtle)' }} aria-label="Vision observations">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>Vision observations</h4>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Semantic evidence for review. Vision does not create or position geometry.
          </p>
        </div>
        <span className="badge badge-neutral">{status?.replaceAll('_', ' ') ?? 'not reported'}</span>
      </div>

      {diagnostic && !vision && (
        <p className="text-xs" role="status" style={{ color: 'var(--text-secondary)' }}>{diagnostic}</p>
      )}

      {vision && (
        <>
          {model && <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Model: {model}</p>}
          {display(target?.plot_number) && (
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Target label reported by Vision: <strong>{display(target?.plot_number)}</strong> · corroboration is checked against OCR before fusion.
            </p>
          )}

          {plots.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Visible plot observations</p>
              {plots.map((entry, index) => {
                const plot = asObject(entry);
                if (!plot) return null;
                const number = display(plot.plot_number) ?? 'Plot number unknown';
                const confidence = typeof plot.label_confidence === 'number' ? ` · ${Math.round(plot.label_confidence * 100)}% model confidence` : '';
                return <p key={`${number}-${index}`} className="text-xs" style={{ color: 'var(--text-muted)' }}>{number}{confidence}</p>;
              })}
            </div>
          )}

          {dimensions.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Dimension observations</p>
              {dimensions.map((entry, index) => {
                const item = asObject(entry);
                if (!item) return null;
                const text = display(item.text) ?? [display(item.value), display(item.unit)].filter(Boolean).join(' ');
                return text ? <p key={`${text}-${index}`} className="text-xs" style={{ color: 'var(--text-muted)' }}>{text}</p> : null;
              })}
            </div>
          )}

          {features.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Feature observations · location not used as geometry</p>
              {features.map((entry, index) => {
                const feature = asObject(entry);
                if (!feature) return null;
                const label = display(feature.label) ?? display(feature.type) ?? 'Unclassified feature';
                const location = display(feature.location_description);
                return <p key={`${label}-${index}`} className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {label}{location ? ` · ${location}` : ''}
                </p>;
              })}
            </div>
          )}

          {northArrow?.detected === true && (
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Vision reports a visible north arrow. It is drawn only when an explicit orientation is available.</p>
          )}

          {uncertainty.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium" style={{ color: 'var(--warning, #f59e0b)' }}>Needs review</p>
              {uncertainty.map((item, index) => <p key={`${item}-${index}`} className="text-xs" style={{ color: 'var(--text-secondary)' }}>{item}</p>)}
            </div>
          )}

          {plots.length === 0 && features.length === 0 && dimensions.length === 0 && uncertainty.length === 0 && (
            <p className="text-xs null-indicator">Vision returned no confident plot, feature, or dimension observations.</p>
          )}
        </>
      )}

      {!vision && !diagnostic && status !== 'running' && (
        <p className="text-xs null-indicator">No structured Vision response is available for this analysis.</p>
      )}
    </section>
  );
}
