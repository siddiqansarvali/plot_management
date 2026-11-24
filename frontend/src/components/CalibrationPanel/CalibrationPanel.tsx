import { useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';

export default function CalibrationPanel() {
  const { analysis } = useAnalysisStore();
  const calibration = analysis?.calibration;

  const [mode, setMode] = useState<'view' | 'manual'>('view');
  const [knownDistance, setKnownDistance] = useState('');
  const [point1, setPoint1] = useState('');
  const [point2, setPoint2] = useState('');

  const submitManual = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!analysis?.analysis_id) return;
    
    try {
      const pt1 = point1.split(',').map(Number);
      const pt2 = point2.split(',').map(Number);
      
      const response = await fetch(`/api/analysis/${analysis.analysis_id}/calibration/manual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          known_distance_m: Number(knownDistance),
          point_1_px: pt1,
          point_2_px: pt2,
        })
      });
      
      if (!response.ok) throw new Error("Failed to calibrate");
      
      // We would ideally refresh analysis here.
      alert('Calibration saved. Please refresh analysis to see updated coordinates.');
      setMode('view');
    } catch (e) {
      console.error(e);
      alert('Failed to save manual calibration');
    }
  };

  const confirmAuto = async () => {
    if (!analysis?.analysis_id) return;
    try {
      const response = await fetch(`/api/analysis/${analysis.analysis_id}/calibration/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_confirmed: true })
      });
      if (!response.ok) throw new Error("Failed to confirm");
      alert('Calibration confirmed.');
    } catch (e) {
      console.error(e);
      alert('Failed to confirm calibration');
    }
  };

  return (
    <div className="card p-5 animate-fade-in space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>Scale Calibration</h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Transform pixel-based geometry into real-world coordinates.</p>
        </div>
        <div>
          {mode === 'view' ? (
            <button className="btn-secondary" onClick={() => setMode('manual')}>Manual Calibration</button>
          ) : (
            <button className="btn-secondary" onClick={() => setMode('view')}>View Calibration</button>
          )}
        </div>
      </div>

      {mode === 'view' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-gray-50 p-4 rounded-md">
              <p className="text-xs text-gray-500 uppercase font-bold">Status</p>
              <p className="text-lg font-medium mt-1">{calibration?.status || 'Unknown'}</p>
            </div>
            <div className="bg-gray-50 p-4 rounded-md">
              <p className="text-xs text-gray-500 uppercase font-bold">Estimated Scale</p>
              <p className="text-lg font-medium mt-1">
                {calibration?.scale_factor_px_per_m ? `${calibration.scale_factor_px_per_m.toFixed(2)} px/m` : 'N/A'}
              </p>
            </div>
            <div className="bg-gray-50 p-4 rounded-md">
              <p className="text-xs text-gray-500 uppercase font-bold">Confidence</p>
              <p className="text-lg font-medium mt-1">
                {calibration?.confidence != null ? `${(calibration.confidence * 100).toFixed(0)}%` : 'N/A'}
              </p>
            </div>
            <div className="bg-gray-50 p-4 rounded-md">
              <p className="text-xs text-gray-500 uppercase font-bold">Residual Error</p>
              <p className="text-lg font-medium mt-1">
                {calibration?.residual_error != null ? `${calibration.residual_error.toFixed(2)}` : 'N/A'}
              </p>
            </div>
          </div>

          <div>
            <h3 className="font-semibold text-sm mb-2" style={{ color: 'var(--text-primary)' }}>Supporting Dimensions</h3>
            {calibration?.supporting_dimensions && calibration.supporting_dimensions.length > 0 ? (
              <ul className="list-disc pl-5 text-sm" style={{ color: 'var(--text-secondary)' }}>
                {calibration.supporting_dimensions.map((dim: any, i: number) => (
                  <li key={i}>
                    {dim.source}: {dim.dimension_px.toFixed(1)}px / {dim.dimension_m.toFixed(1)}m = {dim.scale_px_per_m.toFixed(2)} px/m
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm italic" style={{ color: 'var(--text-muted)' }}>No supporting dimensions found.</p>
            )}
          </div>

          {!calibration?.is_manual && calibration?.status !== 'uncalibrated' && (
            <div className="pt-4 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
              <button className="btn-primary" onClick={confirmAuto}>Confirm Calibration</button>
            </div>
          )}
        </div>
      )}

      {mode === 'manual' && (
        <form onSubmit={submitManual} className="space-y-4 max-w-md">
          <div>
            <label className="block text-sm font-medium mb-1">Known distance (meters)</label>
            <input 
              type="number" 
              step="any"
              className="input w-full" 
              value={knownDistance} 
              onChange={e => setKnownDistance(e.target.value)} 
              required 
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Point 1 (x, y pixels)</label>
            <input 
              type="text" 
              className="input w-full" 
              placeholder="e.g. 100,200" 
              value={point1} 
              onChange={e => setPoint1(e.target.value)} 
              required 
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Point 2 (x, y pixels)</label>
            <input 
              type="text" 
              className="input w-full" 
              placeholder="e.g. 300,400" 
              value={point2} 
              onChange={e => setPoint2(e.target.value)} 
              required 
            />
          </div>
          <button type="submit" className="btn-primary w-full">Calculate & Save</button>
        </form>
      )}
    </div>
  );
}
