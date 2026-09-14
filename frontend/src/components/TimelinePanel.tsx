// Structured timeline: NormalizedEvents earliest-known-time first, each
// expandable to show every TimeAssertion about it. Consumes GET
// /timeline's structured JSON only -- no CLI text parsing.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getTimeline } from '../api/client'

export function TimelinePanel() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const query = useQuery({ queryKey: ['timeline'], queryFn: () => getTimeline() })

  if (query.isLoading) return <p>Loading timeline...</p>
  if (query.isError) return <p className="error-text">{(query.error as Error).message}</p>
  if (!query.data) return null

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="view-panel" data-testid="timeline-panel">
      <h2>Timeline</h2>
      <p className="provenance-caption">
        Every NormalizedEvent, ordered by its earliest known TimeAssertion value (or ingest time
        when it has none). Expand an event to see every claim made about when it occurred --
        Witnessgraph never merges disagreeing claims into one adjudicated time; see
        Contradictions for events where those claims conflict.
      </p>
      {query.data.length === 0 && <p className="empty-note">No events in this case yet.</p>}
      <ul className="timeline-list">
        {query.data.map((entry) => (
          <li key={entry.id}>
            <button
              type="button"
              className="provenance-toggle"
              onClick={() => toggle(entry.id)}
              aria-expanded={expanded.has(entry.id)}
            >
              {expanded.has(entry.id) ? '▾' : '▸'} <strong>{entry.event_type}</strong>{' '}
              <code>{entry.id}</code>
            </button>
            {expanded.has(entry.id) && (
              <div className="provenance-body">
                <p>
                  entity_ids: {entry.entity_ids.length > 0 ? entry.entity_ids.join(', ') : '(none)'}
                </p>
                <p>
                  attributes:{' '}
                  {Object.entries(entry.attributes)
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join(', ') || '(none)'}
                </p>
                <p>time assertions:</p>
                {entry.time_assertions.length === 0 ? (
                  <p className="empty-note">No time assertion recorded for this event.</p>
                ) : (
                  <ul>
                    {entry.time_assertions.map((a) => (
                      <li key={a.id}>
                        {a.value} (precision: {a.precision}, source:{' '}
                        <code>{a.source_evidence_id}</code>)
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
