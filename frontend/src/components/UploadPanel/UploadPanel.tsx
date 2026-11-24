/**
 * Upload Panel — drag-and-drop / file picker for survey images.
 * Phase 1: Full implementation.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

interface Props {
  onFileSelected: (file: File) => void;
  isUploading: boolean;
  uploadProgress: number;
  error: string | null;
  targetPlotNumber: string;
  onTargetPlotChange: (v: string) => void;
}

const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp'];
const MAX_SIZE_MB = 50;

export default function UploadPanel({
  onFileSelected, isUploading, uploadProgress, error,
  targetPlotNumber, onTargetPlotChange,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const handleFile = useCallback((file: File) => {
    setValidationError(null);
    if (!ACCEPTED.includes(file.type)) {
      setValidationError(`Unsupported type: ${file.type}. Use PNG, JPG, or WEBP.`);
      return;
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      setValidationError(`File too large. Maximum size is ${MAX_SIZE_MB} MB.`);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    onFileSelected(file);
  }, [onFileSelected]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = '';
  };

  const displayError = validationError || error;

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-4"
             style={{ background: 'linear-gradient(135deg, rgba(14,165,233,0.2), rgba(99,102,241,0.2))', border: '1px solid rgba(14,165,233,0.3)' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#0ea5e9" strokeWidth="1.5">
            <path d="M12 16V8M8 12l4-4 4 4" strokeLinecap="round" strokeLinejoin="round"/>
            <rect x="3" y="3" width="18" height="18" rx="3" strokeLinecap="round"/>
          </svg>
        </div>
        <h2 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
          Upload Survey Document
        </h2>
        <p className="text-sm max-w-md mx-auto" style={{ color: 'var(--text-secondary)' }}>
          Upload a surveyor's plot layout image. The system will extract text, detect geometry,
          validate measurements, and reconstruct a digital layout from the actual content.
        </p>
      </div>

      {/* Optional target plot */}
      <div className="card p-4 space-y-2">
        <label className="block text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
          Target Plot Number (optional)
        </label>
        <input
          type="text"
          className="input"
          placeholder="e.g. 24 — leave blank to auto-detect the main plot"
          value={targetPlotNumber}
          onChange={e => onTargetPlotChange(e.target.value)}
          disabled={isUploading}
        />
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          If specified, the system will search for this plot number specifically.
        </p>
      </div>

      {/* Drop zone */}
      <div
        className={`upload-zone p-10 text-center cursor-pointer transition-all duration-300 ${dragging ? 'drag-over' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !isUploading && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".png,.jpg,.jpeg,.webp"
          className="hidden"
          onChange={onInputChange}
          disabled={isUploading}
        />

        {previewUrl ? (
          <div className="space-y-3">
            <img
              src={previewUrl}
              alt="Survey preview"
              className="max-h-64 mx-auto rounded-lg object-contain"
              style={{ border: '1px solid var(--border-subtle)' }}
            />
            {!isUploading && (
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                Click or drop to replace
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center"
                 style={{ background: 'var(--bg-elevated)', border: '2px dashed var(--border-subtle)' }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
                   stroke="var(--text-muted)" strokeWidth="1.5">
                <path d="M12 16V8M8 12l4-4 4 4" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M3 16v2a2 2 0 002 2h14a2 2 0 002-2v-2" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <p className="font-medium" style={{ color: 'var(--text-primary)' }}>
                Drop survey image here
              </p>
              <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
                or click to browse — PNG, JPG, WEBP up to {MAX_SIZE_MB}MB
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Upload progress */}
      {isUploading && (
        <div className="card p-4 space-y-2 animate-fade-in">
          <div className="flex items-center justify-between text-sm">
            <span style={{ color: 'var(--text-secondary)' }}>Uploading…</span>
            <span className="value-mono">{uploadProgress}%</span>
          </div>
          <div className="confidence-bar">
            <div className="confidence-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
        </div>
      )}

      {/* Error */}
      {displayError && (
        <div className="p-4 rounded-lg animate-fade-in"
             style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <p className="text-sm" style={{ color: '#ef4444' }}>⚠ {displayError}</p>
        </div>
      )}

      {/* Disclaimer */}
      <div className="p-3 rounded-lg text-xs space-y-1"
           style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
        <p className="font-medium" style={{ color: 'var(--text-secondary)' }}>Important</p>
        <p>This system extracts information from the uploaded survey image only. It will report
           what it can determine and clearly indicate what it cannot. Results should be verified
           by a qualified surveyor before any legal or construction use.</p>
      </div>
    </div>
  );
}
