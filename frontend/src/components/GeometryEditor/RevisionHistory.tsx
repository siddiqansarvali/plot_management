import { useEffect, useState } from 'react';
import { getAnalysisHistory, undoAnalysisCorrection, redoAnalysisCorrection, getAnalysisResult } from '../../api/client';
import { useAnalysisStore } from '../../store/analysisStore';

export default function RevisionHistory() {
  const store = useAnalysisStore();
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    if (!store.analysis) return;
    try {
      const hist = await getAnalysisHistory(store.analysis.analysis_id!);
      setHistory(hist);
    } catch (e) {
      console.error("Failed to load history", e);
    }
  };

  useEffect(() => {
    fetchHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.analysis?.analysis_id]);

  const handleUndo = async () => {
    if (!store.analysis || !store.upload.documentId) return;
    setLoading(true);
    try {
      await undoAnalysisCorrection(store.analysis.analysis_id!);
      const updated = await getAnalysisResult(store.upload.documentId);
      store.setAnalysis(updated);
      await fetchHistory();
    } catch (e: any) {
      alert(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRedo = async () => {
    if (!store.analysis || !store.upload.documentId) return;
    setLoading(true);
    try {
      await redoAnalysisCorrection(store.analysis.analysis_id!);
      const updated = await getAnalysisResult(store.upload.documentId);
      store.setAnalysis(updated);
      await fetchHistory();
    } catch (e: any) {
      alert(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  if (!store.analysis) return null;

  const canUndo = history.some(h => !h.is_undone);
  const canRedo = history.some(h => h.is_undone);

  return (
    <div className="card p-4 mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold text-sm">Revision History</h3>
        <div className="flex gap-2">
          <button 
            className="btn-secondary text-xs" 
            onClick={handleUndo} 
            disabled={!canUndo || loading}
          >
            Undo Last
          </button>
          <button 
            className="btn-secondary text-xs" 
            onClick={handleRedo} 
            disabled={!canRedo || loading}
          >
            Redo
          </button>
        </div>
      </div>
      
      {history.length === 0 ? (
        <p className="text-xs null-indicator">No manual corrections yet. AI-generated geometry only.</p>
      ) : (
        <div className="space-y-3 relative pl-4 border-l border-gray-200">
          {history.map((rev) => (
            <div key={rev.id} className={`relative ${rev.is_undone ? 'opacity-40' : ''}`}>
              <div className="absolute w-2 h-2 rounded-full bg-blue-500 -left-[21px] top-1.5" />
              <p className="text-sm font-medium">
                Revision {rev.revision_number} — {rev.operation === 'metadata_update' ? 'Attribute corrected' : 'Geometry corrected'}
              </p>
              <div className="text-xs text-gray-500 flex justify-between mt-0.5">
                <span>{rev.note || 'Manual correction'}</span>
                <span>{new Date(rev.corrected_at).toLocaleTimeString()}</span>
              </div>
            </div>
          ))}
          <div className="relative pt-2">
            <div className="absolute w-2 h-2 rounded-full bg-gray-300 -left-[21px] top-3.5" />
            <p className="text-xs text-gray-500">Initial AI Analysis</p>
          </div>
        </div>
      )}
    </div>
  );
}
