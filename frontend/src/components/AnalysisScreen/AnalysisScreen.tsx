/**
 * Analysis Screen — shows what the pipeline found.
 *
 * Primary content: annotated image + analysis summary cards.
 * Secondary content: OCR tokens, CV candidates, feature list.
 *
 * No developer terminology on the primary view.
 */

import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';
import AnnotatedViewer from '../AnnotatedViewer/AnnotatedViewer';
import OriginalViewer from '../OriginalViewer/OriginalViewer';
import AnalysisSummary from '../AnalysisSummary/AnalysisSummary';
import ConfidencePanel from '../ConfidencePanel/ConfidencePanel';
import ValidationPanel from '../ValidationPanel/ValidationPanel';

export default function AnalysisScreen() {
  const { analysis } = useAnalysisStore();
  const [showDetails, setShowDetails] = useState(false);

  if (!analysis) return null;

  const plotCount = analysis.plots.filter(p => !!p.geometry?.pixel_coordinates?.length).length;
  const totalLabels = analysis.plots.filter(p => !!p.plot_number).length;
  const featureCount = analysis.features.filter(f => f.review_status !== 'rejected').length;
  const reviewRequired =
    analysis.plots.filter(p => p.status === 'uncertain').length +
    analysis.features.filter(f => f.review_required && f.review_status !== 'confirmed').length;
  const calib = analysis.calibration;
  const isCalibrated = calib && calib.status !== 'uncalibrated' && calib.scale_factor_px_per_m;

  return (
    <div className="analysis-screen animate-fade-in">
      {/* Evidence summary bar */}
      <div className="analysis-evidence-bar">
        <div className="evidence-item">
          <span className="evidence-value">{totalLabels}</span>
          <span className="evidence-label">Plot labels</span>
        </div>
        <div className="evidence-divider" />
        <div className="evidence-item">
          <span className="evidence-value">{plotCount}</span>
          <span className="evidence-label">With geometry</span>
        </div>
        <div className="evidence-divider" />
        <div className="evidence-item">
          <span className="evidence-value">{featureCount}</span>
          <span className="evidence-label">Site features</span>
        </div>
        <div className="evidence-divider" />
        <div className="evidence-item">
          <span className="evidence-value">{analysis.ocr_results.length}</span>
          <span className="evidence-label">OCR tokens</span>
        </div>
        <div className="evidence-divider" />
        <div className="evidence-item">
          {reviewRequired > 0
            ? <span className="evidence-value evidence-warn">⚠ {reviewRequired}</span>
            : <span className="evidence-value evidence-ok">✓</span>
          }
          <span className="evidence-label">Needs review</span>
        </div>
        <div className="evidence-divider" />
        <div className="evidence-item">
          <span className={`evidence-value ${isCalibrated ? 'evidence-ok' : 'evidence-muted'}`}>
            {isCalibrated ? '✓' : '—'}
          </span>
          <span className="evidence-label">Calibration</span>
        </div>

        <button className="btn-ghost text-xs ml-auto" onClick={() => setShowDetails(v => !v)}>
          {showDetails ? 'Hide details' : 'Technical details'}
        </button>
      </div>

      {/* Main content area */}
      <div className="analysis-grid">
        <div className="analysis-visual-column">
          <AnnotatedViewer />
          {showDetails && <OriginalViewer />}
        </div>
        <aside className="analysis-inspector">
          <AnalysisSummary />
          {showDetails && (
            <>
              <ConfidencePanel />
              <ValidationPanel />
            </>
          )}
          {!showDetails && <ValidationPanel />}
        </aside>
      </div>

      {/* Technical details drawer */}
      {showDetails && (
        <div className="card p-4 mt-4">
          <p className="section-header">CV Geometry Candidates ({analysis.cv_candidates.length})</p>
          <div className="cv-candidate-list">
            {analysis.cv_candidates.slice(0, 30).map(c => (
              <div key={c.id} className={`cv-candidate-row ${c.selected ? 'is-selected' : ''}`}>
                <span className="cv-type">{c.candidate_type || 'contour'}</span>
                <span className="cv-points">{c.pixel_coordinates?.length ?? 0} pts</span>
                <span className="cv-area">{c.area_pixels ? Math.round(c.area_pixels).toLocaleString() : '—'} px²</span>
                {c.evidence_score != null && (
                  <span className="cv-score">{Math.round(c.evidence_score * 100)}%</span>
                )}
                {c.selected && <span className="badge badge-success" style={{ fontSize: '0.6rem' }}>selected</span>}
              </div>
            ))}
            {analysis.cv_candidates.length > 30 && (
              <p className="text-xs" style={{ color: 'var(--text-muted)', padding: '8px' }}>
                + {analysis.cv_candidates.length - 30} more candidates not shown
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
