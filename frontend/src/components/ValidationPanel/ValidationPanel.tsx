/** Evidence-based checks for the active plot, or a survey-wide review list. */

import { useAnalysisStore } from '../../store/analysisStore';

type TopologyEntry = { status?: string; plots?: string[]; reason?: string };

function topologyEntry(value: unknown): TopologyEntry | null {
  return value && typeof value === 'object' ? value as TopologyEntry : null;
}

function checkBadge(value: string | null | undefined) {
  if (value === 'pass' || value === 'valid') return <span className="badge badge-success text-xs">✓ Pass</span>;
  if (value === 'fail' || value === 'error') return <span className="badge badge-error text-xs">✗ Review</span>;
  if (value === 'warning') return <span className="badge badge-warning text-xs">⚠ Review</span>;
  return <span className="null-indicator">Not assessable</span>;
}

function numeric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function formatArea(value: unknown): string {
  const amount = numeric(value);
  return amount == null ? 'Unknown' : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} m²`;
}

export default function ValidationPanel() {
  const { selectedPlot, analysis } = useAnalysisStore();
  if (!analysis) return null;

  const v = selectedPlot?.validation;
  const reviewFeatures = analysis.features.filter(feature => feature.review_required || feature.warning);
  const statusConfig = {
    valid: { label: 'Valid', className: 'badge-success', icon: '✓' },
    warning: { label: 'Warning', className: 'badge-warning', icon: '⚠' },
    error: { label: 'Error', className: 'badge-error', icon: '✗' },
    unknown: { label: 'Unknown', className: 'badge-unknown', icon: '?' },
  } as const;
  const cfg = statusConfig[v?.status as keyof typeof statusConfig] ?? statusConfig.unknown;
  const topology = v?.details?.topology && typeof v.details.topology === 'object'
    ? v.details.topology as Record<string, unknown>
    : {};
  const geometryCheck = topologyEntry(topology.geometry_valid);
  const overlapCheck = topologyEntry(topology.overlaps);
  const gapCheck = topologyEntry(topology.gaps);
  const closedCheck = topologyEntry(topology.boundary_closed);
  const length = selectedPlot?.measurements?.length_m;
  const width = selectedPlot?.measurements?.width_m;

  return (
    <div className="card p-4 space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <p className="section-header mb-0">Checks</p>
        {selectedPlot && <span className={`badge ${cfg.className}`}>{cfg.icon} {cfg.label}</span>}
      </div>

      {!selectedPlot ? (
        <section className="space-y-2" aria-label="Survey-wide plot checks">
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            All plots are shown. Select one above to inspect its measurements and topology.
          </p>
          {analysis.plots.map(plot => (
            <div key={plot.id} className="flex items-center justify-between gap-3 py-2 px-3 rounded-lg" style={{ background: 'var(--bg-elevated)' }}>
              <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                {plot.plot_number ? `Plot ${plot.plot_number}` : 'Target plot not identified'}
                {' · '}{plot.geometry?.pixel_coordinates?.length ? 'boundary associated' : 'boundary needs review'}
              </span>
              {checkBadge(plot.validation?.status)}
            </div>
          ))}
        </section>
      ) : !v ? (
        <p className="null-indicator text-center py-2">Checks are not available for this plot.</p>
      ) : (
        <>
          <div className="space-y-2">
            {[
              { label: 'Stated area vs. calculated area', value: v.area_match },
              { label: 'Dimension product vs. stated area', value: v.dimension_match },
              { label: 'Geometry consistent with dimensions', value: v.geometry_consistent },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between py-1.5 px-3 rounded-lg" style={{ background: 'var(--bg-elevated)' }}>
                <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</span>
                {value == null ? <span className="null-indicator">Not assessable</span>
                  : value ? <span className="badge badge-success text-xs">✓ Pass</span>
                    : <span className="badge badge-error text-xs">✗ Review</span>}
              </div>
            ))}
          </div>

          <section className="space-y-2" aria-label="Observed and calculated measurements">
            <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Measurements</p>
            {(length || width) && (
              <div className="rounded-lg p-3 text-xs space-y-1" style={{ background: 'var(--bg-elevated)', color: 'var(--text-secondary)' }}>
                <div>Observed dimensions: {length?.value ?? 'Unknown'} × {width?.value ?? 'Unknown'} {length?.unit || width?.unit || 'm'}</div>
                <div>Source: OCR survey text · values are preserved as read</div>
              </div>
            )}
            {selectedPlot.measurements?.stated_area_m2 && (
              <div className="rounded-lg p-3 text-xs space-y-1" style={{ background: 'var(--bg-elevated)', color: 'var(--text-secondary)' }}>
                <div>Stated area: {formatArea(selectedPlot.measurements.stated_area_m2.value)}</div>
                <div>Calculated area: {formatArea(v.details?.calculated_area_m2 ?? selectedPlot.measurements.calculated_area_m2)}</div>
                <div>Source: {selectedPlot.measurements.stated_area_m2.source || 'not recorded'} · difference: {v.area_discrepancy_pct == null ? 'not assessable' : `${v.area_discrepancy_pct.toFixed(1)}%`}</div>
              </div>
            )}
          </section>

          <section className="space-y-2" aria-label="Polygon topology checks">
            <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Topology</p>
            {[
              { label: 'Polygon validity', check: geometryCheck },
              { label: 'Overlap with reconstructed plots', check: overlapCheck },
              { label: 'Boundary closure', check: closedCheck },
              { label: 'Layout gaps', check: gapCheck },
            ].map(({ label, check }) => (
              <div key={label} className="flex items-center justify-between gap-3 py-1.5 px-3 rounded-lg" style={{ background: 'var(--bg-elevated)' }}>
                <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</span>
                {checkBadge(check?.status)}
              </div>
            ))}
            {overlapCheck?.plots && overlapCheck.plots.length > 0 && (
              <p className="text-xs" style={{ color: 'var(--warning)' }}>Overlaps: {overlapCheck.plots.join(', ')}</p>
            )}
            {gapCheck?.reason && <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{gapCheck.reason}</p>}
          </section>

          {v.area_discrepancy_pct != null && (
            <div className="flex items-center justify-between py-1.5 px-3 rounded-lg" style={{ background: 'var(--bg-elevated)' }}>
              <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>Area difference</span>
              <span className="value-mono text-sm">{v.area_discrepancy_pct.toFixed(1)}%</span>
            </div>
          )}

          {v.warnings.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium" style={{ color: 'var(--warning)' }}>Warnings</p>
              {v.warnings.map((warning, index) => (
                <div key={index} className="p-3 rounded-lg text-xs" style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.2)', color: '#f59e0b' }}>
                  {warning}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {reviewFeatures.length > 0 && (
        <section className="space-y-2" aria-label="Feature review checks">
          <p className="text-xs font-medium" style={{ color: 'var(--warning)' }}>
            Feature classification needs review ({reviewFeatures.length})
          </p>
          {reviewFeatures.map(feature => (
            <div key={feature.id} className="p-3 rounded-lg text-xs space-y-1" style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.2)', color: '#f59e0b' }}>
              <strong>{feature.label || feature.feature_type.replaceAll('_', ' ')}</strong>
              <div>{feature.warning || 'Confirm this feature observation before using it in a drawing.'}</div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
