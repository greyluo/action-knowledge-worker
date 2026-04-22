import { useState, useMemo, type CSSProperties } from 'react'
import type { Run, OntologyEvent, AgentSpec } from '../../types'

export interface RunsViewProps {
  runs: Run[]
  events: OntologyEvent[]
  agents: AgentSpec[]
}

function StatPill({ count, label }: { count: number; label: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        background: 'var(--color-surface-2)',
        border: '1px solid var(--color-border)',
        borderRadius: '20px',
        padding: '3px 10px',
        fontSize: '12px',
        fontFamily: 'var(--font-sans)',
        color: 'var(--color-text-muted)',
      }}
    >
      <span style={{ color: 'var(--color-accent)', fontWeight: 700 }}>{count}</span>
      {' '}{label}
    </span>
  )
}

function formatDuration(startedAt: string, endedAt: string | null): string {
  const start = new Date(startedAt).getTime()
  const end = endedAt ? new Date(endedAt).getTime() : Date.now()
  const totalSeconds = Math.floor((end - start) / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) return `${seconds}s`
  return `${minutes}m ${seconds}s`
}

function StatusPill({ status }: { status: string }) {
  const s = status.toLowerCase()

  let color: string
  let bg: string

  if (s === 'completed' || s === 'done') {
    color = 'var(--color-success)'
    bg = 'var(--color-success-bg)'
  } else if (s === 'running' || s === 'in_progress') {
    color = 'var(--color-warning)'
    bg = 'var(--color-warning-bg)'
  } else if (s === 'failed' || s === 'error') {
    color = 'var(--color-error)'
    bg = 'var(--color-error-bg)'
  } else {
    color = 'var(--color-text-muted)'
    bg = 'var(--color-surface-3)'
  }

  const label = s === 'completed' ? 'done' : s === 'in_progress' ? 'running' : s

  return (
    <span
      style={{
        padding: '1px 6px',
        background: bg,
        borderRadius: '3px',
        fontSize: '10px',
        fontFamily: 'var(--font-sans)',
        fontWeight: 600,
        color,
        textTransform: 'lowercase',
        letterSpacing: '0.02em',
      }}
    >
      {label}
    </span>
  )
}

function RunRow({
  run,
  agentName,
  selected,
  onClick,
}: {
  run: Run
  agentName: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <div
      className="runs-run-row"
      onClick={onClick}
      style={{
        padding: '10px 16px',
        borderBottom: '1px solid var(--color-border)',
        borderLeft: selected
          ? '2px solid var(--color-accent)'
          : '2px solid transparent',
        background: selected ? 'var(--color-accent-bg)' : 'transparent',
        cursor: 'pointer',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '4px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--color-text-muted)',
              flexShrink: 0,
            }}
          >
            {run.id.slice(0, 8)}
          </span>
          <span
            style={{
              fontSize: '13px',
              fontFamily: 'var(--font-sans)',
              color: 'var(--color-text)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {agentName}
          </span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <StatusPill status={run.status} />
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--color-text-muted)',
          }}
        >
          {formatDuration(run.started_at, run.ended_at)}
        </span>
      </div>
    </div>
  )
}

const EVENT_BADGE_STYLES: Record<string, { color: string; bg: string }> = {
  entity_created: {
    color: 'var(--color-success)',
    bg: 'var(--color-success-bg)',
  },
  type_created: {
    color: 'var(--color-warning)',
    bg: 'var(--color-warning-bg)',
  },
  edge_type_created: {
    color: 'var(--color-accent)',
    bg: 'var(--color-accent-bg)',
  },
}

function EventTypeBadge({ eventType }: { eventType: string }) {
  const style = EVENT_BADGE_STYLES[eventType] ?? {
    color: 'var(--color-text-muted)',
    bg: 'var(--color-surface-3)',
  }

  return (
    <span
      style={{
        padding: '1px 6px',
        background: style.bg,
        borderRadius: '3px',
        fontSize: '10px',
        fontFamily: 'var(--font-sans)',
        fontWeight: 600,
        color: style.color,
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}
    >
      {eventType}
    </span>
  )
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    return `${hh}:${mm}:${ss}`
  } catch {
    return '--:--:--'
  }
}

function EventRow({ event }: { event: OntologyEvent }) {
  return (
    <div
      className="runs-event-row"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '6px 8px',
        borderRadius: 'var(--radius-sm)',
        cursor: 'default',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          color: 'var(--color-text-muted)',
          flexShrink: 0,
        }}
      >
        {formatTime(event.created_at)}
      </span>
      <EventTypeBadge eventType={event.event_type} />
      <span
        style={{
          fontSize: '13px',
          fontFamily: 'var(--font-sans)',
          color: 'var(--color-text)',
          flex: '1 1 auto',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {event.entity_name ?? '—'}
      </span>
    </div>
  )
}

const panelHeaderStyle: CSSProperties = {
  fontSize: '11px',
  fontWeight: 600,
  fontFamily: 'var(--font-sans)',
  color: 'var(--color-text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  padding: '12px 16px 8px',
  flexShrink: 0,
}

const emptyStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '48px 16px',
  fontSize: '13px',
  fontFamily: 'var(--font-sans)',
  color: 'var(--color-text-dim)',
}

export function RunsView({ runs, events, agents }: RunsViewProps) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const agentMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const a of agents) m.set(a.id, a.name)
    return m
  }, [agents])

  const filteredEvents = useMemo(() => {
    const base = selectedRunId
      ? events.filter((e) => e.run_id === selectedRunId)
      : events
    return [...base].sort((a, b) => b.created_at.localeCompare(a.created_at))
  }, [events, selectedRunId])

  const handleRunClick = (id: string) => {
    setSelectedRunId((prev) => (prev === id ? null : id))
  }

  return (
    <>
      <style>{`
        .runs-run-row:hover { background: var(--color-surface-2) !important; }
        .runs-event-row:hover { background: var(--color-surface-2) !important; }
      `}</style>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          background: 'var(--color-bg)',
          fontFamily: 'var(--font-sans)',
          overflow: 'hidden',
        }}
      >
        {/* Stat bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: '44px',
            padding: '0 20px',
            flexShrink: 0,
            borderBottom: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
          }}
        >
          <span
            style={{
              fontSize: '13px',
              fontWeight: 600,
              fontFamily: 'var(--font-sans)',
              color: 'var(--color-text)',
            }}
          >
            Runs
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <StatPill count={runs.length} label="runs" />
            <StatPill count={events.length} label="events" />
          </div>
        </div>

        {/* Split layout */}
        <div style={{ display: 'flex', flex: '1 1 auto', overflow: 'hidden' }}>
          {/* Left — Runs list */}
          <div
            style={{
              width: '280px',
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              borderRight: '1px solid var(--color-border)',
            }}
          >
            <div style={panelHeaderStyle}>Runs</div>
            <div style={{ flex: '1 1 auto', overflowY: 'auto' }}>
              {runs.length === 0 ? (
                <div style={emptyStyle}>No runs</div>
              ) : (
                runs.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    agentName={agentMap.get(run.spec_id) ?? run.spec_id.slice(0, 8)}
                    selected={selectedRunId === run.id}
                    onClick={() => handleRunClick(run.id)}
                  />
                ))
              )}
            </div>
          </div>

          {/* Right — Events */}
          <div
            style={{
              flex: '1 1 auto',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                ...panelHeaderStyle,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: '8px',
              }}
            >
              {selectedRunId ? (
                <span>
                  Showing events for run{' '}
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text)' }}>
                    {selectedRunId.slice(0, 8)}
                  </span>
                </span>
              ) : (
                <span>Events</span>
              )}
              {selectedRunId && (
                <button
                  onClick={() => setSelectedRunId(null)}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: '0',
                    cursor: 'pointer',
                    fontSize: '11px',
                    fontFamily: 'var(--font-sans)',
                    color: 'var(--color-accent)',
                    fontWeight: 500,
                    textTransform: 'none',
                    letterSpacing: 'normal',
                  }}
                >
                  Clear
                </button>
              )}
            </div>
            <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '0 8px 16px' }}>
              {filteredEvents.length === 0 ? (
                <div style={emptyStyle}>No events</div>
              ) : (
                filteredEvents.map((event) => (
                  <EventRow key={event.id} event={event} />
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export default RunsView
