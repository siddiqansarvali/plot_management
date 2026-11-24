/**
 * Overview Screen — primary project dashboard shown after analysis completes.
 *
 * Shows: survey name, status, plot/feature counts, items needing review,
 * calibration status, and a concise analysis health summary.
 *
 * Technical details (component statuses, raw diagnostics) are hidden behind
 * a collapsible "System diagnostics" section.
 */

import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';
import type { ComponentStatus, ComponentStatuses } from '../../types';

interface Props {
  onNavigate: (tab: string) => void;
}

function userStatusLabel(status: ComponentStatus | null | undefined): string {
  if (status === 'ok') return 'OK';
  if (status === 'running') return 'Running';
  if (status === 'failed') return 'Failed';
  if (status === 'unavailable' || status === 'not_configured') return 'Unavailable';
  if (status === 'disabled' || status === 'no_result') return 'Disabled';
  if (status === 'not_implemented') return 'Not implemented';
  return 'Unknown';
}

function statusIcon(status: ComponentStatus | null | undefined): string {
  if (status === 'ok') return '✓';
  if (status === 'running') return '◌';
  if (status === 'failed' || status === 'unavailable') return '⚠';
  return '—';
}

function statusClass(status: ComponentStatus | null | undefined): string {
  if (status === 'ok') return 'health-ok';
  if (status === 'running') return 'health-running';
  if (status === 'failed' || status === 'unavailable') return 'health-warn';
  return 'health-muted';
}

const HEALTH_ITEMS: { id: keyof ComponentStatuses; label: string }[] = [
  { id: 'ocr',        label: 'OCR' },
  { id: 'opencv',     label: 'Geometry detection' },
  { id: 'fusion',     label: 'Feature detection' },
  { id: 'llm',        label: 'Vision AI' },
  { id: 'annotation', label: 'Annotation' },
];

export default function OverviewScreen({ onNavigate }: Props) {
  const { analysis } = useAnalysisStore();
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  if (!analysis) return null;

  const docName = analysis.document_name || 'Survey document';
  const isPartial = analysis.status === 'partial';
  const plotCount = analysis.plots.filter(p => !!p.geometry?.pixel_coordinates?.length).length;
  const totalPlotLabels = analysis.plots.filter(p => !!p.plot_number).length;
  const featureCount = analysis.features.filter(f => f.review_status !== 'rejected').length;
  const reviewRequired =
    analysis.plots.filter(p => p.status === 'uncertain').length +
    analysis.features.filter(f => (f.review_required || !!f.warning) && f.review_status !== 'rejected' && f.review_status !== 'confirmed').length;

  const calib = analysis.calibration;
  const isCalibrated = calib && calib.status !== 'uncalibrated' && calib.scale_factor_px_per_m;

  const statuses = analysis.components;
  const diagnostics = analysis.component_diagnostics ?? {};

  return (
    <div className="overview-screen animate-fade-in">
      {/* Survey hero header */}
      <div className="overview-hero">
        <div className="overview-hero-left">
          <div className="overview-doc-name">{docName.replace(/\.[^.]+$/, '').toUpperCase()}</div>
          <div className="flex items-center gap-3 mt-2">
            <span className={`badge ${isPartial ? 'badge-warning' : 'badge-success'}`}>
              {isPartial ? '⚠ Analysis partially complete' : '✓ Analysis complete'}
            </span>
            {analysis.completed_at && (
              <span className="overview-timestamp">
                {new Date(analysis.completed_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>

        <div className="overview-hero-actions">
          {reviewRequired > 0 && (
            <button className="btn-secondary" onClick={() => onNavigate('validate')}>
              Review {reviewRequired} item{reviewRequired !== 1 ? 's' : ''}
            </button>
          )}
          <button className="btn-primary" onClick={() => onNavigate('plan')}>
            Open Digital Plan
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="overview-stats-grid">
        <div className="overview-stat" onClick={() => onNavigate('plan')} role="button" tabIndex={0}
             onKeyDown={e => e.key === 'Enter' && onNavigate('plan')}>
          <div className="stat-value">{plotCount}</div>
          <div className="stat-label">Plot{plotCount !== 1 ? 's' : ''} with geometry</div>
          {totalPlotLabels > plotCount && (
            <div className="stat-sub">{totalPlotLabels - plotCount} label{totalPlotLabels - plotCount !== 1 ? 's' : ''} without boundary</div>
          )}
        </div>

        <div className="overview-stat" onClick={() => onNavigate('plan')} role="button" tabIndex={0}
             onKeyDown={e => e.key === 'Enter' && onNavigate('plan')}>
          <div className="stat-value">{featureCount}</div>
          <div className="stat-label">Site feature{featureCount !== 1 ? 's' : ''} detected</div>
          <div className="stat-sub">{analysis.ocr_results.length} OCR labels</div>
        </div>

        <div className={`overview-stat ${reviewRequired > 0 ? 'stat-warning' : ''}`}
             onClick={() => reviewRequired > 0 && onNavigate('validate')}
             role={reviewRequired > 0 ? 'button' : undefined}
             tabIndex={reviewRequired > 0 ? 0 : undefined}
             onKeyDown={e => e.key === 'Enter' && reviewRequired > 0 && onNavigate('validate')}>
          {reviewRequired > 0
            ? <div className="stat-value stat-value-warn">⚠ {reviewRequired}</div>
            : <div className="stat-value stat-value-ok">✓ 0</div>
          }
          <div className="stat-label">{reviewRequired > 0 ? 'Needs review' : 'All items confirmed'}</div>
          {reviewRequired > 0 && <div className="stat-sub">Click to review</div>}
        </div>

        <div className="overview-stat" onClick={() => onNavigate('calibration')} role="button" tabIndex={0}
             onKeyDown={e => e.key === 'Enter' && onNavigate('calibration')}>
          {isCalibrated
            ? <div className="stat-value stat-value-ok">✓</div>
            : <div className="stat-value stat-value-muted">—</div>
          }
          <div className="stat-label">Calibration</div>
          <div className="stat-sub">
            {isCalibrated
              ? `${calib!.scale_factor_px_per_m!.toFixed(1)} px/m`
              : 'No real-world scale found'}
          </div>
        </div>
      </div>

      {/* Analysis health — compact summary */}
      <div className="overview-health-card">
        <div className="overview-health-header">
          <span className="overview-health-title">Analysis health</span>
          <button
            className="btn-ghost text-xs"
            onClick={() => setShowDiagnostics(v => !v)}
          >
            {showDiagnostics ? 'Hide diagnostics' : 'System diagnostics'}
          </button>
        </div>
        <div className="overview-health-items">
          {HEALTH_ITEMS.map(item => {
            const s = statuses?.[item.id];
            return (
              <div key={item.id} className={`health-item ${statusClass(s)}`}>
                <span className="health-icon">{statusIcon(s)}</span>
                <span className="health-label">{item.label}</span>
                {s !== 'ok' && s !== null && s !== undefined && (
                  <span className="health-detail">{userStatusLabel(s)}</span>
                )}
              </div>
            );
          })}
        </div>

        {showDiagnostics && (
          <div className="overview-diagnostics">
            <p className="diagnostics-title">System diagnostics</p>
            {Object.entries(diagnostics).length === 0 && (
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No diagnostic messages recorded.</p>
            )}
            {Object.entries(diagnostics).map(([key, detail]) => (
              <div key={key} className="diagnostic-row">
                <span className="diagnostic-key">{key.replaceAll('_', ' ')}</span>
                <span className="diagnostic-value">{detail}</span>
              </div>
            ))}
            {Object.entries(statuses ?? {}).map(([key, s]) => (
              <div key={key} className="diagnostic-row">
                <span className="diagnostic-key">{key.replaceAll('_', ' ')}</span>
                <span className="diagnostic-value">{userStatusLabel(s as ComponentStatus)}</span>
              </div>
            ))}
            {analysis.llm_raw_response && (
              <details className="mt-3">
                <summary className="text-xs cursor-pointer" style={{ color: 'var(--text-muted)' }}>
                  Raw Vision AI response
                </summary>
                <pre className="text-xs mt-2 overflow-auto" style={{ color: 'var(--text-muted)', maxHeight: 200 }}>
                  {analysis.llm_raw_response.slice(0, 2000)}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      {/* Workflow quick-access links */}
      <div className="overview-workflow-links">
        <span className="overview-workflow-title">Continue with</span>
        <button className="workflow-link" onClick={() => onNavigate('analysis')}>
          <span className="workflow-link-icon">🔬</span>
          <div>
            <div className="workflow-link-name">Analysis</div>
            <div className="workflow-link-sub">OCR results, geometry candidates, feature evidence</div>
          </div>
        </button>
        <button className="workflow-link" onClick={() => onNavigate('plan')}>
          <span className="workflow-link-icon">📐</span>
          <div>
            <div className="workflow-link-name">Digital Plan</div>
            <div className="workflow-link-sub">Vector survey canvas with all detected plots and features</div>
          </div>
        </button>
        <button className="workflow-link" onClick={() => onNavigate('edit')}>
          <span className="workflow-link-icon">✏️</span>
          <div>
            <div className="workflow-link-name">Review & Edit</div>
            <div className="workflow-link-sub">Move vertices, correct plot numbers, accept or reject geometry</div>
          </div>
        </button>
        <button className="workflow-link" onClick={() => onNavigate('validate')}>
          <span className="workflow-link-icon">✅</span>
          <div>
            <div className="workflow-link-name">Validate</div>
            <div className="workflow-link-sub">Check areas, dimensions, topology, and boundary consistency</div>
          </div>
        </button>
        <button className="workflow-link" onClick={() => onNavigate('export')}>
          <span className="workflow-link-icon">⬇</span>
          <div>
            <div className="workflow-link-name">Export</div>
            <div className="workflow-link-sub">Download SVG, PDF, GeoJSON, or DXF</div>
          </div>
        </button>
      </div>
    </div>
  );
}
