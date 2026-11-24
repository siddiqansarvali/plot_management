/**
 * Zustand global state store.
 *
 * CRITICAL: When a new image is uploaded, the ENTIRE analysis state
 * is reset. No data from a previous image survives into a new analysis.
 * This is enforced by the resetAll() action.
 */

import { create } from 'zustand';
import type { AnalysisResult, Plot, SurveyFeature } from '../types';

// ── Upload state ──────────────────────────────────────────────────────────────
export interface UploadState {
  file: File | null;
  documentId: string | null;
  uploadProgress: number;           // 0–100
  isUploading: boolean;
  uploadError: string | null;
}

// ── Pipeline state ────────────────────────────────────────────────────────────
export type PipelinePhase =
  | 'idle'
  | 'uploading'
  | 'analyzing'
  | 'complete'
  | 'error';

// ── UI state ──────────────────────────────────────────────────────────────────
export type ActiveTab =
  | 'upload'
  | 'overview'
  | 'analysis'
  | 'plan'
  | 'edit'
  | 'validate'
  | 'export'
  // Legacy/diagnostics tabs
  | 'ocr'
  | 'preprocessed'
  | 'annotated'
  | 'cad'
  | 'redraw'
  | 'correction'
  | 'calibration';

// ── Full store ────────────────────────────────────────────────────────────────
export interface AnalysisStore {
  // Upload
  upload: UploadState;

  // Pipeline
  phase: PipelinePhase;
  pollingIntervalId: ReturnType<typeof setInterval> | null;

  // Analysis results
  analysis: AnalysisResult | null;

  // UI
  activeTab: ActiveTab;
  selectedPlot: Plot | null;
  selectedFeature: SurveyFeature | null;
  editingGeometry: boolean;
  targetPlotNumber: string;
  projectId: string | null;

  // Actions
  setFile: (file: File) => void;
  setDocumentId: (id: string) => void;
  setUploadProgress: (pct: number) => void;
  setUploading: (v: boolean) => void;
  setUploadError: (err: string | null) => void;

  setPhase: (phase: PipelinePhase) => void;
  setAnalysis: (result: AnalysisResult | null) => void;
  setPollingInterval: (id: ReturnType<typeof setInterval> | null) => void;

  setActiveTab: (tab: ActiveTab) => void;
  setSelectedPlot: (plot: Plot | null) => void;
  setSelectedFeature: (feature: SurveyFeature | null) => void;
  setEditingGeometry: (v: boolean) => void;
  setTargetPlotNumber: (n: string) => void;
  setProjectId: (id: string | null) => void;

  /** Reset EVERYTHING when a new image is uploaded. No cross-image contamination. */
  resetAll: () => void;
}

const initialUpload: UploadState = {
  file: null,
  documentId: null,
  uploadProgress: 0,
  isUploading: false,
  uploadError: null,
};

export const useAnalysisStore = create<AnalysisStore>((set, get) => ({
  // ── Initial state ──────────────────────────────────────────────────────────
  upload: initialUpload,
  phase: 'idle',
  pollingIntervalId: null,
  analysis: null,
  activeTab: 'upload',
  selectedPlot: null,
  selectedFeature: null,
  editingGeometry: false,
  targetPlotNumber: '',
  projectId: null,

  // ── Upload actions ─────────────────────────────────────────────────────────
  setFile: (file) => set((s) => ({ upload: { ...s.upload, file } })),
  setDocumentId: (id) => set((s) => ({ upload: { ...s.upload, documentId: id } })),
  setUploadProgress: (pct) => set((s) => ({ upload: { ...s.upload, uploadProgress: pct } })),
  setUploading: (v) => set((s) => ({ upload: { ...s.upload, isUploading: v } })),
  setUploadError: (err) => set((s) => ({ upload: { ...s.upload, uploadError: err } })),

  // ── Pipeline actions ───────────────────────────────────────────────────────
  setPhase: (phase) => set({ phase }),
  setAnalysis: (analysis) => {
    const plots = analysis?.plots ?? [];
    const previousId = get().selectedPlot?.id;
    const selected = plots.find(p => p.id === previousId)
      ?? plots.find(p => p.is_target && !!p.plot_number && p.plot_number_source === 'ocr')
      ?? null;
    set({ analysis, selectedPlot: selected });
  },
  setPollingInterval: (id) => set({ pollingIntervalId: id }),

  // ── UI actions ─────────────────────────────────────────────────────────────
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedPlot: (plot) => set({ selectedPlot: plot, selectedFeature: null }),
  setSelectedFeature: (feature) => set({ selectedFeature: feature, selectedPlot: null }),
  setEditingGeometry: (v) => set({ editingGeometry: v }),
  setTargetPlotNumber: (n) => set({ targetPlotNumber: n }),
  setProjectId: (id) => set({ projectId: id }),

  // ── Reset all — MUST be called on new upload ──────────────────────────────
  resetAll: () => {
    // Clear any active polling interval
    const { pollingIntervalId } = get();
    if (pollingIntervalId) clearInterval(pollingIntervalId);

    set({
      upload: initialUpload,
      phase: 'idle',
      pollingIntervalId: null,
      analysis: null,
      activeTab: 'upload',
      selectedPlot: null,
      editingGeometry: false,
      targetPlotNumber: '',
    });
  },
}));
