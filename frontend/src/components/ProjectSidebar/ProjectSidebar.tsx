import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { createProject, getProject, listProjects } from '../../api/client';
import type { Project, ProjectDocument } from '../../types';

interface Props {
  activeProjectId: string | null;
  onProjectSelect: (id: string | null) => void;
  onDocumentSelect: (documentId: string, projectId: string) => void;
}

export default function ProjectSidebar({ activeProjectId, onProjectSelect, onDocumentSelect }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [collapsed, setCollapsed] = useState(() => window.matchMedia('(max-width: 800px)').matches);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<ProjectDocument[]>([]);

  useEffect(() => {
    const refresh = () => {
      listProjects().then(setProjects).catch(() => setError('Projects could not be loaded.'));
      if (expandedProjectId) {
        getProject(expandedProjectId).then(detail => setDocuments(detail.documents)).catch(() => {});
      }
    };
    refresh();
    window.addEventListener('plotline:refresh-projects', refresh);
    return () => window.removeEventListener('plotline:refresh-projects', refresh);
  }, [expandedProjectId]);

  const submitProject = async (event: FormEvent) => {
    event.preventDefault();
    const cleanName = name.trim();
    if (!cleanName) return;
    try {
      const project = await createProject(cleanName);
      setProjects(current => [project, ...current]);
      onProjectSelect(project.id);
      setExpandedProjectId(project.id);
      setDocuments([]);
      setName('');
      setCreating(false);
      setError(null);
    } catch {
      setError('Project could not be created.');
    }
  };

  const toggleProject = async (projectId: string) => {
    onProjectSelect(projectId);
    if (expandedProjectId === projectId) {
      setExpandedProjectId(null);
      return;
    }
    setExpandedProjectId(projectId);
    try {
      const detail = await getProject(projectId);
      setDocuments(detail.documents);
    } catch {
      setError('Project documents could not be loaded.');
    }
  };

  if (collapsed) {
    return (
      <aside className="project-sidebar is-collapsed">
        <button className="sidebar-collapse" onClick={() => setCollapsed(false)} aria-label="Expand projects">›</button>
        <div className="sidebar-mini-mark">P</div>
      </aside>
    );
  }

  return (
    <aside className="project-sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-mark">P</div>
        <div><strong>Plotline</strong><span>Land survey tools</span></div>
        <button className="sidebar-collapse" onClick={() => setCollapsed(true)} aria-label="Collapse projects">‹</button>
      </div>

      <button className="sidebar-new-survey" onClick={() => onProjectSelect(null)}>
        <span>＋</span> New survey
      </button>

      <div className="sidebar-section-title">
        <span>PROJECTS</span>
        <button onClick={() => { setCreating(value => !value); setError(null); }} aria-label="Create project">＋</button>
      </div>
      {creating && (
        <form className="project-create-form" onSubmit={submitProject}>
          <input className="input" autoFocus maxLength={255} value={name} onChange={event => setName(event.target.value)} placeholder="Project name" />
          <div className="flex gap-2">
            <button className="btn-primary flex-1" type="submit" disabled={!name.trim()}>Create</button>
            <button className="btn-ghost" type="button" onClick={() => setCreating(false)}>Cancel</button>
          </div>
        </form>
      )}

      <nav className="project-list" aria-label="Projects">
        {projects.length === 0 ? (
          <div className="sidebar-empty">Your projects will appear here. Uploading a survey can create one automatically.</div>
        ) : projects.map(project => (
          <div className="project-group" key={project.id}>
            <button
              className={`project-row ${activeProjectId === project.id ? 'is-active' : ''}`}
              onClick={() => toggleProject(project.id)}
              title={`${project.name} · ${project.document_count} documents`}
            >
              <span className="project-glyph">▧</span>
              <span className="project-row-copy"><strong>{project.name}</strong><small>{project.document_count} documents</small></span>
              {activeProjectId === project.id && <span className="project-active-dot" />}
            </button>
            {expandedProjectId === project.id && (
              <div className="document-list">
                {documents.length ? documents.map(document => (
                  <button key={document.id} className="document-row" onClick={() => onDocumentSelect(document.id, project.id)}>
                    <span aria-hidden="true">▤</span>
                    <span><strong>{document.original_filename}</strong><small>{document.status} · {new Date(document.uploaded_at).toLocaleDateString()}</small></span>
                  </button>
                )) : <p className="document-list-empty">No surveys saved in this project yet.</p>}
              </div>
            )}
          </div>
        ))}
      </nav>
      {error && <p className="sidebar-error" role="status">{error}</p>}

      <div className="sidebar-status-card">
        <span className="status-dot status-dot-ok" />
        <div><strong>Private workspace</strong><small>Analysis runs on your local backend</small></div>
      </div>
      <div className="sidebar-footer">Plotline <span>·</span> Survey analysis</div>
    </aside>
  );
}
