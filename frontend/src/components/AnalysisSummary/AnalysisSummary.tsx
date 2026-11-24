/**
 * Analysis Summary — shows plot details, measurements, boundaries.
 * Displays null fields as "Not detected" — never invents values.
 */

import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';
import type { EvidencedValue } from '../../types';
import { updatePlot, updateSurveyFeature } from '../../api/client';
import RevisionHistory from '../GeometryEditor/RevisionHistory';

function Field({
  label, value, unit, source, confidence
}: {
  label: string;
  value: unknown;
  unit?: string | null;
  source?: string | null;
  confidence?: number | null;
}) {
  const hasValue = value !== null && value !== undefined && value !== '';

  return (
    <div className="flex items-start justify-between py-2 border-b"
         style={{ borderColor: 'var(--border-subtle)' }}>
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <div className="text-right">
        {hasValue ? (
          <>
            <span className="value-mono text-sm">
              {String(value)}{unit ? ` ${unit}` : ''}
            </span>
            {source && (
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                via {source}{confidence != null ? ` (${Math.round(confidence * 100)}%)` : ''}
              </div>
            )}
          </>
        ) : (
          <span className="null-indicator">Not detected</span>
        )}
      </div>
    </div>
  );
}

function EvidencedField({ label, ev }: { label: string; ev: EvidencedValue | null | undefined }) {
  return (
    <Field
      label={label}
      value={ev?.value ?? null}
      unit={ev?.unit}
      source={ev?.source ?? undefined}
      confidence={ev?.confidence ?? undefined}
    />
  );
}

function BoundaryItem({ dir, ev }: { dir: string; ev: EvidencedValue<string> | null | undefined }) {
  const hasValue = ev?.value != null;
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs font-medium w-12" style={{ color: 'var(--text-muted)' }}>{dir}</span>
      <div className="flex-1 text-right">
        {hasValue
          ? <span className="text-sm" style={{ color: 'var(--text-primary)' }}>{ev!.value}</span>
          : <span className="null-indicator">—</span>}
      </div>
    </div>
  );
}

export default function AnalysisSummary() {
  const store = useAnalysisStore();
  const plot = store.selectedPlot;
  const feature = store.selectedFeature;
  const [editingPlotNo, setEditingPlotNo] = useState(false);
  const [plotNoVal, setPlotNoVal] = useState('');
  
  const [editingFeature, setEditingFeature] = useState(false);
  const [featureTypeVal, setFeatureTypeVal] = useState('');
  const [featureLabelVal, setFeatureLabelVal] = useState('');

  if (!store.analysis || (!plot && !feature)) {
    return (
      <div className="card p-4">
        <p className="null-indicator text-center py-4">Select a plot or feature from the dropdown to view details.</p>
      </div>
    );
  }

  const savePlotNo = async () => {
    if (plot) {
      const p = await updatePlot(plot.id, { plot_number: plotNoVal });
      if (store.analysis) {
        const newAnalysis = { ...store.analysis };
        const idx = newAnalysis.plots.findIndex(x => x.id === plot.id);
        if (idx !== -1) {
          newAnalysis.plots[idx] = { ...newAnalysis.plots[idx], plot_number: p.plot_number };
          store.setAnalysis(newAnalysis);
          store.setSelectedPlot(newAnalysis.plots[idx]);
        }
      }
    }
    setEditingPlotNo(false);
  };
  
  const saveFeature = async () => {
    if (feature) {
      const f = await updateSurveyFeature(feature.id, { feature_type: featureTypeVal as any, label: featureLabelVal });
      if (store.analysis) {
        const newAnalysis = { ...store.analysis };
        const idx = newAnalysis.features.findIndex(x => x.id === feature.id);
        if (idx !== -1) {
          newAnalysis.features[idx] = f;
          store.setAnalysis(newAnalysis);
          store.setSelectedFeature(newAnalysis.features[idx]);
        }
      }
    }
    setEditingFeature(false);
  };

  if (feature) {
    return (
      <div className="card p-4 space-y-4 animate-fade-in">
        <div>
          <p className="section-header">Feature Identification</p>
          <div className="space-y-0.5 mt-2">
            {!editingFeature ? (
              <div className="flex justify-between items-center py-2 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                <div>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Class / Label</span>
                  <div className="text-sm value-mono">{feature.feature_type} · {feature.label || 'unlabeled'}</div>
                </div>
                <button className="btn-ghost" onClick={() => {
                  setFeatureTypeVal(feature.feature_type);
                  setFeatureLabelVal(feature.label || '');
                  setEditingFeature(true);
                }}>Edit</button>
              </div>
            ) : (
              <div className="flex flex-col gap-2 py-2 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                <input className="input-field" value={featureTypeVal} onChange={e => setFeatureTypeVal(e.target.value)} placeholder="Type (e.g. road)" />
                <input className="input-field" value={featureLabelVal} onChange={e => setFeatureLabelVal(e.target.value)} placeholder="Label" />
                <div className="flex gap-2">
                  <button className="btn-primary" onClick={saveFeature}>Save</button>
                  <button className="btn-secondary" onClick={() => setEditingFeature(false)}>Cancel</button>
                </div>
              </div>
            )}
            
            <div className="flex items-center justify-between py-2">
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Status</span>
              <span className={`badge ${
                feature.review_status === 'confirmed' ? 'badge-success' :
                feature.review_status === 'detected' ? 'badge-info' : 'badge-warning'
              }`}>{feature.review_status || 'detected'}</span>
            </div>
            
            {feature.evidence_text && (
              <div className="flex flex-col py-2 mt-2">
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Evidence</span>
                <span className="text-sm value-mono mt-1">{feature.evidence_text}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  const m = plot?.measurements;
  const b = plot?.boundaries;

  return (
    <div className="card p-4 space-y-4 animate-fade-in">
      {/* Plot identification */}
      <div>
        <p className="section-header">Plot Identification</p>
        <div className="space-y-0.5">
          {!editingPlotNo ? (
            <div className="flex justify-between items-center py-2 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
              <div>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Plot Number</span>
                <div className="text-sm value-mono">{plot?.plot_number ?? 'Not detected'}</div>
              </div>
              <button className="btn-ghost" onClick={() => {
                setPlotNoVal(plot?.plot_number || '');
                setEditingPlotNo(true);
              }}>Edit</button>
            </div>
          ) : (
            <div className="flex gap-2 py-2 border-b items-center" style={{ borderColor: 'var(--border-subtle)' }}>
              <input className="input-field" value={plotNoVal} onChange={e => setPlotNoVal(e.target.value)} placeholder="Plot No." />
              <button className="btn-primary" onClick={savePlotNo}>Save</button>
              <button className="btn-secondary" onClick={() => setEditingPlotNo(false)}>Cancel</button>
            </div>
          )}
          <Field label="Survey Number" value={plot?.survey_number} />
          <div className="flex items-center justify-between py-2">
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Status</span>
            <span className={`badge ${
              plot?.status === 'detected' ? 'badge-success' :
              plot?.status === 'manual'   ? 'badge-info'    :
              plot?.status === 'uncertain'? 'badge-warning' : 'badge-neutral'
            }`}>{plot?.status}</span>
          </div>
        </div>
      </div>

      {/* Measurements */}
      <div>
        <p className="section-header">Measurements</p>
        <div className="space-y-0.5">
          <EvidencedField label="Length"      ev={m?.length_m} />
          <EvidencedField label="Width"       ev={m?.width_m} />
          <EvidencedField label="Stated Area" ev={m?.stated_area_m2} />
          <Field label="Calculated Area" value={m?.calculated_area_m2 ?? null} unit="m²" />
          <Field label="Area (ha)"        value={m?.area_ha ?? null}           unit="ha" />
          <Field label="Units"            value={m?.units ?? null} />
        </div>
        {m?.conflicting_values && Object.keys(m.conflicting_values).length > 0 && (
          <div className="conflict-box">
            <strong>Conflicting observations</strong>
            {Object.entries(m.conflicting_values).map(([field, values]) => (
              <div key={field}>
                <span>{field}</span>
                <p>{values.map(item => `${String(item.value)}${item.unit ? ` ${item.unit}` : ''} · ${item.source}`).join(' / ')}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Boundaries */}
      {b && (
        <div>
          <p className="section-header">Boundaries</p>
          <div className="p-3 rounded-lg" style={{ background: 'var(--bg-elevated)' }}>
            <BoundaryItem dir="N ↑" ev={b.north} />
            <BoundaryItem dir="S ↓" ev={b.south} />
            <BoundaryItem dir="E →" ev={b.east} />
            <BoundaryItem dir="W ←" ev={b.west} />
          </div>
          {b.north_arrow_detected === false && (
            <p className="text-xs mt-2 null-indicator">North arrow not detected in image</p>
          )}
        </div>
      )}

      {/* Geometry summary */}
      {plot?.geometry && (
        <div>
          <p className="section-header">Geometry</p>
          <div className="space-y-0.5">
            <Field label="Type"       value={plot.geometry.geom_type} />
            <Field label="Source"     value={plot.geometry.source} />
            <Field label="Confidence" value={plot.geometry.confidence != null
              ? `${Math.round(plot.geometry.confidence * 100)}%` : null} />
            <Field label="Area (geom)" value={plot.geometry.calculated_area_m2} unit="m²" />
          </div>
        </div>
      )}

      {!plot?.geometry && (
        <div className="p-3 rounded-lg text-center"
             style={{ background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.2)' }}>
          <p className="text-sm" style={{ color: '#6366f1' }}>
            Plot boundary could not be confidently detected.
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Use Edit boundary to manually define the boundary.
          </p>
        </div>
      )}
      
      <RevisionHistory />
    </div>
  );
}
