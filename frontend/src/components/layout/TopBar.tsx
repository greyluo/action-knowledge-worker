import { useState } from 'react'

type Tab = 'workspace' | 'ontology' | 'policies' | 'topology'

interface TopBarProps {
  activeTab: Tab
  onTabChange: (tab: Tab) => void
}

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'workspace', label: 'Workspace' },
  { key: 'ontology', label: 'Ontology' },
  { key: 'policies', label: 'Policies' },
  { key: 'topology', label: 'Topology' },
]

export function TopBar({ activeTab, onTabChange }: TopBarProps) {
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      height: '48px',
      padding: '0 20px',
      background: 'var(--color-surface)',
      borderBottom: '1px solid var(--color-border)',
      flexShrink: 0,
      gap: '32px',
    }}>
      <style>{`
        .topbar-tab {
          position: relative;
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 500;
          letter-spacing: 0.02em;
          padding: 4px 0;
          border: none;
          background: none;
          cursor: pointer;
          transition: color 120ms ease;
        }
        .topbar-tab::after {
          content: '';
          position: absolute;
          bottom: -1px;
          left: 0; right: 0;
          height: 2px;
          border-radius: 2px 2px 0 0;
          background: var(--color-accent);
          transform: scaleX(0);
          transition: transform 150ms ease;
        }
        .topbar-tab.active::after { transform: scaleX(1); }
        .topbar-tab.active { color: var(--color-text) !important; }
      `}</style>

      {/* Brand mark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '9px', userSelect: 'none', flexShrink: 0 }}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="10" r="3" fill="var(--color-accent)" />
          <circle cx="3" cy="5" r="1.5" fill="var(--color-accent)" opacity="0.5" />
          <circle cx="17" cy="5" r="1.5" fill="var(--color-accent)" opacity="0.5" />
          <circle cx="3" cy="15" r="1.5" fill="var(--color-accent)" opacity="0.5" />
          <circle cx="17" cy="15" r="1.5" fill="var(--color-accent)" opacity="0.5" />
          <line x1="3" y1="5" x2="10" y2="10" stroke="var(--color-accent)" strokeWidth="0.8" opacity="0.35" />
          <line x1="17" y1="5" x2="10" y2="10" stroke="var(--color-accent)" strokeWidth="0.8" opacity="0.35" />
          <line x1="3" y1="15" x2="10" y2="10" stroke="var(--color-accent)" strokeWidth="0.8" opacity="0.35" />
          <line x1="17" y1="15" x2="10" y2="10" stroke="var(--color-accent)" strokeWidth="0.8" opacity="0.35" />
        </svg>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          fontWeight: 500,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: 'var(--color-text-muted)',
        }}>
          knowledge<span style={{ color: 'var(--color-accent)' }}>_</span>worker
        </span>
      </div>

      {/* Tab nav */}
      <nav style={{ display: 'flex', gap: '20px' }}>
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            className={`topbar-tab${activeTab === key ? ' active' : ''}`}
            style={{ color: hovered === key || activeTab === key ? 'var(--color-text)' : 'var(--color-text-muted)' }}
            onClick={() => onTabChange(key)}
            onMouseEnter={() => setHovered(key)}
            onMouseLeave={() => setHovered(null)}
          >
            {label}
          </button>
        ))}
      </nav>

    </header>
  )
}

export default TopBar
