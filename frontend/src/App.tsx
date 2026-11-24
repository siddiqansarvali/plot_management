import { useCallback, useEffect, useRef, useState } from 'react';
import { useAnalysisStore } from './store/analysisStore';
import { checkHealth, createProject, getAnalysisResult, triggerAnalysis, uploadSurveyImage } from './api/client';
import UploadPanel from './components/UploadPanel/UploadPanel';
import AnalysisProgress from './components/AnalysisProgress/AnalysisProgress';
import OriginalViewer from './components/OriginalViewer/OriginalViewer';
import AnnotatedViewer from './components/AnnotatedViewer/AnnotatedViewer';
import DigitalRedraw from './components/DigitalRedraw/DigitalRedraw';
import GeometryEditor from './components/GeometryEditor/GeometryEditor';
import CalibrationPanel from './components/CalibrationPanel/CalibrationPanel';
import ExportPanel from './components/ExportPanel/ExportPanel';
import ProjectSidebar from './components/ProjectSidebar/ProjectSidebar';
import OverviewScreen from './components/Overview/OverviewScreen';
import AnalysisScreen from './components/AnalysisScreen/AnalysisScreen';
import ValidationScreen from './components/ValidationScreen/ValidationScreen';

const POLLING_INTERVAL_MS = 1800;
const MAX_POLL_ATTEMPTS = 300;

// Primary workflow steps
const WORKFLOW_STEPS = [
  { id: 'upload',   label: 'Upload' },
  { id: 'overview', label: 'Overview' },
  { id: 'analysis', label: 'Analysis' },
  { id: 'plan',     label: 'Digital Plan' },
  { id: 'edit',     label: 'Edit' },
  { id: 'validate', label: 'Validate' },
  { id: 'export',   label: 'Export' },
] as const;

export default function App() {
  const store = useAnalysisStore();
  const pollCount = useRef(0);
  const runToken = useRef(0);
  const [serviceReady, setServiceReady] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(() => setServiceReady(true)).catch(() => setServiceReady(false));
  }, []);

  const monitorDocument = useCallback((documentId: string, token: number) => {
    pollCount.current = 0;
    let busy = false;
    const intervalId = setInterval(async () => {
      if (runToken.current !== token || busy) return;
      busy = true;
      pollCount.current += 1;
      try {
        const result = await getAnalysisResult(documentId);
        if (runToken.current !== token) return;
        store.setAnalysis(result);
        if (['completed', 'partial'].includes(result.status)) {
          clearInterval(intervalId);
          store.setPollingInterval(null);
          store.setPhase('complete');
          store.setActiveTab('overview');
        } else if (result.status === 'failed') {
          clearInterval(intervalId);
          store.setPollingInterval(null);
          store.setPhase('error');
          store.setUploadError(result.error_message || 'Analysis failed.');
        } else if (pollCount.current > MAX_POLL_ATTEMPTS) {
          clearInterval(intervalId);
          store.setPollingInterval(null);
          store.setPhase('error');
          store.setUploadError('Analysis timed out. Please check the backend service and try again.');
        }
      } catch {
        if (runToken.current !== token) return;
        if (pollCount.current > MAX_POLL_ATTEMPTS) {
          clearInterval(intervalId);
          store.setPollingInterval(null);
          store.setPhase('error');
          store.setUploadError('The analysis status could not be retrieved. Please retry.');
        }
      } finally {
        busy = false;
      }
    }, POLLING_INTERVAL_MS);
    store.setPollingInterval(intervalId);
  }, [store]);

  const handleFileSelected = useCallback(async (file: File) => {
    const token = ++runToken.current;
    const requestedPlot = store.targetPlotNumber.trim();
    let projectId = store.projectId;
    store.resetAll();
    store.setFile(file);
    store.setPhase('uploading');

    try {
      if (!projectId) {
        const projectName = file.name.replace(/\.[^.]+$/, '').slice(0, 255) || 'Survey project';
        const project = await createProject(projectName);
        if (runToken.current !== token) return;
        projectId = project.id;
      }
      store.setProjectId(projectId);

      store.setUploading(true);
      const upload = await uploadSurveyImage(file, projectId, store.setUploadProgress);
      if (runToken.current !== token) return;
      store.setDocumentId(upload.document_id);
      store.setUploading(false);
      window.dispatchEvent(new Event('plotline:refresh-projects'));

      store.setPhase('analyzing');
      await triggerAnalysis(upload.document_id, requestedPlot || undefined);
      if (runToken.current !== token) return;
      monitorDocument(upload.document_id, token);
    } catch (err: unknown) {
      if (runToken.current !== token) return;
      store.setUploading(false);
      store.setPhase('error');
      const message = err instanceof Error ? err.message : 'Upload or analysis could not start.';
      store.setUploadError(message);
    }
  }, [store, monitorDocument]);

  const handleDocumentSelect = useCallback(async (documentId: string, projectId: string) => {
    const token = ++runToken.current;
    store.resetAll();
    store.setProjectId(projectId);
    store.setDocumentId(documentId);
    store.setPhase('analyzing');
    store.setActiveTab('overview');
    try {
      const result = await getAnalysisResult(documentId);
      if (runToken.current !== token) return;
      store.setAnalysis(result);
      if (result.status === 'completed' || result.status === 'partial') {
        store.setPhase('complete');
      } else if (result.status === 'failed') {
        store.setPhase('error');
        store.setUploadError(result.error_message || 'This survey analysis failed.');
      } else {
        if (result.status === 'not_started') await triggerAnalysis(documentId);
        if (runToken.current !== token) return;
        monitorDocument(documentId, token);
      }
    } catch (err) {
      if (runToken.current !== token) return;
      store.setPhase('error');
      store.setUploadError(err instanceof Error ? err.message : 'Saved survey could not be opened.');
    }
  }, [store, monitorDocument]);

  useEffect(() => () => {
    if (store.pollingIntervalId) clearInterval(store.pollingIntervalId);
  }, [store.pollingIntervalId]);

  const { phase, analysis, activeTab, upload } = store;
  const hasResults = !!analysis && (phase === 'complete' || phase === 'error');
  const isRunning = phase === 'uploading' || phase === 'analyzing';

  // Determine current step index for progress indicator
  const currentStepIndex = WORKFLOW_STEPS.findIndex(s => s.id === activeTab);

  return (
    <div className="app-shell">
      <ProjectSidebar
        activeProjectId={store.projectId}
        onProjectSelect={store.setProjectId}
        onDocumentSelect={handleDocumentSelect}
      />
      <div className="workspace-main">
        <header className="app-header">
          <div className="brand-lockup">
            <div className="brand-mark" aria-hidden="true"><span /></div>
            <div>
              <h1>Plotline <span>Survey workspace</span></h1>
            </div>
          </div>

          {/* Workflow step indicator — shown when we have results */}
          {hasResults && (
            <nav className="workflow-steps" aria-label="Survey workflow">
              {WORKFLOW_STEPS.map((step, idx) => {
                const isActive = activeTab === step.id;
                const isComplete = currentStepIndex > idx;
                const isAccessible = idx === 0 || hasResults;
                return (
                  <button
                    key={step.id}
                    className={`workflow-step ${isActive ? 'is-active' : ''} ${isComplete ? 'is-complete' : ''}`}
                    onClick={() => isAccessible && store.setActiveTab(step.id as any)}
                    disabled={!isAccessible}
                    aria-current={isActive ? 'step' : undefined}
                  >
                    <span className="step-num">{idx + 1}</span>
                    <span className="step-label">{step.label}</span>
                  </button>
                );
              })}
            </nav>
          )}

          <div className="header-actions">
            <span className={`service-pill ${serviceReady ? 'is-ready' : serviceReady === false ? 'is-down' : ''}`}>
              <i />{serviceReady === null ? 'Connecting' : serviceReady ? 'API connected' : 'API unavailable'}
            </span>
            {hasResults && (
              <button className="btn-secondary" onClick={() => { store.resetAll(); store.setActiveTab('upload'); }}>
                New survey
              </button>
            )}
          </div>
        </header>

        <main className="workspace-content">
          {/* Upload screen */}
          {(phase === 'idle' || activeTab === 'upload') && !isRunning && (
            <div className="upload-page animate-fade-in">
              <UploadPanel
                onFileSelected={handleFileSelected}
                isUploading={upload.isUploading}
                uploadProgress={upload.uploadProgress}
                error={upload.uploadError}
                targetPlotNumber={store.targetPlotNumber}
                onTargetPlotChange={store.setTargetPlotNumber}
              />
            </div>
          )}

          {/* Analysis in progress */}
          {isRunning && <AnalysisProgress />}

          {/* Main workflow screens */}
          {hasResults && activeTab === 'overview' && (
            <OverviewScreen onNavigate={tab => store.setActiveTab(tab as any)} />
          )}

          {hasResults && activeTab === 'analysis' && (
            <AnalysisScreen />
          )}

          {hasResults && activeTab === 'plan' && (
            <DigitalRedraw />
          )}

          {hasResults && activeTab === 'edit' && (
            <GeometryEditor />
          )}

          {hasResults && activeTab === 'validate' && (
            <ValidationScreen onNavigate={tab => store.setActiveTab(tab as any)} />
          )}

          {hasResults && activeTab === 'export' && (
            <ExportPanel />
          )}

          {/* Diagnostics / legacy tabs — still accessible via URL or overview links */}
          {hasResults && activeTab === 'calibration' && <CalibrationPanel />}
          {hasResults && activeTab === 'ocr' && (
            <div className="single-panel">
              <div className="card p-4">
                <p className="section-header">OCR Tokens ({analysis?.ocr_results?.length ?? 0})</p>
                <div className="ocr-token-grid">
                  {(analysis?.ocr_results ?? []).map(r => (
                    <div key={r.id} className="ocr-token-row">
                      <span className="ocr-token-text">{r.text}</span>
                      <span className="ocr-token-conf">{Math.round(r.confidence * 100)}%</span>
                      {r.category && <span className="badge badge-neutral" style={{ fontSize: '0.6rem' }}>{r.category}</span>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          {hasResults && activeTab === 'preprocessed' && (
            <div className="single-panel">
              <OriginalViewer />
            </div>
          )}
          {hasResults && activeTab === 'annotated' && (
            <div className="single-panel">
              <AnnotatedViewer />
            </div>
          )}

          {/* Error banner */}
          {phase === 'error' && activeTab !== 'upload' && upload.uploadError && (
            <div className="error-banner" role="alert">{upload.uploadError}</div>
          )}
        </main>

        <footer className="workspace-footer">
          <span>Evidence first · Original files are preserved · Geometry is never filled in by default</span>
          {upload.file && <span>{upload.file.name}</span>}
        </footer>
      </div>
    </div>
  );
}
