import { useEffect, useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';
import { getExportStatus, getExportUrl } from '../../api/client';

const FORMATS = [
  { id: 'svg',     label: 'SVG Vector',    desc: 'Scalable vector — best for editors (Inkscape, Illustrator)' },
  { id: 'pdf',     label: 'PDF',           desc: 'Printable document — for field use and archiving' },
  { id: 'geojson', label: 'GeoJSON',       desc: 'Geographic data — for GIS applications (QGIS, ArcGIS)' },
  { id: 'dxf',     label: 'DXF CAD',      desc: 'CAD exchange format — for AutoCAD, LibreCAD, etc.' },
] as const;

type ExportFormat = typeof FORMATS[number]['id'];

export default function ExportPanel() {
  const store = useAnalysisStore();
  const analysis = store.analysis;
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<ExportFormat | null>(null);

  useEffect(() => {
    let active = true;
    if (analysis?.analysis_id) {
      getExportStatus(analysis.analysis_id)
        .then(res => {
          if (active) setStatus(res);
        })
        .catch(err => {
          if (active) setError(err.response?.data?.detail || err.message || 'Export status unavailable');
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }
    return () => {
      active = false;
    };
  }, [analysis?.analysis_id]);

  if (!analysis) {
    return (
      <div className="card p-8 text-center">
        <div className="text-4xl mb-4">📋</div>
        <p style={{ color: 'var(--text-muted)' }}>No survey loaded. Upload and analyse a survey first.</p>
      </div>
    );
  }

  const calib = analysis.calibration;
  const isCalibrated = calib && calib.status !== 'uncalibrated' && calib.scale_factor_px_per_m;
  const isBlocked = status?.status === 'blocked';
  const hasWarnings = status?.status === 'warning';

  const handleDownload = (format: ExportFormat) => {
    if (isBlocked) return;
    setDownloading(format);
    const url = getExportUrl(analysis.analysis_id!, format);
    // Use a hidden anchor to avoid navigating away
    const a = document.createElement('a');
    a.href = url;
    a.download = `survey_${analysis.analysis_id?.slice(0, 8) ?? 'export'}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => setDownloading(null), 1500);
  };

  return (
    <div className="export-screen animate-fade-in">
      <div className="export-header">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>Export Survey</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
            Generate professional outputs from the validated survey model.{' '}
            {isCalibrated
              ? `Coordinates are in local survey space (${calib!.scale_factor_px_per_m!.toFixed(1)} px/m).`
              : 'Coordinates are in image space — calibrate to enable real-world coordinates.'}
          </p>
        </div>
        {!isCalibrated && (
          <button className="btn-secondary" onClick={() => store.setActiveTab('calibration' as any)}>
            Calibrate scale
          </button>
        )}
      </div>

      {/* Validation status banner */}
      {loading && (
        <div className="card p-4 text-sm" style={{ color: 'var(--text-muted)' }}>
          Checking export readiness…
        </div>
      )}
      {error && (
        <div className="notice-error">{error}</div>
      )}
      {!loading && status && (
        <div className={`export-status-banner ${isBlocked ? 'export-blocked' : hasWarnings ? 'export-warning' : 'export-ready'}`}>
          <div className="export-status-icon">
            {isBlocked ? '✗' : hasWarnings ? '⚠' : '✓'}
          </div>
          <div>
            <div className="font-semibold">
              {isBlocked ? 'Export blocked' : hasWarnings ? 'Export with warnings' : 'Ready to export'}
            </div>
            {status.reasons?.length > 0 && (
              <ul className="mt-2 text-sm space-y-1">
                {status.reasons.map((r: string, i: number) => <li key={i}>• {r}</li>)}
              </ul>
            )}
            {!isBlocked && status.warnings?.length > 0 && (
              <ul className="mt-2 text-sm space-y-1 opacity-80">
                {status.warnings.map((w: string, i: number) => <li key={i}>• {w}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* Format cards */}
      <div className="export-formats-grid">
        {FORMATS.map(fmt => (
          <div key={fmt.id} className={`export-format-card ${isBlocked ? 'export-format-disabled' : ''}`}>
            <div className="export-format-header">
              <span className="export-format-ext">.{fmt.id.toUpperCase()}</span>
              <span className="export-format-label">{fmt.label}</span>
            </div>
            <p className="export-format-desc">{fmt.desc}</p>
            <button
              className={`btn-primary w-full ${downloading === fmt.id ? 'downloading' : ''}`}
              onClick={() => handleDownload(fmt.id)}
              disabled={isBlocked || downloading !== null}
            >
              {downloading === fmt.id ? '⬇ Downloading…' : `Download ${fmt.label}`}
            </button>
          </div>
        ))}
      </div>

      {isBlocked && (
        <div className="card p-4 text-sm text-center" style={{ color: 'var(--text-muted)' }}>
          Resolve the errors above to enable export.{' '}
          <button className="btn-ghost" onClick={() => store.setActiveTab('edit' as any)}>
            Go to Edit
          </button>
        </div>
      )}
    </div>
  );
}
