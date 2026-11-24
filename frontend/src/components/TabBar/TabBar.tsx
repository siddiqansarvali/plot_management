/**
 * Tab bar — shown when analysis results are available.
 */

import { useAnalysisStore, type ActiveTab } from '../../store/analysisStore';

const TABS: { id: ActiveTab; label: string; icon: string }[] = [
  { id: 'upload',     label: 'Upload',     icon: '＋' },
  { id: 'analysis',  label: 'Overview',   icon: '◉' },
  { id: 'ocr',       label: 'OCR',        icon: 'T' },
  { id: 'preprocessed', label: 'Analysis image', icon: '◧' },
  { id: 'annotated', label: 'Annotated preview', icon: '▧' },
  { id: 'cad',       label: 'CAD layout', icon: '◇' },
  { id: 'redraw',    label: 'Digital redraw', icon: '▱' },
  { id: 'correction', label: 'Edit boundary', icon: '⌁' },
  { id: 'calibration', label: 'Calibration', icon: '◧' },
  { id: 'export',    label: 'Export',      icon: '↓' },
];

export default function TabBar() {
  const { activeTab, setActiveTab } = useAnalysisStore();

  return (
    <div className="flex items-center gap-1 px-6 py-2 border-b flex-shrink-0 overflow-x-auto"
         style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-subtle)' }}>
      {TABS.map(tab => (
        <button
          key={tab.id}
          onClick={() => setActiveTab(tab.id)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                      transition-all duration-150 whitespace-nowrap
                      ${activeTab === tab.id
                        ? 'text-white'
                        : ''}`}
          style={activeTab === tab.id
            ? { background: 'rgba(14,165,233,0.2)', color: '#0ea5e9', border: '1px solid rgba(14,165,233,0.3)' }
            : { color: 'var(--text-secondary)', border: '1px solid transparent' }}
        >
          <span>{tab.icon}</span>
          {tab.label}
        </button>
      ))}
    </div>
  );
}
