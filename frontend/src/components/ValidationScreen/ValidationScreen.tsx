/**
 * Validation Screen — concise survey-wide validation summary.
 *
 * Shows: overall counts, warnings per plot, feature review items.
 * Clicking a warning item navigates directly to Edit → selects that object.
 */

import { useAnalysisStore } from '../../store/analysisStore';

interface Props {
  onNavigate: (tab: string) => void;
}

export default function ValidationScreen({ onNavigate }: Props) {
  const { analysis, setSelectedPlot, setSelectedFeature } = useAnalysisStore();

  if (!analysis) return null;

  const validPlots = analysis.plots.filter(p => p.validation?.status === 'valid');
  const warnPlots = analysis.plots.filter(p => p.validation?.status === 'warning');
  const errorPlots = analysis.plots.filter(p => p.validation?.status === 'error');
  const noBoundary = analysis.plots.filter(p => !p.geometry?.pixel_coordinates?.length);
  const reviewFeatures = analysis.features.filter(
    f => (f.review_required || !!f.warning) && f.review_status !== 'confirmed' && f.review_status !== 'rejected'
  );

  const overallOk = errorPlots.length === 0 && warnPlots.length === 0 && reviewFeatures.length === 0 && noBoundary.length === 0;

  const handlePlotClick = (plotId: string) => {
    const plot = analysis.plots.find(p => p.id === plotId);
    if (plot) {
      setSelectedPlot(plot);
      onNavigate('edit');
    }
  };

  const handleFeatureClick = (featureId: string) => {
    const feature = analysis.features.find(f => f.id === featureId);
    if (feature) {
      setSelectedFeature(feature);
      onNavigate('plan');
    }
  };

  return (
    <div className="validation-screen animate-fade-in">
      <div className="validation-header">
        <div>
          <h2 className="font-semibold text-lg" style={{ color: 'var(--text-primary)' }}>Validation</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
            Survey-wide geometry and measurement checks
          </p>
        </div>
        {overallOk && (
          <span className="badge badge-success" style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
            ✓ Ready to export
          </span>
        )}
      </div>

      {/* Summary row */}
      <div className="validation-summary-grid">
        <div className={`vsummary-item ${validPlots.length > 0 ? 'vsummary-ok' : ''}`}>
          <span className="vsummary-icon">✓</span>
          <span className="vsummary-count">{validPlots.length}</span>
          <span className="vsummary-label">Plot{validPlots.length !== 1 ? 's' : ''} valid</span>
        </div>
        <div className={`vsummary-item ${warnPlots.length > 0 ? 'vsummary-warn' : ''}`}>
          <span className="vsummary-icon">{warnPlots.length > 0 ? '⚠' : '✓'}</span>
          <span className="vsummary-count">{warnPlots.length}</span>
          <span className="vsummary-label">Warnings</span>
        </div>
        <div className={`vsummary-item ${errorPlots.length > 0 ? 'vsummary-error' : ''}`}>
          <span className="vsummary-icon">{errorPlots.length > 0 ? '✗' : '✓'}</span>
          <span className="vsummary-count">{errorPlots.length}</span>
          <span className="vsummary-label">Errors</span>
        </div>
        <div className={`vsummary-item ${noBoundary.length > 0 ? 'vsummary-warn' : ''}`}>
          <span className="vsummary-icon">{noBoundary.length > 0 ? '⚠' : '✓'}</span>
          <span className="vsummary-count">{noBoundary.length}</span>
          <span className="vsummary-label">No boundary</span>
        </div>
        <div className={`vsummary-item ${reviewFeatures.length > 0 ? 'vsummary-warn' : ''}`}>
          <span className="vsummary-icon">{reviewFeatures.length > 0 ? '⚠' : '✓'}</span>
          <span className="vsummary-count">{reviewFeatures.length}</span>
          <span className="vsummary-label">Feature reviews</span>
        </div>
      </div>

      {/* Plots with issues */}
      {(warnPlots.length > 0 || errorPlots.length > 0 || noBoundary.length > 0) && (
        <div className="card p-4">
          <p className="section-header">Plots requiring attention</p>
          <div className="validation-item-list">
            {[...errorPlots, ...warnPlots, ...noBoundary].map(plot => {
              const warnings = plot.validation?.warnings ?? [];
              const hasBoundary = !!plot.geometry?.pixel_coordinates?.length;
              return (
                <button
                  key={plot.id}
                  className="validation-plot-row"
                  onClick={() => handlePlotClick(plot.id)}
                >
                  <div className="vprow-left">
                    <span className={`badge ${plot.validation?.status === 'error' ? 'badge-error' : 'badge-warning'}`}>
                      {plot.validation?.status === 'error' ? '✗' : '⚠'}
                    </span>
                    <span className="vprow-name">
                      {plot.plot_number ? `Plot ${plot.plot_number}` : 'Unidentified plot'}
                    </span>
                    {!hasBoundary && (
                      <span className="badge badge-neutral" style={{ fontSize: '0.6rem' }}>no boundary</span>
                    )}
                  </div>
                  <div className="vprow-warnings">
                    {warnings.slice(0, 2).map((w, i) => (
                      <span key={i} className="vprow-warning-text">{w}</span>
                    ))}
                    {warnings.length > 2 && (
                      <span className="vprow-warning-text">+{warnings.length - 2} more</span>
                    )}
                  </div>
                  <span className="vprow-action">Edit →</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Features requiring review */}
      {reviewFeatures.length > 0 && (
        <div className="card p-4">
          <p className="section-header">Features requiring review ({reviewFeatures.length})</p>
          <div className="validation-item-list">
            {reviewFeatures.map(feature => (
              <button
                key={feature.id}
                className="validation-plot-row"
                onClick={() => handleFeatureClick(feature.id)}
              >
                <div className="vprow-left">
                  <span className="badge badge-warning">⚠</span>
                  <span className="vprow-name">
                    {feature.label || feature.feature_type.replaceAll('_', ' ')}
                  </span>
                  <span className="badge badge-neutral" style={{ fontSize: '0.6rem' }}>
                    {feature.feature_type.replaceAll('_', ' ')}
                  </span>
                </div>
                <div className="vprow-warnings">
                  <span className="vprow-warning-text">{feature.warning || 'Review classification before using in drawing'}</span>
                </div>
                <span className="vprow-action">Review →</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* All plots list */}
      <div className="card p-4">
        <p className="section-header">All plots ({analysis.plots.length})</p>
        <div className="validation-all-plots">
          {analysis.plots.map(plot => {
            const hasBoundary = !!plot.geometry?.pixel_coordinates?.length;
            const status = plot.validation?.status;
            return (
              <button
                key={plot.id}
                className="validation-all-row"
                onClick={() => handlePlotClick(plot.id)}
              >
                <span className="var-name">{plot.plot_number ? `Plot ${plot.plot_number}` : '—'}</span>
                <span className="var-geo">{hasBoundary ? 'boundary detected' : 'no boundary'}</span>
                {status === 'valid' && <span className="badge badge-success text-xs">✓ Valid</span>}
                {status === 'warning' && <span className="badge badge-warning text-xs">⚠ Warning</span>}
                {status === 'error' && <span className="badge badge-error text-xs">✗ Error</span>}
                {(!status || status === 'unknown') && <span className="null-indicator">Not assessed</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
