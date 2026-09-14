import { useQuery } from '@tanstack/react-query'
import { listContradictions } from '../api/client'

export function ContradictionsPanel() {
  const query = useQuery({ queryKey: ['contradictions'], queryFn: listContradictions })

  if (query.isLoading) return <p>Loading contradictions...</p>
  if (query.isError) return <p className="error-text">{(query.error as Error).message}</p>
  if (!query.data || query.data.length === 0) {
    return <p className="empty-note">No structural time contradictions detected in this case.</p>
  }

  return (
    <div className="contradictions-panel" data-testid="contradictions-panel">
      <p className="provenance-caption">
        Two TimeAssertions about the same event that cannot both be true. Neither assertion is
        marked as "the truth" -- this only reports that they disagree.
      </p>
      <ul>
        {query.data.map((c) => (
          <li key={`${c.subject_event_id}-${c.assertions.map((a) => a.id).join('-')}`}>
            <strong>Event</strong> <code>{c.subject_event_id}</code>
            <ul>
              {c.assertions.map((a) => (
                <li key={a.id}>
                  <code>{a.id}</code>: {a.value} (precision: {a.precision}, source:{' '}
                  <code>{a.source_evidence_id}</code>)
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  )
}
