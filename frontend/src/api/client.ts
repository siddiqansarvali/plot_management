/**
 * Axios API client for the FastAPI backend.
 * All API calls are centralized here — no ad-hoc fetch() elsewhere.
 */

import axios from 'axios';
import type {
  AnalysisResult,
  GeometryCorrectionRequest,
  GeometryCorrectionResponse,
  Project,
  ProjectDetail,
  SurveyFeature,
  TriggerResponse,
  UploadResponse,
} from '../types';

// Base URL — in dev, Vite proxy forwards /api to localhost:8000
const BASE_URL = '/api';

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120_000, // 2 min — LLM calls can be slow
});

// ── Upload ─────────────────────────────────────────────────────────────────────
export async function uploadSurveyImage(
  file: File,
  projectId?: string,
  onProgress?: (pct: number) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  if (projectId) form.append('project_id', projectId);

  const response = await client.post<UploadResponse>('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    },
  });
  return response.data;
}

// ── Analyze ────────────────────────────────────────────────────────────────────
export async function triggerAnalysis(
  documentId: string,
  targetPlotNumber?: string,
  forceReanalyze = false,
): Promise<TriggerResponse> {
  const response = await client.post<TriggerResponse>(`/analyze/${documentId}`, {
    target_plot_number: targetPlotNumber || null,
    force_reanalyze: forceReanalyze,
  });
  return response.data;
}

export async function getAnalysisResult(documentId: string): Promise<AnalysisResult> {
  const response = await client.get<AnalysisResult>(`/analysis/${documentId}`);
  return response.data;
}

// ── Images ─────────────────────────────────────────────────────────────────────
export function getOriginalImageUrl(documentId: string): string {
  return `/api/image/${documentId}/original`;
}

export function getAnnotatedImageUrl(documentId: string): string {
  return `/api/image/${documentId}/annotated`;
}

// ── Geometry correction ────────────────────────────────────────────────────────
export async function submitGeometryCorrection(
  plotId: string,
  correction: GeometryCorrectionRequest,
): Promise<GeometryCorrectionResponse> {
  const response = await client.post<GeometryCorrectionResponse>(
    `/geometry/${plotId}/correct`,
    correction,
  );
  return response.data;
}

export async function updateSurveyFeature(
  featureId: string,
  correction: Partial<Pick<SurveyFeature, 'feature_type' | 'label' | 'geometry' | 'review_status'>>,
): Promise<SurveyFeature> {
  const response = await client.patch<SurveyFeature>(`/features/${featureId}`, correction);
  return response.data;
}

export async function updatePlot(
  plotId: string,
  update: { plot_number?: string; review_status?: string },
): Promise<{ id: string; plot_number: string | null; status: string | null }> {
  const response = await client.patch(`/plots/${plotId}`, update);
  return response.data;
}

// ── Projects ───────────────────────────────────────────────────────────────────
export async function listProjects(): Promise<Project[]> {
  const response = await client.get<Project[]>('/project');
  return response.data;
}

export async function createProject(name: string, description?: string): Promise<Project> {
  const response = await client.post<Project>('/project', { name, description });
  return response.data;
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const response = await client.get<ProjectDetail>(`/project/${projectId}`);
  return response.data;
}

export async function undoAnalysisCorrection(analysisId: string) {
  const response = await client.post(`/analysis/${analysisId}/undo`);
  return response.data;
}

export async function redoAnalysisCorrection(analysisId: string) {
  const response = await client.post(`/analysis/${analysisId}/redo`);
  return response.data;
}

export async function getAnalysisHistory(analysisId: string) {
  const response = await client.get(`/analysis/${analysisId}/history`);
  return response.data;
}

// ── Export ─────────────────────────────────────────────────────────────────────
export function getExportUrl(analysisId: string, format: string): string {
  return `/api/export/${analysisId}/${format}`;
}

export async function getExportStatus(analysisId: string) {
  const response = await client.get(`/export/${analysisId}/status`);
  return response.data;
}

// ── Health check ───────────────────────────────────────────────────────────────
export async function checkHealth() {
  const response = await client.get('/health');
  return response.data;
}

export default client;
